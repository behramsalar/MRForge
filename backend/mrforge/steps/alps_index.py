"""AlpsIndexStep: the DTI-ALPS index (diffusion along perivascular spaces) from the tensor and the
four regions of interest.

Port of the statistics part of ``alps.sh`` (G. Barisano, MIT licence; lines 711-748):

* ``fslstats <image> -k <roi> -m`` = the mean over the voxels where the ROI is not zero, of the
  tensor volumes 0 (Dxx), 3 (Dyy) and 5 (Dzz);
* left side: ALPS = mean(Dxx in projection, Dxx in association) / mean(Dyy in projection, Dzz in
  association); the right side likewise; ALPS = mean of the two sides;
* FA and MD in the four ROIs, with the means over the projection and the association ROIs.

The step writes ``alps.json`` (the record every export is built from: numbers, settings, notes)
and the two CSV files of the script (same columns, same order). Notes and flags warn only; they
never exclude a subject (principle 6).

REVIEW(domain): ``fslstats`` prints its means with 6 decimals, which leaves about three
significant digits for diffusivities (about 6e-4 mm2/s), so the script computes ALPS from rounded
numbers. This step uses the full values by default; ``round_like_script`` reproduces the script
exactly (differences are at the 0.1 % level). The ALPS formula is the published one (Taoka et al.)
as in the script; which side is "left" follows the ROI files (JHU/MNI orientation).
"""

from __future__ import annotations

import json
import shutil
from importlib import metadata
from pathlib import Path
from typing import cast

import numpy as np
from nibabel.loadsave import load as load_image
from nibabel.nifti1 import Nifti1Image
from numpy.typing import NDArray
from pydantic import BaseModel

from mrforge.errors import StepError
from mrforge.steps.alps_rois import tagged_desc
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.qcpics import known_slices, slice_row, slices_dir
from mrforge.steps.registry import register_step

CSV_HEADER_ALPS = (
    "id,scanner,x_proj_L,x_assoc_L,y_proj_L,z_assoc_L,x_proj_R,x_assoc_R,y_proj_R,z_assoc_R,"
    "alps_L,alps_R,alps"
)
CSV_HEADER_FAMD = "id,scanner,diffusion_metric,proj_L,assoc_L,proj_R,assoc_R,mean_proj,mean_assoc"
ROI_NAMES = ("proj_L", "proj_R", "assoc_L", "assoc_R")
SMALL_ROI_VOXELS = 20  # REVIEW(domain): proposal; a flag only


class AlpsIndexInput(BaseModel):
    tensor: str  # 6 volumes (Dxx Dxy Dxz Dyy Dyz Dzz), in the space of the ROIs
    fa: str
    md: str
    proj_l: str
    proj_r: str
    assoc_l: str
    assoc_r: str
    dwi_json: str | None = None  # for the scanner name in the tables


class AlpsIndexParams(BaseModel):
    round_like_script: bool = False
    # What was done before this step, as the stage reports it (denoising applied or skipped,
    # distortion correction, eddy program, registration, ...). Recorded in alps.json and exports.
    settings: dict[str, str] = {}
    # Things worth knowing about how this number came about ("no distortion correction", ...).
    notes: list[str] = []


class AlpsIndexOutput(BaseModel):
    result: str  # alps.json
    alps_csv: str
    fa_md_csv: str
    roi_picture: str


def _load(path: Path) -> Nifti1Image:
    return cast(Nifti1Image, load_image(str(path)))


def roi_mean(volume: NDArray[np.generic], roi: NDArray[np.generic]) -> float:
    """Mean over the voxels where the ROI is not zero (what ``fslstats -k roi -m`` computes)."""
    return float(np.mean(volume[roi != 0], dtype=np.float64))


def alps_from_means(x_proj: float, x_assoc: float, y_proj: float, z_assoc: float) -> float:
    return ((x_proj + x_assoc) / 2) / ((y_proj + z_assoc) / 2)


