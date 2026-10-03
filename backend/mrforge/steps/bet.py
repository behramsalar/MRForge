"""BetStep: brain extraction with FSL ``bet`` (verified against ``bet`` usage output, FSL 6.0.7).

Command built: ``bet <input> <run_dir>/work/brain -f <frac> [-R] [-m]``. bet's own output
names are then moved to BIDS names in the results folder:
``sub-001_desc-bet_T1w.nii.gz`` and ``sub-001_desc-bet_mask.nii.gz`` (the run label is
added to ``desc`` when a pipeline gives the step another id).

This step is optional and independent. It must NOT be used to prepare the input of
``fsl_anat`` (see docs/DECISIONS.md and FslAnatStep).
"""

from __future__ import annotations

import os
import shutil

from pydantic import BaseModel, Field

from mrforge.bids import parse_bids_name
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
    brain: str
    mask: str | None = None


@register_step
class BetStep(Step[BetInput, BetParams, BetOutput]):
    name = "bet"
    version = "2"  # 2: BIDS-named outputs in the results folder
    InputSpec, ParamSpec, OutputSpec = BetInput, BetParams, BetOutput
    requires_fsl = True

    def expected_outputs(self, ctx: StepContext[BetInput, BetParams]) -> BetOutput:
        suffix = parse_bids_name(ctx.inputs.t1)[1] or "T1w"
        return BetOutput(
            brain=ctx.bids_name(suffix, desc=self.desc(ctx, "bet")),
            mask=ctx.bids_name("mask", desc=self.desc(ctx, "bet")) if ctx.params.mask else None,
        )

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

    def prepare(self, ctx: StepContext[BetInput, BetParams]) -> None:
        super().prepare(ctx)
        shutil.rmtree(ctx.run_dir / "work", ignore_errors=True)  # leftover of an earlier run

    def run(self, ctx: StepContext[BetInput, BetParams]) -> StepResult:
        p = ctx.params
        work = ctx.run_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        argv = [
            "bet",
            str(ctx.input_path(ctx.inputs.t1)),
            str(work / "brain"),
            "-f",
            f"{p.frac:g}",
        ]
        if p.robust:
            argv.append("-R")
        if p.mask:
            argv.append("-m")
        ctx.run_command(argv)
        out = self.expected_outputs(ctx)
        moves = {"brain.nii.gz": out.brain}
        if out.mask:
            moves["brain_mask.nii.gz"] = out.mask
        for native, target in moves.items():
            if (work / native).is_file():
                os.replace(work / native, ctx.output_dir / target)
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()
