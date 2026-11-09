"""Independent component analysis with FSL MELODIC (single run).

Splits the preprocessed functional data into independent components so that a researcher (or
ICA-AROMA) can tell signal from noise. MELODIC's own folder (``<name>.ica``, like ``.feat``)
is kept; the key results are linked to BIDS names next to it, and one picture per component
is drawn for the review screen. Nothing is labelled here.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field

from mrforge.bids import split_extension
from mrforge.errors import StepError
from mrforge.hashing import file_sha256
from mrforge.layout import placed
from mrforge.niftiutil import image_info, is_readable_nifti
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.icapics import draw_component, draw_planes, draw_plots, peak_voxel
from mrforge.steps.registry import register_step

MIN_VOLUMES = 30  # fewer than this is too short for a meaningful decomposition


class MelodicInput(BaseModel):
    bold: str  # preprocessed 4D functional image (the FEAT result)
    brain_mask: str  # brain mask in the same space
    # Both or neither. With them the component maps are also placed on the subject's T1 (using
    # the affine FEAT found), so the review screen can show them on an anatomical background.
    t1_brain: str | None = None
    to_t1_affine: str | None = None  # example volume -> T1 (FSL matrix), from feat_preproc


class MelodicParams(BaseModel):
    # REVIEW(domain): None lets MELODIC estimate the number of components itself (Laplace
    # approximation, FSL's default). A fixed number makes runs comparable between subjects.
    dimensionality: int | None = Field(default=None, ge=2)
    # MELODIC starts from random values, so without a fixed seed every run gives a slightly
    # different set of components in a different order, and saved labels would not fit.
    # REVIEW(domain): a fixed seed makes a run reproducible; it does not make the result
    # "more right". Change it only to check that a finding does not depend on the seed.
    seed: int = Field(default=1, ge=0)


class MelodicOutput(BaseModel):
    components: str  # 4D image: one spatial z-map per component
    mixing: str  # time course of every component (FSL text matrix: volumes x components)
    spectra: str  # power spectrum of every component (FSL text matrix)
    summary: str  # JSON: number of components, TR, explained variance, picture per component


def native_folder_name(bold_relpath: str) -> str:
    """MELODIC's own folder: the image name without extension, plus '.ica'."""
    return placed(split_extension(bold_relpath.rsplit("/", 1)[-1])[0] + ".ica", "func")


def picture_name(number: int) -> str:
    return f"mrforge_report/component-{number:03d}.png"


def plots_name(number: int) -> str:
    return f"mrforge_report/plots-{number:03d}.png"


def map_name(number: int) -> str:
    return f"mrforge_report/ic-{number:03d}.nii.gz"


def planes_name(number: int) -> str:
    return f"mrforge_report/planes-{number:03d}.png"


def map_t1_name(number: int) -> str:
    return f"mrforge_report/ic-{number:03d}_T1w.nii.gz"


