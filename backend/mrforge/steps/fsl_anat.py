"""FslAnatStep: structural processing with FSL ``fsl_anat`` (verified against ``fsl_anat --help``
and a real run on test data, FSL 6.0.7.23).

Command built: ``fsl_anat -i <t1> -o <output_dir>/anat [-t T1|T2|PD] [--strongbias]
[--nosubcortseg]``. fsl_anat writes ``<output_dir>/anat.anat/`` itself.

The input must be the ORIGINAL T1 with skull: fsl_anat does its own brain extraction and
skips registration to standard space for a brain-extracted input (see docs/DECISIONS.md), so
the output of the ``bet`` step is refused as input.
"""

from __future__ import annotations

import re
import shutil
from typing import Literal

from pydantic import BaseModel

from mrforge.niftiutil import is_readable_nifti
from mrforge.provenance import read_provenance
from mrforge.steps.base import Problem, Step, StepContext, StepResult
from mrforge.steps.bet import BetStep
from mrforge.steps.registry import register_step

ANAT_DIR = "anat.anat"  # fsl_anat appends ".anat" to the -o basename "anat"
BRAIN_NAME_HINT = re.compile(r"(brain|skullstrip|skull-strip|_bet\b|_masked)", re.IGNORECASE)


class FslAnatInput(BaseModel):
    t1: str  # workspace-relative path to the original T1 (with skull)


class FslAnatParams(BaseModel):
    image_type: Literal["T1", "T2", "PD"] = "T1"  # fsl_anat -t
    strong_bias: bool = False  # --strongbias (for images with very strong bias fields)
    # Optional extra, off by default (user decision): the subcortical segmentation (FIRST) is
    # slow and not needed for the functional pipeline (WM/CSF signals come from the tissue
    # segmentation). True runs it; False adds --nosubcortseg.
    subcortical_segmentation: bool = False


class FslAnatOutput(BaseModel):
    """Key results, relative to the step output directory (all inside ``anat.anat/``)."""

    biascorr: str = f"{ANAT_DIR}/T1_biascorr.nii.gz"  # bias-corrected head image
    brain: str = f"{ANAT_DIR}/T1_biascorr_brain.nii.gz"  # bias-corrected, brain-extracted
    brain_mask: str = f"{ANAT_DIR}/T1_biascorr_brain_mask.nii.gz"
    segmentation: str = f"{ANAT_DIR}/T1_fast_seg.nii.gz"  # tissue classes (CSF/GM/WM)
    csf_pve: str = f"{ANAT_DIR}/T1_fast_pve_0.nii.gz"  # partial volume estimates
    gm_pve: str = f"{ANAT_DIR}/T1_fast_pve_1.nii.gz"
    wm_pve: str = f"{ANAT_DIR}/T1_fast_pve_2.nii.gz"
    to_mni_linear: str = f"{ANAT_DIR}/T1_to_MNI_lin.nii.gz"
    to_mni_linear_mat: str = f"{ANAT_DIR}/T1_to_MNI_lin.mat"
    to_mni_nonlinear: str = f"{ANAT_DIR}/T1_to_MNI_nonlin.nii.gz"
    to_mni_warp: str = f"{ANAT_DIR}/T1_to_MNI_nonlin_coeff.nii.gz"  # T1 -> MNI (for applywarp)
    from_mni_warp: str = f"{ANAT_DIR}/MNI_to_T1_nonlin_field.nii.gz"  # MNI -> T1
    subcortical_segmentation: str | None = f"{ANAT_DIR}/T1_subcort_seg.nii.gz"


@register_step
class FslAnatStep(Step[FslAnatInput, FslAnatParams, FslAnatOutput]):
    name = "fsl_anat"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = FslAnatInput, FslAnatParams, FslAnatOutput
    requires_fsl = True

    def expected_outputs(self, ctx: StepContext[FslAnatInput, FslAnatParams]) -> FslAnatOutput:
        if ctx.params.subcortical_segmentation:
            return FslAnatOutput()
        return FslAnatOutput(subcortical_segmentation=None)

    def validate_inputs(self, ctx: StepContext[FslAnatInput, FslAnatParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        rel = ctx.inputs.t1
        path = ctx.input_path(rel)
        if not is_readable_nifti(path):
            return [
                Problem(
                    code="INPUT_NOT_NIFTI",
                    message=f"The T1 image could not be read as a NIfTI image: {rel}",
                    probable_cause="The file is damaged, incomplete or not a NIfTI (.nii/.nii.gz).",
                    suggested_action="Check the file opens in FSLeyes, or import the scan again.",
                )
            ]
        prov = read_provenance(path.parent)
        if prov is not None and prov.step.name == BetStep.name:
            return [
                Problem(
                    code="ANAT_NEEDS_ORIGINAL_T1",
                    message="This image is the result of brain extraction (the 'bet' step).",
                    probable_cause="fsl_anat does its own brain extraction and needs the whole "
                    "head. Given a brain-extracted image it would skip registration to "
                    "standard space, which later steps need.",
                    suggested_action="Use the original T1 instead, for example from rawbids/.",
                )
            ]
        if BRAIN_NAME_HINT.search(path.name):
            return [
                Problem(
                    code="ANAT_INPUT_MAY_BE_BRAIN_EXTRACTED",
                    message=f"The file name suggests a brain-extracted image: {path.name}",
                    probable_cause="fsl_anat works best on the original T1 with skull.",
                    suggested_action="Make sure this is the original T1, not a skull-stripped one.",
                    severity="warning",
                )
            ]
        return []

    def prepare(self, ctx: StepContext[FslAnatInput, FslAnatParams]) -> None:
        super().prepare(ctx)
        # An interrupted run leaves a partial .anat folder, and fsl_anat refuses to write into
        # an existing one. The run restarts from the beginning (docs/DECISIONS.md), so remove
        # our own leftover; nothing outside this step's output folder is touched.
        leftover = ctx.output_dir / ANAT_DIR
        if leftover.is_dir():
            shutil.rmtree(leftover)

    def run(self, ctx: StepContext[FslAnatInput, FslAnatParams]) -> StepResult:
        p = ctx.params
        argv = [
            "fsl_anat",
            "-i",
            str(ctx.input_path(ctx.inputs.t1)),
            "-o",
            str(ctx.output_dir / "anat"),
        ]
        if p.image_type != "T1":
            argv += ["-t", p.image_type]
        if p.strong_bias:
            argv.append("--strongbias")
        if not p.subcortical_segmentation:
            argv.append("--nosubcortseg")
        ctx.run_command(argv)
        return StepResult()
