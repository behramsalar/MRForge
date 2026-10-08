"""Resample native-space functional data into MNI space with one interpolation.

The functional-to-T1 transform (from FEAT) and the T1-to-MNI nonlinear warp (from
``fsl_anat``) are combined with ``convertwarp`` and applied once with ``applywarp``, the same
way FEAT itself applies its registration (``applywarp --premat=<func2highres.mat>
--warp=<highres2standard_warp>``). The input can be any 4D image in the functional (FEAT)
space: the FEAT result today, the cleaned data after ICA-based cleanup later. This gives the
order "cleanup first, standard space last".

When FEAT corrected the distortion, its 4D result is already unwarped and lives in the
example-volume space, so the affine transform (not FEAT's distortion-including warp) is the
right one to use.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from mrforge.bids import parse_bids_name
from mrforge.errors import StepError
from mrforge.fsl_env import find_fsl
from mrforge.niftiutil import image_info, is_readable_nifti
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.fsl_anat import STANDARD_SPACE
from mrforge.steps.qcpics import known_slices, slice_row, slices_dir
from mrforge.steps.registry import register_step


class FuncToMniInput(BaseModel):
    bold: str  # 4D functional image in FEAT's space (preprocessed or cleaned)
    to_t1_affine: str  # example volume -> T1 (FSL matrix), from feat_preproc
    t1_to_mni_warp: str  # fsl_anat's T1 -> MNI nonlinear warp coefficients
    brain_mask: str | None = None  # brain mask in the same functional space (optional)


class FuncToMniParams(BaseModel):
    resolution_mm: Literal[1, 2] = 2  # MNI152 template resolution of the output grid
    # REVIEW(domain): spline interpolation (as FEAT uses when it unwarps 4D data); FSL's
    # default for applywarp is trilinear, which smooths the data a little more.
    interpolation: Literal["trilinear", "spline", "sinc"] = "spline"


class FuncToMniOutput(BaseModel):
    bold_mni: str
    warp: str  # the combined functional -> MNI warp, reusable for other images
    qc_picture: str
    brain_mask_mni: str | None = None


def standard_brain(env: dict[str, str] | None, resolution_mm: int) -> Path | None:
    """The MNI152 brain template of the FSL install in use (never a fixed path): the step's
    own environment, else the usual FSL lookup. ``None`` if there is no such file."""
    fsldir = (env or {}).get("FSLDIR")
    if not fsldir:
        try:
            fsldir = str(find_fsl().fsldir)
        except StepError:
            return None
    path = Path(fsldir) / "data" / "standard" / f"MNI152_T1_{resolution_mm}mm_brain.nii.gz"
    return path if path.is_file() else None


@register_step
class FuncToMniStep(Step[FuncToMniInput, FuncToMniParams, FuncToMniOutput]):
    name = "func_to_mni"
    version = "3"  # 3: single slices kept; 2: result named for the data it comes from
    InputSpec, ParamSpec, OutputSpec = FuncToMniInput, FuncToMniParams, FuncToMniOutput
    requires_fsl = True
    datatype = "func"

    @staticmethod
    def _data_desc(ctx: StepContext[FuncToMniInput, FuncToMniParams]) -> str:
        """The name says which data went in: "denoised" after noise removal, else "preproc"."""
        found = parse_bids_name(ctx.inputs.bold)[0].get("desc", "")
        return "denoised" if found.startswith("denoised") else "preproc"

    def expected_outputs(
        self, ctx: StepContext[FuncToMniInput, FuncToMniParams]
    ) -> FuncToMniOutput:
        n = ctx.bids_name
        space = {"space": STANDARD_SPACE}
        return FuncToMniOutput(
            bold_mni=n("bold", **space, desc=self.desc(ctx, self._data_desc(ctx))),
            warp=n(
                "xfm",
                **{"from": "boldref", "to": STANDARD_SPACE, "mode": "image"},
                desc=self.desc(ctx, "fnirtcoeff"),
            ),
            qc_picture=n("qc", ".png", desc=self.desc(ctx, "mni")),
            brain_mask_mni=(
                n("mask", **space, desc=self.desc(ctx, "brain")) if ctx.inputs.brain_mask else None
            ),
        )

    def validate_inputs(self, ctx: StepContext[FuncToMniInput, FuncToMniParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        i = ctx.inputs
        for rel in (i.bold, i.t1_to_mni_warp, i.brain_mask):
            if rel and not is_readable_nifti(ctx.input_path(rel)):
                problems.append(
                    Problem(
                        code="INPUT_NOT_NIFTI",
                        message=f"An image could not be read: {rel}",
                        probable_cause="The file is damaged or incomplete.",
                        suggested_action="Run the step that makes it again.",
                    )
                )
        if problems:
            return problems
        if len(image_info(ctx.input_path(i.bold))[0]) != 4:
            problems.append(
                Problem(
                    code="BOLD_NOT_4D",
                    message="The functional image is not a time series (4D image).",
                    probable_cause="A single volume or a mask was given instead of the data.",
                    suggested_action="Choose the preprocessed (or cleaned) functional run.",
                )
            )
        if standard_brain(ctx.env, ctx.params.resolution_mm) is None:
            problems.append(
                Problem(
                    code="MNI_TEMPLATE_MISSING",
                    message="The MNI152 template was not found in your FSL installation.",
                    probable_cause="FSL's standard images are missing or FSL is incomplete.",
                    suggested_action="Reinstall FSL, or run 'python scripts/check_env.py'.",
                )
            )
        return problems

    def prepare(self, ctx: StepContext[FuncToMniInput, FuncToMniParams]) -> None:
        super().prepare(ctx)
        shutil.rmtree(ctx.run_dir / "work", ignore_errors=True)

    def validate_outputs(self, ctx: StepContext[FuncToMniInput, FuncToMniParams]) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        out = self.expected_outputs(ctx)
        want = image_info(ctx.input_path(ctx.inputs.bold))[0][3]
        shape = image_info(ctx.output_dir / out.bold_mni)[0]
        template = standard_brain(ctx.env, ctx.params.resolution_mm)
        grid = image_info(template)[0] if template else shape[:3]  # no template: volumes only
        if len(shape) != 4 or shape[3] != want or shape[:3] != grid:
            return [
                Problem(
                    code="MNI_RESULT_UNEXPECTED",
                    message=f"The result has size {shape}, expected {grid} with {want} volumes.",
                    probable_cause="The tool finished with an unexpected result.",
                    suggested_action="Open the raw log, then run the step again.",
                )
            ]
        return []

    def run(self, ctx: StepContext[FuncToMniInput, FuncToMniParams]) -> StepResult:
        i, p = ctx.inputs, ctx.params
        work = ctx.run_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        out = self.expected_outputs(ctx)
        ref = standard_brain(ctx.env, p.resolution_mm)
        assert ref is not None  # checked in validate_inputs
        warp = ctx.output_dir / out.warp
        ctx.run_command(
            [
                "convertwarp",
                f"--ref={ref}",
                f"--premat={ctx.input_path(i.to_t1_affine)}",
                f"--warp1={ctx.input_path(i.t1_to_mni_warp)}",
                f"--out={warp}",
            ]
        )
        ctx.run_command(
            [
                "applywarp",
                "-i", str(ctx.input_path(i.bold)),
                "-r", str(ref),
                "-w", str(warp),
                "-o", str(ctx.output_dir / out.bold_mni),
                f"--interp={p.interpolation}",
            ]
        )  # fmt: skip
        if i.brain_mask and out.brain_mask_mni:
            ctx.run_command(
                [
                    "applywarp",
                    "-i", str(ctx.input_path(i.brain_mask)),
                    "-r", str(ref),
                    "-w", str(warp),
                    "-o", str(ctx.output_dir / out.brain_mask_mni),
                    "--interp=nn",
                ]
            )  # fmt: skip
        mean = work / "mean"
        ctx.run_command(["fslmaths", str(ctx.output_dir / out.bold_mni), "-Tmean", str(mean)])
        slice_row(
            ctx, work / "mean.nii.gz", ref, work / "mni.png", slices_dir(ctx, out.qc_picture), "mni"
        )
        os.replace(work / "mni.png", ctx.output_dir / out.qc_picture)
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def generate_qc(self, ctx: StepContext[FuncToMniInput, FuncToMniParams]) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        return [
            QCItem(
                name="Alignment to standard space (red: outline of the MNI brain)",
                kind="image",
                path=out.qc_picture,
                slices=known_slices(ctx, slices_dir(ctx, out.qc_picture), "mni"),
            )
        ]
