"""FslAnatStep: structural processing with FSL ``fsl_anat`` (verified against ``fsl_anat --help``
and real runs on test data, FSL 6.0.7.23).

Command built: ``fsl_anat -i <t1> -o <output_dir>/<input name> [-t T1|T2|PD] [--strongbias]
[--nosubcortseg]``. fsl_anat writes the native folder ``<input name>.anat/`` (for example
``sub-001_T1w.anat/``) into the results folder and leaves it untouched. The key results are
then linked (copied if linking is impossible) next to it under BIDS derivatives names.

The input must be the ORIGINAL T1 with skull: fsl_anat does its own brain extraction and
skips registration to standard space for a brain-extracted input (see docs/DECISIONS.md), so
the output of the ``bet`` step is refused as input.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from mrforge.bids import parse_bids_name, split_extension
from mrforge.models import File
from mrforge.niftiutil import is_readable_nifti
from mrforge.steps.base import Problem, Step, StepContext, StepResult
from mrforge.steps.bet import BetStep
from mrforge.steps.registry import register_step

BRAIN_NAME_HINT = re.compile(r"(brain|skullstrip|skull-strip|_bet\b|_masked)", re.IGNORECASE)

# REVIEW(domain): FSL's standard template is the MRI "MNI152" used by fsl_anat; in the
# BIDS/TemplateFlow naming it corresponds to MNI152NLin6Asym. Confirm before relying on it.
STANDARD_SPACE = "MNI152NLin6Asym"

# REVIEW(domain): FAST label values for a T1 (1=CSF, 2=GM, 3=WM); written to the dseg lookup table.
SEGMENTATION_LABELS = ((1, "CSF"), (2, "GM"), (3, "WM"))

# Result field -> file inside the native .anat folder
NATIVE_FILES = {
    "biascorr": "T1_biascorr.nii.gz",
    "brain": "T1_biascorr_brain.nii.gz",
    "brain_mask": "T1_biascorr_brain_mask.nii.gz",
    "segmentation": "T1_fast_seg.nii.gz",
    "csf_pve": "T1_fast_pve_0.nii.gz",
    "gm_pve": "T1_fast_pve_1.nii.gz",
    "wm_pve": "T1_fast_pve_2.nii.gz",
    "to_mni_linear": "T1_to_MNI_lin.nii.gz",
    "to_mni_linear_mat": "T1_to_MNI_lin.mat",
    "to_mni_nonlinear": "T1_to_MNI_nonlin.nii.gz",
    "to_mni_warp": "T1_to_MNI_nonlin_coeff.nii.gz",
    "from_mni_warp": "MNI_to_T1_nonlin_field.nii.gz",
    "subcortical_segmentation": "T1_subcort_seg.nii.gz",
}


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
    """Key results, as BIDS file names in the results folder (next to the native .anat folder)."""

    biascorr: str  # bias-corrected head image
    brain: str  # bias-corrected, brain-extracted
    brain_mask: str
    segmentation: str  # tissue classes (see segmentation_labels)
    segmentation_labels: str  # lookup table for the tissue classes
    csf_pve: str  # partial volume estimates
    gm_pve: str
    wm_pve: str
    to_mni_linear: str
    to_mni_linear_mat: str
    to_mni_nonlinear: str
    to_mni_warp: str  # T1 -> standard space (FNIRT coefficients, for applywarp)
    from_mni_warp: str  # standard space -> T1 (field)
    subcortical_segmentation: str | None = None


def native_folder_name(t1_relpath: str) -> str:
    """Name of fsl_anat's native folder: the input name without extension, plus '.anat'."""
    return split_extension(t1_relpath.rsplit("/", 1)[-1])[0] + ".anat"