@register_step
class AlpsIndexStep(Step[AlpsIndexInput, AlpsIndexParams, AlpsIndexOutput]):
    name = "alps_index"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = AlpsIndexInput, AlpsIndexParams, AlpsIndexOutput
    requires_fsl = True  # for the picture
    datatype = "dwi"

    def desc(self, ctx: StepContext[AlpsIndexInput, AlpsIndexParams], base: str) -> str:
        return tagged_desc(self.name, ctx.label, base)

    def expected_outputs(
        self, ctx: StepContext[AlpsIndexInput, AlpsIndexParams]
    ) -> AlpsIndexOutput:
        d = self.desc(ctx, "alps")
        return AlpsIndexOutput(
            result=ctx.bids_name("alps", ".json", desc=d),
            alps_csv=ctx.bids_name("alps", ".csv", desc=d),
            fa_md_csv=ctx.bids_name("famd", ".csv", desc=d),
            roi_picture=ctx.bids_name("qc", ".png", desc=self.desc(ctx, "alpsrois")),
        )

    def tool_versions(self, ctx: StepContext[AlpsIndexInput, AlpsIndexParams]) -> dict[str, str]:
        return {"nibabel": metadata.version("nibabel"), "numpy": metadata.version("numpy")}

    def validate_inputs(self, ctx: StepContext[AlpsIndexInput, AlpsIndexParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        i = ctx.inputs
        tensor = _load(ctx.input_path(i.tensor))
        if len(tensor.shape) != 4 or tensor.shape[3] != 6:
            problems.append(
                Problem(
                    code="TENSOR_NOT_SIX_VOLUMES",
                    message="The tensor file does not have 6 volumes.",
                    probable_cause="It was not made by the tensor fit of this app.",
                    suggested_action="Run the tensor fit again.",
                )
            )
            return problems
        for label, rel in (
            ("FA map", i.fa), ("MD map", i.md), ("projection ROI, left", i.proj_l),
            ("projection ROI, right", i.proj_r), ("association ROI, left", i.assoc_l),
            ("association ROI, right", i.assoc_r),
        ):  # fmt: skip
            other = _load(ctx.input_path(rel))
            if tuple(other.shape[:3]) != tuple(tensor.shape[:3]) or not np.allclose(
                other.affine, tensor.affine, atol=1e-3
            ):
                problems.append(
                    Problem(
                        code="ROI_GRID_MISMATCH",
                        message=f"The {label} is not on the same grid as the tensor.",
                        probable_cause="The ROIs and the tensor are in different spaces (native "
                        "space vs template space, or two templates).",
                        suggested_action="Make the ROIs in the same space as the tensor "
                        "(the ROI step has a native-space option), then run this step again.",
                    )
                )
        return problems

    def run(self, ctx: StepContext[AlpsIndexInput, AlpsIndexParams]) -> StepResult:
        i, p = ctx.inputs, ctx.params
        out = self.expected_outputs(ctx)
        tensor = np.asarray(_load(ctx.input_path(i.tensor)).dataobj, dtype=np.float32)
        rois = {
            "proj_L": np.asarray(_load(ctx.input_path(i.proj_l)).dataobj),
            "proj_R": np.asarray(_load(ctx.input_path(i.proj_r)).dataobj),
            "assoc_L": np.asarray(_load(ctx.input_path(i.assoc_l)).dataobj),
            "assoc_R": np.asarray(_load(ctx.input_path(i.assoc_r)).dataobj),
        }
        voxels = {k: int(np.count_nonzero(v)) for k, v in rois.items()}
        empty = [k for k, n in voxels.items() if n == 0]
        if empty:
            raise StepError(
                code="ROI_EMPTY",
                message=f"The region(s) {', '.join(empty)} contain no voxels.",
                probable_cause="The ROI files are empty or do not overlap the image.",
                suggested_action="Check the ROI step and the registration pictures.",
            )

        def mean(volume: NDArray[np.generic], roi: str) -> float:
            value = roi_mean(volume, rois[roi])
            return round(value, 6) if p.round_like_script else value  # fslstats prints 6 decimals

        dxx, dyy, dzz = tensor[..., 0], tensor[..., 3], tensor[..., 5]
        comp = {
            "x_proj_L": mean(dxx, "proj_L"), "x_assoc_L": mean(dxx, "assoc_L"),
            "y_proj_L": mean(dyy, "proj_L"), "z_assoc_L": mean(dzz, "assoc_L"),
            "x_proj_R": mean(dxx, "proj_R"), "x_assoc_R": mean(dxx, "assoc_R"),
            "y_proj_R": mean(dyy, "proj_R"), "z_assoc_R": mean(dzz, "assoc_R"),
        }  # fmt: skip
        alps_l = alps_from_means(
            *(comp[k] for k in ("x_proj_L", "x_assoc_L", "y_proj_L", "z_assoc_L"))
        )
        alps_r = alps_from_means(
            *(comp[k] for k in ("x_proj_R", "x_assoc_R", "y_proj_R", "z_assoc_R"))
        )
        alps = (alps_r + alps_l) / 2

        maps: dict[str, dict[str, float]] = {}
        for label, rel in (("FA", i.fa), ("MD", i.md)):
            vol = np.asarray(_load(ctx.input_path(rel)).dataobj, dtype=np.float32)
            v = {k: mean(vol, k) for k in ROI_NAMES}
            maps[label] = {
                **v,
                "mean_proj": (v["proj_L"] + v["proj_R"]) / 2,
                "mean_assoc": (v["assoc_L"] + v["assoc_R"]) / 2,
            }

        scanner = ""
        if i.dwi_json:
            scanner = str(
                json.loads(ctx.input_path(i.dwi_json).read_text()).get("Manufacturer", "")
            )
        subject_id = ctx.subject + (f"_{ctx.session}" if ctx.session else "")

        checks = [
            f"the {k} region has only {n} voxels" for k, n in voxels.items() if n < SMALL_ROI_VOXELS
        ]
        record = {
            "id": subject_id,
            "scanner": scanner,
            "alps_L": alps_l,
            "alps_R": alps_r,
            "alps": alps,
            "components": comp,
            "fa": maps["FA"],
            "md": maps["MD"],
            "voxels": voxels,
            "rounded_like_script": p.round_like_script,
            "settings": p.settings,
            "notes": p.notes,
            "checks": checks,
            "versions": {"mrforge_step": f"{self.name} {self.version}", **self.tool_versions(ctx)},
        }
        (ctx.output_dir / out.result).write_text(json.dumps(record, indent=2) + "\n")

        csv_row = ",".join(
            [subject_id, scanner]
            + [repr(comp[k]) for k in comp]
            + [repr(alps_l), repr(alps_r), repr(alps)]
        )
        (ctx.output_dir / out.alps_csv).write_text(f"{CSV_HEADER_ALPS}\n{csv_row}\n")
        lines = [CSV_HEADER_FAMD]
        for label in ("FA", "MD"):
            m = maps[label]
            values = [
                m["proj_L"],
                m["assoc_L"],
                m["proj_R"],
                m["assoc_R"],
                m["mean_proj"],
                m["mean_assoc"],
            ]
            lines.append(",".join([subject_id, scanner, label] + [repr(v) for v in values]))
        (ctx.output_dir / out.fa_md_csv).write_text("\n".join(lines) + "\n")

        # the picture: the FA map with the outline of the four ROIs
        work = ctx.run_dir / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        union = work / "rois.nii.gz"
        ctx.run_command(
            ["fslmaths", str(ctx.input_path(i.proj_l)), "-add", str(ctx.input_path(i.proj_r)),
             "-add", str(ctx.input_path(i.assoc_l)), "-add", str(ctx.input_path(i.assoc_r)),
             "-bin", str(union)]
        )  # fmt: skip
        slice_row(
            ctx, ctx.input_path(i.fa), union, ctx.output_dir / out.roi_picture,
            slices_dir(ctx, out.roi_picture), "rois",
        )  # fmt: skip
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def generate_qc(self, ctx: StepContext[AlpsIndexInput, AlpsIndexParams]) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        rec = json.loads((ctx.output_dir / out.result).read_text())
        slices = known_slices(ctx, slices_dir(ctx, out.roi_picture), "rois")
        items = [
            QCItem(
                name="ALPS index (mean of both sides)", kind="metric", value=round(rec["alps"], 4)
            ),
            QCItem(name="ALPS index, left", kind="metric", value=round(rec["alps_L"], 4)),
            QCItem(name="ALPS index, right", kind="metric", value=round(rec["alps_R"], 4)),
            QCItem(
                name="The four ROIs on the FA map",
                kind="image",
                path=out.roi_picture,
                slices=slices,
            ),
        ]
        for note in rec["notes"] + rec["checks"]:
            items.append(QCItem(name="Note", kind="metric", value="see warning", warning=note))
        return items