@register_step
class MelodicStep(Step[MelodicInput, MelodicParams, MelodicOutput]):
    name = "melodic"
    version = (
        "6"  # 6: slice summary; 5: T1-space maps (2 mm); 4: maps on the T1; 3: 3D maps; 2: pictures
    )
    InputSpec, ParamSpec, OutputSpec = MelodicInput, MelodicParams, MelodicOutput
    requires_fsl = True
    datatype = "func"

    def expected_outputs(self, ctx: StepContext[MelodicInput, MelodicParams]) -> MelodicOutput:
        n = ctx.bids_name
        return MelodicOutput(
            components=n("components", desc=self.desc(ctx, "melodic")),
            mixing=n("mixing", ".txt", desc=self.desc(ctx, "melodic")),
            spectra=n("spectra", ".txt", desc=self.desc(ctx, "melodic")),
            summary=n("components", ".json", desc=self.desc(ctx, "melodic")),
        )

    def validate_inputs(self, ctx: StepContext[MelodicInput, MelodicParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        for rel in (ctx.inputs.bold, ctx.inputs.brain_mask):
            if not is_readable_nifti(ctx.input_path(rel)):
                return [
                    Problem(
                        code="INPUT_NOT_NIFTI",
                        message=f"The image could not be read: {rel}",
                        probable_cause="The file is damaged, incomplete or not a NIfTI image.",
                        suggested_action="Run the step that makes it again.",
                    )
                ]
        shape = image_info(ctx.input_path(ctx.inputs.bold))[0]
        if len(shape) != 4 or shape[3] < MIN_VOLUMES:
            have = shape[3] if len(shape) == 4 else 1
            return [
                Problem(
                    code="BOLD_TOO_SHORT_FOR_ICA",
                    message=f"The functional run has only {have} volumes; component analysis "
                    f"needs at least {MIN_VOLUMES}.",
                    probable_cause="The run is very short, or the image is not a time series.",
                    suggested_action="Skip artifact rejection for this run, or check the scan.",
                )
            ]
        return []

    def prepare(self, ctx: StepContext[MelodicInput, MelodicParams]) -> None:
        super().prepare(ctx)
        leftover = ctx.output_dir / native_folder_name(ctx.inputs.bold)
        if leftover.is_dir():  # an interrupted run: start again from the beginning
            shutil.rmtree(leftover)

    def run(self, ctx: StepContext[MelodicInput, MelodicParams]) -> StepResult:
        native = ctx.output_dir / native_folder_name(ctx.inputs.bold)
        native.parent.mkdir(parents=True, exist_ok=True)
        tr = image_info(ctx.input_path(ctx.inputs.bold))[1][3]
        argv = [
            "melodic",
            "-i", str(ctx.input_path(ctx.inputs.bold)),
            "-o", str(native),
            "-m", str(ctx.input_path(ctx.inputs.brain_mask)),
            f"--tr={tr:g}",
            "--nobet",
            "--Oall",
            f"--seed={ctx.params.seed}",
        ]  # fmt: skip
        if bool(ctx.inputs.t1_brain) != bool(ctx.inputs.to_t1_affine):
            raise StepError(
                code="MELODIC_T1_INCOMPLETE",
                message="The T1 image and the registration must be given together.",
                probable_cause="Only one of the two was supplied.",
                suggested_action="Give both, or neither.",
            )
        if ctx.params.dimensionality is not None:
            argv.append(f"--dim={ctx.params.dimensionality}")
        record = ctx.run_command(argv, check=False)
        if record.return_code < 0:
            raise StepError(
                code="COMMAND_KILLED",
                message=f"'melodic' was stopped before it finished (signal {-record.return_code}).",
                probable_cause="The process was killed, for example by a user or the system.",
                suggested_action="Resume the pipeline to run this step again.",
            )
        # MELODIC reports some mistakes in its text output but still exits with 0, so the
        # result itself is the test.
        if record.return_code != 0 or not (native / "melodic_IC.nii.gz").is_file():
            raise StepError(
                code="MELODIC_FAILED",
                message="MELODIC did not produce any components.",
                probable_cause="The data could not be decomposed (for example an unsuitable "
                "image, or too few volumes), or MELODIC was given an option it did not accept.",
                suggested_action="Open the raw log for MELODIC's message, then fix the input "
                "and retry.",
                log_path=ctx.workspace.abspath(record.stderr_log),
            )
        self._publish(ctx, native, tr)
        return StepResult()

    def _publish(
        self, ctx: StepContext[MelodicInput, MelodicParams], native: Path, tr: float
    ) -> None:
        out = self.expected_outputs(ctx)
        for target_name, native_name in (
            (out.components, "melodic_IC.nii.gz"),
            (out.mixing, "melodic_mix"),
            (out.spectra, "melodic_FTmix"),
        ):
            source = native / native_name
            target = ctx.output_dir / target_name
            target.unlink(missing_ok=True)
            try:
                os.link(source, target)  # same data, no extra disk space
            except OSError:
                shutil.copy2(source, target)

        import nibabel as nib

        affine = nib.load(native / "melodic_IC.nii.gz").affine  # type: ignore[attr-defined]
        maps = _load(native / "melodic_IC.nii.gz")
        if maps.ndim == 3:
            maps = maps[..., None]
        total = maps.shape[3]
        mean = _load(native / "mean.nii.gz")
        mask = _load(ctx.input_path(ctx.inputs.brain_mask)) > 0
        mix = np.loadtxt(native / "melodic_mix", ndmin=2)
        spectra = np.loadtxt(native / "melodic_FTmix", ndmin=2)
        variance = _variance_explained(native / "melodic_ICstats", total)
        (native / "mrforge_report").mkdir(exist_ok=True)
        background_path = (
            ctx.input_path(ctx.inputs.t1_brain)
            if ctx.inputs.t1_brain and ctx.inputs.to_t1_affine
            else native / "mean.nii.gz"
        )
        bg_img: Any = nib.as_closest_canonical(nib.load(background_path))  # type: ignore[attr-defined,no-untyped-call]
        bg_data = np.asarray(bg_img.dataobj, dtype=np.float64)
        bg_affine = bg_img.affine
        entries = []
        for k in range(total):
            picture = picture_name(k + 1)
            draw_component(
                maps[..., k], mean, mask, mix[:, k], spectra[:, k], tr, k + 1, total,
                native / picture, variance[k],
            )  # fmt: skip
            draw_plots(
                mix[:, k], spectra[:, k], tr, k + 1, total, native / plots_name(k + 1), variance[k]
            )
            nib.save(  # type: ignore[attr-defined]
                nib.Nifti1Image(maps[..., k].astype(np.float32), affine),  # type: ignore[attr-defined,no-untyped-call]
                native / map_name(k + 1),
            )
            shown = map_name(k + 1)
            if ctx.inputs.t1_brain and ctx.inputs.to_t1_affine:
                # Affine only: FEAT's data are already unwarped, so the fieldmap warp is not
                # applied again. Trilinear interpolation of a z-map, on a 2 mm grid inside the T1's
                # space (a 1 mm map of every component would be about 8 MB each).
                ctx.run_command(
                    [
                        "flirt", "-in", str(native / map_name(k + 1)),
                        "-ref", str(ctx.input_path(ctx.inputs.t1_brain)),
                        "-applyisoxfm", "2", "-init", str(ctx.input_path(ctx.inputs.to_t1_affine)),
                        "-interp", "trilinear", "-out", str(native / map_t1_name(k + 1)),
                    ]
                )  # fmt: skip
                shown = map_t1_name(k + 1)
                grid: Any = nib.load(native / shown)  # type: ignore[attr-defined]
                shown_data = np.asarray(grid.dataobj, dtype=np.float64)
                px, py, pz = peak_voxel(shown_data, np.ones(shown_data.shape, dtype=bool))
                peak_mm = [float(v) for v in (grid.affine @ np.array([px, py, pz, 1.0]))[:3]]
            else:
                px, py, pz = peak_voxel(maps[..., k], mask)
                peak_mm = [float(v) for v in (affine @ np.array([px, py, pz, 1.0]))[:3]]
            map_img: Any = nib.as_closest_canonical(nib.load(native / shown))  # type: ignore[attr-defined,no-untyped-call]
            draw_planes(
                bg_data, bg_affine,
                np.asarray(map_img.dataobj, dtype=np.float64), map_img.affine,
                k + 1, total, native / planes_name(k + 1),
            )  # fmt: skip
            entries.append(
                {
                    "number": k + 1,
                    "picture": ctx.workspace.relpath(native / picture),
                    "plots": ctx.workspace.relpath(native / plots_name(k + 1)),
                    "planes": ctx.workspace.relpath(native / planes_name(k + 1)),
                    "map": ctx.workspace.relpath(native / shown),
                    "peak_mm": peak_mm,
                    "variance_pct": variance[k],
                }
            )
        shutil.copy2(native / "mean.nii.gz", native / "mrforge_report" / "mean.nii.gz")
        summary = {
            "n_components": total,
            "n_volumes": int(mix.shape[0]),
            "tr_s": tr,
            "melodic_folder": ctx.workspace.relpath(native),
            # Identifies this decomposition: labels saved for it mean nothing for another one.
            "mixing_sha256": file_sha256(
                ctx.workspace, ctx.workspace.relpath(ctx.output_dir / out.mixing)
            ),
            "mean": ctx.workspace.relpath(native / "mrforge_report" / "mean.nii.gz"),
            # What the maps are drawn on: the T1 brain when the maps were placed on it.
            "background": ctx.inputs.t1_brain
            if ctx.inputs.t1_brain and ctx.inputs.to_t1_affine
            else ctx.workspace.relpath(native / "mrforge_report" / "mean.nii.gz"),
            "space": "T1w" if ctx.inputs.t1_brain and ctx.inputs.to_t1_affine else "native",
            "components": entries,
        }
        (ctx.output_dir / out.summary).write_text(json.dumps(summary, indent=2) + "\n")

    def validate_outputs(self, ctx: StepContext[MelodicInput, MelodicParams]) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        summary = json.loads((ctx.output_dir / self.expected_outputs(ctx).summary).read_text())
        missing = [
            e["picture"]
            for e in summary["components"]
            if not ctx.workspace.abspath(e["picture"]).is_file()
        ]
        if summary["n_components"] < 1 or missing:
            return [
                Problem(
                    code="ICA_RESULT_INCOMPLETE",
                    message="MELODIC did not leave a complete result"
                    + (f" (missing {missing[0]})" if missing else " (no components found)."),
                    probable_cause="MELODIC stopped early or the data could not be decomposed.",
                    suggested_action="Open the raw log, then run the step again.",
                )
            ]
        return []

    def generate_qc(self, ctx: StepContext[MelodicInput, MelodicParams]) -> list[QCItem]:
        summary = json.loads((ctx.output_dir / self.expected_outputs(ctx).summary).read_text())
        return [
            QCItem(name="Components found", kind="metric", value=summary["n_components"]),
            QCItem(name="Volumes analysed", kind="metric", value=summary["n_volumes"]),
        ]


def redraw_planes(ws: Any, summary_rel: str) -> int:
    """Draw the three-plane pictures of a finished MELODIC result again from the files on disk
    (the maps and the background named in its summary), without running MELODIC again.
    Returns how many pictures were drawn."""
    import nibabel as nib

    summary = json.loads(ws.abspath(summary_rel).read_text())
    bg_img: Any = nib.as_closest_canonical(nib.load(ws.abspath(summary["background"])))  # type: ignore[attr-defined,no-untyped-call]
    bg_data = np.asarray(bg_img.dataobj, dtype=np.float64)
    entries = summary["components"]
    for entry in entries:
        map_img: Any = nib.as_closest_canonical(nib.load(ws.abspath(entry["map"])))  # type: ignore[attr-defined,no-untyped-call]
        draw_planes(
            bg_data, bg_img.affine,
            np.asarray(map_img.dataobj, dtype=np.float64), map_img.affine,
            entry["number"], len(entries), ws.abspath(entry["planes"]),
        )  # fmt: skip
    return len(entries)


def _load(path: Path) -> NDArray[np.float64]:
    import nibabel as nib

    return np.asarray(nib.load(path).dataobj, dtype=np.float64)  # type: ignore[attr-defined]


def _variance_explained(stats_file: Path, total: int) -> list[float | None]:
    """Percent of the total variance each component explains (first column of MELODIC's
    ``melodic_ICstats``), or None when the file is not there."""
    try:
        rows = np.loadtxt(stats_file, ndmin=2)
        return [float(rows[k, 0]) for k in range(total)]
    except (OSError, ValueError, IndexError):
        return [None] * total
