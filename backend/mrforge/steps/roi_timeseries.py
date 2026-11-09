"""Mean time series of the regions of an atlas, from a functional image in standard space.

The atlases are on FSL's MNI152 2 mm grid, so the image must be on that grid too (the result of
the standard-space step at 2 mm); nothing is resampled here. One call of
``fslmeants --label=<atlas>`` gives one mean time series per region.

By default only voxels that carry signal are averaged: a voxel outside the brain of the
recording (or lost to dropout) would pull the regional mean towards zero or add noise. "Carries
signal" means: inside the brain mask of the recording in standard space (the one the
standard-space step writes) when it is given, otherwise a voxel that varies over time. Checked
on real data: cleaned (ICA-denoised) data is not masked, every voxel of the grid varies, so
only the brain mask tells the brain from the rest there. The number of voxels used and the
coverage (voxels with signal / voxels of the region) are recorded for every region and low
coverage is flagged; nothing is excluded automatically (CLAUDE.md principle 6).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from pydantic import BaseModel

from mrforge import atlases
from mrforge.niftiutil import image_info, is_readable_nifti
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.fsl_anat import STANDARD_SPACE
from mrforge.steps.qcpics import known_slices, slice_row, slices_dir
from mrforge.steps.registry import register_step

# REVIEW(domain): regions with less than half of their voxels carrying signal are flagged.
MIN_COVERAGE = 0.5


class RoiTimeseriesInput(BaseModel):
    bold: str  # 4D functional image on the FSL MNI152 2 mm grid
    # the recording's brain mask on the same grid (from the standard-space step); optional
    brain_mask: str | None = None


class RoiTimeseriesParams(BaseModel):
    atlas: str = "schaefer100n7"  # one of the bundled atlases (mrforge.atlases)
    # REVIEW(domain): average only voxels with signal (temporal std > 0). False averages every
    # voxel of the region, as the lab's own scripts do.
    only_voxels_with_signal: bool = True
    min_coverage: float = MIN_COVERAGE  # flag regions below this share of voxels with signal


class RoiTimeseriesOutput(BaseModel):
    timeseries: str  # volumes as rows, one column per region (header: clean names)
    roi_info: str  # JSON: settings, region order, voxel counts, coverage, flags
    atlas_used: str  # the atlas as used (voxels without signal removed): viewer overlay
    qc_picture: str


def region_table(
    atlas: np.ndarray[Any, Any],
    used: np.ndarray[Any, Any],
    regions: tuple[atlases.Region, ...],
    min_coverage: float,
) -> list[dict[str, Any]]:
    """Per region: voxels in the atlas, voxels used, coverage and flags. Pure function."""
    rows: list[dict[str, Any]] = []
    for r in regions:
        n_atlas = int((atlas == r.label).sum())
        n_used = int((used == r.label).sum())
        coverage = n_used / n_atlas if n_atlas else 0.0
        rows.append(
            {
                "label": r.label,
                "name": r.clean_name,
                "network": r.network,
                "voxels_in_atlas": n_atlas,
                "voxels_used": n_used,
                "coverage": round(coverage, 4),
                "empty": n_used == 0,
                "low_coverage": 0 < n_used and coverage < min_coverage,
            }
        )
    return rows


def spread_columns(
    meants: np.ndarray[Any, Any], used_labels: list[int], regions: tuple[atlases.Region, ...]
) -> np.ndarray[Any, Any]:
    """Put the columns of ``fslmeants --label`` at the right place of the full region list.

    Checked on FSL 6.0.7: it writes one column for every integer from 1 to the highest label
    value of the label image, also for values that have no voxel (AAL3: 170 columns for 166
    regions). So the column of label L is column L - 1, never a position in the region list.
    Regions without any voxel with signal get NaN, whatever fslmeants wrote for them."""
    if meants.ndim == 1:
        meants = meants[:, None]
    highest = max(used_labels)
    if meants.shape[1] != highest:
        raise ValueError(
            f"fslmeants gave {meants.shape[1]} columns, expected {highest} (one per label value "
            f"from 1 to {highest})"
        )
    out = np.full((meants.shape[0], len(regions)), np.nan, dtype=np.float64)
    present = set(used_labels)
    for j, r in enumerate(regions):
        if r.label in present:
            out[:, j] = meants[:, r.label - 1]
    return out


def write_timeseries(path: Path, values: np.ndarray[Any, Any], header: list[str]) -> None:
    with path.open("w") as f:
        f.write("\t".join(header) + "\n")
        for row in values:
            f.write("\t".join(f"{v:.6f}" for v in row) + "\n")


@register_step
class RoiTimeseriesStep(Step[RoiTimeseriesInput, RoiTimeseriesParams, RoiTimeseriesOutput]):
    name = "roi_timeseries"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = RoiTimeseriesInput, RoiTimeseriesParams, RoiTimeseriesOutput
    requires_fsl = True
    datatype = "func"

    def expected_outputs(
        self, ctx: StepContext[RoiTimeseriesInput, RoiTimeseriesParams]
    ) -> RoiTimeseriesOutput:
        n = ctx.bids_name
        e = {"space": STANDARD_SPACE, "seg": ctx.params.atlas}
        return RoiTimeseriesOutput(
            timeseries=n("timeseries", ".tsv", **e),
            roi_info=n("roi", ".json", **e),
            atlas_used=n("dseg", **e),
            qc_picture=n("qc", ".png", **e, desc="roi"),
        )

    def validate_inputs(
        self, ctx: StepContext[RoiTimeseriesInput, RoiTimeseriesParams]
    ) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        try:
            atlases.volume_path(ctx.params.atlas)
        except atlases.AtlasError as err:
            return [
                Problem(
                    code="ATLAS_UNKNOWN",
                    message=str(err),
                    probable_cause="The atlas name is not one of the atlases of this app.",
                    suggested_action="Choose an atlas from the list.",
                )
            ]
        path = ctx.input_path(ctx.inputs.bold)
        if not is_readable_nifti(path):
            return [
                Problem(
                    code="INPUT_NOT_NIFTI",
                    message=f"An image could not be read: {ctx.inputs.bold}",
                    probable_cause="The file is damaged or incomplete.",
                    suggested_action="Run the step that makes it again.",
                )
            ]
        mask = ctx.inputs.brain_mask
        if mask and not is_readable_nifti(ctx.input_path(mask)):
            return [
                Problem(
                    code="INPUT_NOT_NIFTI",
                    message=f"An image could not be read: {mask}",
                    probable_cause="The file is damaged or incomplete.",
                    suggested_action="Run the step that makes it again.",
                )
            ]
        shape, zooms = image_info(path)
        if len(shape) != 4:
            return [
                Problem(
                    code="BOLD_NOT_4D",
                    message="The functional image is not a time series (4D image).",
                    probable_cause="A single volume or a mask was given instead of the data.",
                    suggested_action="Choose the standard-space functional result of the run.",
                )
            ]
        if shape[:3] != atlases.GRID_SHAPE or any(abs(z - 2.0) > 0.01 for z in zooms[:3]):
            return [
                Problem(
                    code="NOT_ON_MNI_2MM_GRID",
                    message=(
                        f"The image has size {shape[:3]} with {zooms[0]:g} mm voxels; the atlases "
                        f"need {atlases.GRID_SHAPE} (FSL MNI152, 2 mm)."
                    ),
                    probable_cause=(
                        "The image is not in standard space, or standard space was made at 1 mm "
                        "or in another template."
                    ),
                    suggested_action="Run 'Standard space' with a 2 mm grid, then try again.",
                )
            ]
        if mask and image_info(ctx.input_path(mask))[0] != shape[:3]:
            return [
                Problem(
                    code="MASK_GRID_DIFFERS",
                    message="The brain mask is not on the same grid as the functional image.",
                    probable_cause="The mask belongs to another run or another standard space.",
                    suggested_action="Use the brain mask written by the standard-space step.",
                )
            ]
        return []

    def prepare(self, ctx: StepContext[RoiTimeseriesInput, RoiTimeseriesParams]) -> None:
        super().prepare(ctx)
        shutil.rmtree(ctx.run_dir / "work", ignore_errors=True)

    def run(self, ctx: StepContext[RoiTimeseriesInput, RoiTimeseriesParams]) -> StepResult:
        p = ctx.params
        out = self.expected_outputs(ctx)
        bold = ctx.input_path(ctx.inputs.bold)
        work = ctx.run_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        atlas_file = atlases.volume_path(p.atlas)
        used_file = ctx.output_dir / out.atlas_used
        if p.only_voxels_with_signal:
            signal = work / "signal"
            argv = ["fslmaths", str(bold), "-Tstd", "-bin"]
            if ctx.inputs.brain_mask:
                argv += ["-mas", str(ctx.input_path(ctx.inputs.brain_mask))]
            ctx.run_command([*argv, str(signal)])
            ctx.run_command(
                ["fslmaths", str(atlas_file), "-mas", str(signal), str(used_file), "-odt", "short"]
            )
        else:
            shutil.copyfile(atlas_file, used_file)

        regions = atlases.regions(p.atlas)
        atlas_data = np.rint(np.asarray(nib.load(atlas_file).get_fdata())).astype(int)  # type: ignore[attr-defined]
        used_data = np.rint(np.asarray(nib.load(used_file).get_fdata())).astype(int)  # type: ignore[attr-defined]
        used_labels = [r.label for r in regions if (used_data == r.label).any()]

        values = np.full((image_info(bold)[0][3], len(regions)), np.nan)
        if used_labels:
            raw = work / "meants.txt"
            ctx.run_command(["fslmeants", "-i", str(bold), f"--label={used_file}", "-o", str(raw)])
            values = spread_columns(np.loadtxt(raw, ndmin=2), used_labels, regions)
        write_timeseries(ctx.output_dir / out.timeseries, values, [r.clean_name for r in regions])

        table = region_table(atlas_data, used_data, regions, p.min_coverage)
        info = {
            "atlas": p.atlas,
            "atlas_name": atlases.get_atlas(p.atlas).name,
            "space": STANDARD_SPACE,
            "input": ctx.inputs.bold,
            "volumes": int(values.shape[0]),
            "only_voxels_with_signal": p.only_voxels_with_signal,
            "signal_definition": (
                "every voxel of the region"
                if not p.only_voxels_with_signal
                else "inside the brain mask of the recording and varying over time"
                if ctx.inputs.brain_mask
                else "varying over time (no brain mask was given)"
            ),
            "brain_mask": ctx.inputs.brain_mask,
            "min_coverage": p.min_coverage,
            "regions": table,
            "n_empty": sum(r["empty"] for r in table),
            "n_low_coverage": sum(r["low_coverage"] for r in table),
            "mean_coverage": round(float(np.mean([r["coverage"] for r in table])), 4),
        }
        (ctx.output_dir / out.roi_info).write_text(json.dumps(info, indent=2) + "\n")

        mean = work / "mean"
        ctx.run_command(["fslmaths", str(bold), "-Tmean", str(mean)])
        slice_row(
            ctx, work / "mean.nii.gz", used_file, work / "roi.png",
            slices_dir(ctx, out.qc_picture), "roi",
        )  # fmt: skip
        os.replace(work / "roi.png", ctx.output_dir / out.qc_picture)
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def validate_outputs(
        self, ctx: StepContext[RoiTimeseriesInput, RoiTimeseriesParams]
    ) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        out = self.expected_outputs(ctx)
        n_regions = len(atlases.regions(ctx.params.atlas))
        with (ctx.output_dir / out.timeseries).open() as f:
            header = f.readline().rstrip("\n").split("\t")
        if len(header) != n_regions:
            return [
                Problem(
                    code="ROI_RESULT_UNEXPECTED",
                    message=f"The time series have {len(header)} columns, expected {n_regions}.",
                    probable_cause="The tool finished with an unexpected result.",
                    suggested_action="Open the raw log, then run the step again.",
                )
            ]
        info = json.loads((ctx.output_dir / out.roi_info).read_text())
        if info["n_empty"] == n_regions:
            return [
                Problem(
                    code="NO_SIGNAL_IN_ATLAS",
                    message="None of the regions contains any voxel with signal.",
                    probable_cause=(
                        "The image is empty in the area of the atlas, or it is not aligned to "
                        "standard space."
                    ),
                    suggested_action="Open the standard-space result in the viewer and check it.",
                )
            ]
        return []

    def generate_qc(
        self, ctx: StepContext[RoiTimeseriesInput, RoiTimeseriesParams]
    ) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        info = json.loads((ctx.output_dir / out.roi_info).read_text())
        n = len(info["regions"])
        items = [
            QCItem(
                name="Atlas over the mean image (red: region borders)",
                kind="image",
                path=out.qc_picture,
                slices=known_slices(ctx, slices_dir(ctx, out.qc_picture), "roi"),
            ),
            QCItem(
                name="Mean share of voxels with signal",
                kind="metric",
                value=f"{info['mean_coverage'] * 100:.1f} %",
            ),
        ]
        flagged = info["n_low_coverage"] + info["n_empty"]
        items.append(
            QCItem(
                name="Regions with low coverage or no signal",
                kind="metric",
                value=f"{flagged} of {n}",
                warning=(
                    f"{info['n_low_coverage']} region(s) have under {info['min_coverage'] * 100:g} "
                    f"% of their voxels with signal and {info['n_empty']} have none. Their means "
                    "rest on few voxels (or are missing); check the picture."
                )
                if flagged
                else None,
            )
        )
        return items
