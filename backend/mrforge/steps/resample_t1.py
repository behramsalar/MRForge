"""ResampleT1Step: resample a T1 to isotropic voxels before ``fsl_anat`` (optional, off by default).

Command built (verified with ``flirt -help``, FSL 6.0.7):
``flirt -in <T1> -ref <T1> -out <run_dir>/work/resampled -applyisoxfm <mm> -interp spline``.
``-applyisoxfm`` applies the identity transform and forces isotropic voxels of the given size.
The result is ``sub-001_desc-1mm_T1w.nii.gz`` in the results folder; the raw T1 is never changed.
Whether to run the step at all (only when a voxel side is finer than the target) is decided by
the anatomical stage plan with ``needs_resampling``.
"""

from __future__ import annotations

import os
import shutil
from typing import Literal

from pydantic import BaseModel, Field

from mrforge.bids import parse_bids_name
from mrforge.niftiutil import image_info, is_readable_nifti
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.registry import register_step


def needs_resampling(zooms: tuple[float, ...], target_mm: float = 1.0) -> bool:
    """True if any spatial voxel side is finer than the target (a small tolerance keeps
    1.0 mm images that are stored as 0.99999 from being resampled)."""
    return any(z < target_mm - 1e-3 for z in zooms[:3])


class ResampleT1Input(BaseModel):
    t1: str  # workspace-relative path to a 3D T1 image


class ResampleT1Params(BaseModel):
    voxel_mm: float = Field(default=1.0, gt=0.0)
    # REVIEW(domain): spline is the highest-quality interpolation flirt offers for resampling
    # (trilinear blurs, sinc rings); spline can overshoot slightly at sharp edges. Confirm.
    interpolation: Literal["spline", "trilinear", "sinc"] = "spline"


class ResampleT1Output(BaseModel):
    result: str


@register_step
class ResampleT1Step(Step[ResampleT1Input, ResampleT1Params, ResampleT1Output]):
    name = "resample_t1"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = ResampleT1Input, ResampleT1Params, ResampleT1Output
    requires_fsl = True

    def expected_outputs(
        self, ctx: StepContext[ResampleT1Input, ResampleT1Params]
    ) -> ResampleT1Output:
        suffix = parse_bids_name(ctx.inputs.t1)[1] or "T1w"
        mm = f"{ctx.params.voxel_mm:g}".replace(".", "p")
        return ResampleT1Output(result=ctx.bids_name(suffix, desc=self.desc(ctx, f"{mm}mm")))

    def validate_inputs(self, ctx: StepContext[ResampleT1Input, ResampleT1Params]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        path = ctx.input_path(ctx.inputs.t1)
        if not is_readable_nifti(path):
            return [
                Problem(
                    code="INPUT_NOT_NIFTI",
                    message=f"The T1 image could not be read as a NIfTI image: {ctx.inputs.t1}",
                    probable_cause="The file is damaged, incomplete or not a NIfTI (.nii/.nii.gz).",
                    suggested_action="Check the file opens in FSLeyes, or import the scan again.",
                )
            ]
        shape, _ = image_info(path)
        if len(shape) != 3 and not (len(shape) == 4 and shape[3] == 1):
            return [
                Problem(
                    code="INPUT_NOT_3D",
                    message=f"The T1 image has {len(shape)} dimensions; a 3D image is needed.",
                    probable_cause="A time series or a multi-volume image was chosen as the T1.",
                    suggested_action="Choose the single-volume T1 image of this subject.",
                )
            ]
        return []

    def prepare(self, ctx: StepContext[ResampleT1Input, ResampleT1Params]) -> None:
        super().prepare(ctx)
        shutil.rmtree(ctx.run_dir / "work", ignore_errors=True)

    def run(self, ctx: StepContext[ResampleT1Input, ResampleT1Params]) -> StepResult:
        work = ctx.run_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        src = str(ctx.input_path(ctx.inputs.t1))
        ctx.run_command(
            [
                "flirt",
                "-in",
                src,
                "-ref",
                src,
                "-out",
                str(work / "resampled"),
                "-applyisoxfm",
                f"{ctx.params.voxel_mm:g}",
                "-interp",
                ctx.params.interpolation,
            ]
        )
        produced = work / "resampled.nii.gz"
        if produced.is_file():
            os.replace(produced, ctx.output_dir / self.expected_outputs(ctx).result)
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def validate_outputs(
        self, ctx: StepContext[ResampleT1Input, ResampleT1Params]
    ) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        _, zooms = image_info(ctx.output_dir / self.expected_outputs(ctx).result)
        want = ctx.params.voxel_mm
        if any(abs(z - want) > 1e-3 for z in zooms[:3]):
            sizes = " × ".join(f"{z:g}" for z in zooms[:3])
            return [
                Problem(
                    code="RESAMPLE_WRONG_VOXEL_SIZE",
                    message=f"The resampled image has voxels of {sizes} mm, not {want:g} mm.",
                    probable_cause="flirt did not resample as expected.",
                    suggested_action="Open the log of this step and check the flirt output.",
                )
            ]
        return []

    def generate_qc(self, ctx: StepContext[ResampleT1Input, ResampleT1Params]) -> list[QCItem]:
        import nibabel as nib
        import numpy as np

        def fmt(shape: tuple[int, ...], zooms: tuple[float, ...]) -> str:
            size = " × ".join(f"{z:.3g}" for z in zooms[:3])
            return f"{' × '.join(str(n) for n in shape[:3])} voxels of {size} mm"

        before = image_info(ctx.input_path(ctx.inputs.t1))
        out_path = ctx.output_dir / self.expected_outputs(ctx).result
        after = image_info(out_path)
        data = np.asanyarray(nib.load(out_path).dataobj)  # type: ignore[attr-defined]
        negatives = bool(data.min() < 0)
        return [
            QCItem(name="Original image", kind="metric", value=fmt(*before)),
            QCItem(name="Resampled image", kind="metric", value=fmt(*after)),
            QCItem(name="Interpolation", kind="metric", value=ctx.params.interpolation),
            QCItem(
                name="Lowest value",
                kind="metric",
                value=float(data.min()),
                warning=(
                    "The resampled image has values below zero (spline overshoot at sharp "
                    "edges). They are kept in the image."
                    if negatives and before_min_nonneg(ctx)
                    else None
                ),
            ),
        ]


def before_min_nonneg(ctx: StepContext[ResampleT1Input, ResampleT1Params]) -> bool:
    """True if the original image has no negative values (so negatives are new)."""
    import nibabel as nib
    import numpy as np

    data = np.asanyarray(nib.load(ctx.input_path(ctx.inputs.t1)).dataobj)  # type: ignore[attr-defined]
    return bool(data.min() >= 0)
