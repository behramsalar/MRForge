"""The two MRtrix3 steps of the diffusion stage: ``dwi_denoise`` (``dwidenoise``) and
``dwi_unring`` (``mrdegibbs``). Port of ``alps.sh`` lines 264-277, with the default options of
the script (no extra flags). MRtrix3 is an optional extra: when it is missing the stage plan
skips both steps (and records why), and a step run by hand explains what to install.
"""

from __future__ import annotations

from pydantic import BaseModel

from mrforge.errors import StepError
from mrforge.mrtrix_env import MrtrixInstall, find_mrtrix
from mrforge.steps.base import Problem, Step, StepContext, StepResult
from mrforge.steps.registry import register_step


class DwiImageInput(BaseModel):
    dwi: str  # the diffusion series (4D)


class NoParams(BaseModel):
    pass


class DwiImageOutput(BaseModel):
    dwi: str


def require_mrtrix() -> MrtrixInstall:
    install = find_mrtrix()
    if install is None:
        raise StepError(
            code="MRTRIX_MISSING",
            message="MRtrix3 is not installed, so this step cannot run.",
            probable_cause="Denoising and ringing removal use the MRtrix3 programs dwidenoise and "
            "mrdegibbs, which are not part of FSL.",
            suggested_action="Install MRtrix3 (https://www.mrtrix.org), or leave these two "
            "steps out; everything else in the diffusion stage works without them.",
        )
    return install


class _MrtrixStep(Step[DwiImageInput, NoParams, DwiImageOutput]):
    InputSpec, ParamSpec, OutputSpec = DwiImageInput, NoParams, DwiImageOutput
    requires_fsl = False
    datatype = "dwi"
    desc_value: str
    program: str  # attribute of MrtrixInstall

    def expected_outputs(self, ctx: StepContext[DwiImageInput, NoParams]) -> DwiImageOutput:
        return DwiImageOutput(dwi=ctx.bids_name("dwi", desc=self.desc(ctx, self.desc_value)))

    def validate_inputs(self, ctx: StepContext[DwiImageInput, NoParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if find_mrtrix() is None:
            problems.append(
                Problem(
                    code="MRTRIX_MISSING",
                    message="MRtrix3 is not installed, so this step cannot run.",
                    probable_cause="dwidenoise and mrdegibbs are not on the path.",
                    suggested_action="Install MRtrix3, or leave out denoising and ringing removal.",
                )
            )
        return problems

    def tool_versions(self, ctx: StepContext[DwiImageInput, NoParams]) -> dict[str, str]:
        install = find_mrtrix()
        return {"mrtrix3": install.version} if install else {}

    def run(self, ctx: StepContext[DwiImageInput, NoParams]) -> StepResult:
        install = require_mrtrix()
        out = ctx.output_dir / self.expected_outputs(ctx).dwi
        ctx.run_command(
            [str(getattr(install, self.program)), str(ctx.input_path(ctx.inputs.dwi)), str(out),
             "-force"]
        )  # fmt: skip
        return StepResult()


@register_step
class DwiDenoiseStep(_MrtrixStep):
    name = "dwi_denoise"
    version = "1"
    desc_value = "denoised"
    program = "dwidenoise"


@register_step
class DwiUnringStep(_MrtrixStep):
    name = "dwi_unring"
    version = "1"
    desc_value = "unring"
    program = "mrdegibbs"
