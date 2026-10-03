"""BetStep: brain extraction with FSL ``bet`` (verified against ``bet`` usage output, FSL 6.0.7).

Command built: ``bet <input> <output_dir>/brain -f <frac> [-R] [-m]``
bet writes ``brain.nii.gz`` and, with ``-m``, ``brain_mask.nii.gz``.

This step is optional and independent. It must NOT be used to prepare the input of
``fsl_anat`` (see docs/DECISIONS.md and FslAnatStep).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mrforge.niftiutil import is_readable_nifti
from mrforge.steps.base import Problem, Step, StepContext, StepResult
from mrforge.steps.registry import register_step


class BetInput(BaseModel):
    t1: str  # workspace-relative path to a 3D head image (with skull)


class BetParams(BaseModel):
    # REVIEW(domain): defaults are FSL's own (frac 0.5, no robust centre estimation). Confirm
    # they suit your T1 protocol; smaller frac gives a larger brain outline.
    frac: float = Field(default=0.5, ge=0.0, le=1.0)  # bet -f
    robust: bool = False  # bet -R (robust brain centre estimation)
    mask: bool = True  # bet -m (also write the binary brain mask)


class BetOutput(BaseModel):
    brain: str = "brain.nii.gz"
    mask: str | None = "brain_mask.nii.gz"


@register_step
class BetStep(Step[BetInput, BetParams, BetOutput]):
    name = "bet"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = BetInput, BetParams, BetOutput
    requires_fsl = True

    def expected_outputs(self, ctx: StepContext[BetInput, BetParams]) -> BetOutput:
        return BetOutput(mask="brain_mask.nii.gz" if ctx.params.mask else None)

    def validate_inputs(self, ctx: StepContext[BetInput, BetParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        path = ctx.input_path(ctx.inputs.t1)
        if not problems and not is_readable_nifti(path):
            problems.append(
                Problem(
                    code="INPUT_NOT_NIFTI",
                    message=f"The T1 image could not be read as a NIfTI image: {ctx.inputs.t1}",
                    probable_cause="The file is damaged, incomplete or not a NIfTI (.nii/.nii.gz).",
                    suggested_action="Check the file opens in FSLeyes, or import the scan again.",
                )
            )
        return problems

    def run(self, ctx: StepContext[BetInput, BetParams]) -> StepResult:
        p = ctx.params
        argv = [
            "bet",
            str(ctx.input_path(ctx.inputs.t1)),
            str(ctx.output_dir / "brain"),
            "-f",
            f"{p.frac:g}",
        ]
        if p.robust:
            argv.append("-R")
        if p.mask:
            argv.append("-m")
        ctx.run_command(argv)
        return StepResult()