@register_step
class FslAnatStep(Step[FslAnatInput, FslAnatParams, FslAnatOutput]):
    name = "fsl_anat"
    version = "2"  # 2: BIDS layout, native folder named after the input
    InputSpec, ParamSpec, OutputSpec = FslAnatInput, FslAnatParams, FslAnatOutput
    requires_fsl = True

    def expected_outputs(self, ctx: StepContext[FslAnatInput, FslAnatParams]) -> FslAnatOutput:
        suffix = parse_bids_name(ctx.inputs.t1)[1] or "T1w"
        n = ctx.bids_name
        std = {"space": STANDARD_SPACE}

        def xfm(src: str, dst: str, desc: str, ext: str = ".nii.gz") -> str:
            return n("xfm", ext, **{"from": src, "to": dst, "mode": "image", "desc": desc})

        return FslAnatOutput(
            biascorr=n(suffix, desc="biascorr"),
            brain=n(suffix, desc="brain"),
            brain_mask=n("mask", desc="brain"),
            segmentation=n("dseg"),
            segmentation_labels=n("dseg", ".tsv"),
            csf_pve=n("probseg", label="CSF"),
            gm_pve=n("probseg", label="GM"),
            wm_pve=n("probseg", label="WM"),
            to_mni_linear=n(suffix, **std, desc="linear"),
            to_mni_linear_mat=xfm(suffix, STANDARD_SPACE, "linear", ".mat"),
            to_mni_nonlinear=n(suffix, **std, desc="nonlinear"),
            to_mni_warp=xfm(suffix, STANDARD_SPACE, "fnirtcoeff"),
            from_mni_warp=xfm(STANDARD_SPACE, suffix, "field"),
            subcortical_segmentation=(
                n("dseg", desc="subcortical") if ctx.params.subcortical_segmentation else None
            ),
        )

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
        with ctx.workspace.session() as s:
            made_by_bet = s.scalar(
                select(File.id).where(File.relpath == rel, File.kind == BetStep.name)
            )
        if made_by_bet is not None:
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
        # An interrupted run leaves a partial .anat folder, and fsl_anat refuses an existing
        # one. The run restarts from the beginning (docs/DECISIONS.md), so remove our own
        # leftover; nothing outside this step's own native folder is touched.
        leftover = ctx.output_dir / native_folder_name(ctx.inputs.t1)
        if leftover.is_dir():
            shutil.rmtree(leftover)

    def run(self, ctx: StepContext[FslAnatInput, FslAnatParams]) -> StepResult:
        p = ctx.params
        folder = native_folder_name(ctx.inputs.t1)
        argv = [
            "fsl_anat",
            "-i",
            str(ctx.input_path(ctx.inputs.t1)),
            "-o",
            str(ctx.output_dir / folder.removesuffix(".anat")),
        ]
        if p.image_type != "T1":
            argv += ["-t", p.image_type]
        if p.strong_bias:
            argv.append("--strongbias")
        if not p.subcortical_segmentation:
            argv.append("--nosubcortseg")
        ctx.run_command(argv)
        self._publish_bids_results(ctx, ctx.output_dir / folder)
        return StepResult()

    def _publish_bids_results(
        self, ctx: StepContext[FslAnatInput, FslAnatParams], native: os.PathLike[str]
    ) -> None:
        """Link (or copy) the key native files to their BIDS names; write the label table."""
        out = self.expected_outputs(ctx)
        for field_name, native_name in NATIVE_FILES.items():
            target_name = getattr(out, field_name)
            if target_name is None:
                continue
            source = os.path.join(native, native_name)
            if not os.path.isfile(source):
                continue  # validate_outputs reports it as a missing result
            target = ctx.output_dir / target_name
            target.unlink(missing_ok=True)
            try:
                os.link(source, target)  # same data, no extra disk space
            except OSError:
                shutil.copy2(source, target)
        rows = ["index\tname"] + [f"{i}\t{name}" for i, name in SEGMENTATION_LABELS]
        (ctx.output_dir / out.segmentation_labels).write_text("\n".join(rows) + "\n")
