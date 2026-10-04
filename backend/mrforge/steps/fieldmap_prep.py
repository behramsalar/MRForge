"""Fieldmap preparation for B0 distortion correction (Siemens gradient-echo field maps).

Runs ``bet`` on the first magnitude image and FSL's ``fsl_prepare_fieldmap SIEMENS`` on the
phase-difference image. The result (a fieldmap in rad/s and the brain-extracted magnitude) is
exactly what FEAT's B0 unwarping asks for. Philips B0 maps are not supported yet.
"""

from __future__ import annotations

import json
import os
import shutil

from pydantic import BaseModel, Field

from mrforge.niftiutil import is_readable_nifti
from mrforge.steps.base import Problem, Step, StepContext, StepResult
from mrforge.steps.registry import register_step
from mrforge.steps.sidecar import read_sidecar


class FieldmapPrepInput(BaseModel):
    magnitude1: str  # first-echo magnitude image (rawbids/.../fmap/..._magnitude1.nii.gz)
    phasediff: str  # phase-difference image (..._phasediff.nii.gz)


class FieldmapPrepParams(BaseModel):
    # REVIEW(domain): bet -f 0.5 is FSL's default. FSL advises a tight (conservative) brain
    # mask on the magnitude image, since voxels outside the brain give unreliable field
    # estimates; raise the fraction for a tighter mask.
    bet_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    # The echo time difference in ms. Normally read from the phase-difference sidecar
    # (EchoTime2 - EchoTime1); set it only to override a missing or wrong value.
    delta_te_ms: float | None = Field(default=None, gt=0)


class FieldmapPrepOutput(BaseModel):
    fieldmap: str  # fieldmap in rad/s
    magnitude_brain: str  # brain-extracted first magnitude image
    info: str  # JSON: units and the echo time difference that was used


def echo_time_difference_ms(sidecar: dict[str, object]) -> float | None:
    """EchoTime2 - EchoTime1 of a phase-difference image, in ms (None if not recorded)."""
    te1, te2 = sidecar.get("EchoTime1"), sidecar.get("EchoTime2")
    if isinstance(te1, int | float) and isinstance(te2, int | float):
        diff = (float(te2) - float(te1)) * 1000.0
        return diff if diff > 0 else None
    return None


@register_step
class FieldmapPrepStep(Step[FieldmapPrepInput, FieldmapPrepParams, FieldmapPrepOutput]):
    name = "fieldmap_prep"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = FieldmapPrepInput, FieldmapPrepParams, FieldmapPrepOutput
    requires_fsl = True
    datatype = "fmap"

    def expected_outputs(
        self, ctx: StepContext[FieldmapPrepInput, FieldmapPrepParams]
    ) -> FieldmapPrepOutput:
        return FieldmapPrepOutput(
            fieldmap=ctx.bids_name("fieldmap", desc=self.desc(ctx, "prepared")),
            magnitude_brain=ctx.bids_name("magnitude1", desc=self.desc(ctx, "brain")),
            info=ctx.bids_name("fieldmap", ".json", desc=self.desc(ctx, "prepared")),
        )

    def _delta_te(self, ctx: StepContext[FieldmapPrepInput, FieldmapPrepParams]) -> float | None:
        if ctx.params.delta_te_ms is not None:
            return ctx.params.delta_te_ms
        return echo_time_difference_ms(read_sidecar(ctx.workspace, ctx.inputs.phasediff))

    def validate_inputs(
        self, ctx: StepContext[FieldmapPrepInput, FieldmapPrepParams]
    ) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        for label, rel in (("magnitude", ctx.inputs.magnitude1), ("phase", ctx.inputs.phasediff)):
            if not is_readable_nifti(ctx.input_path(rel)):
                problems.append(
                    Problem(
                        code="INPUT_NOT_NIFTI",
                        message=f"The fieldmap {label} image could not be read: {rel}",
                        probable_cause="The file is damaged, incomplete or not a NIfTI image.",
                        suggested_action="Import the fieldmap series again.",
                    )
                )
        if not problems and self._delta_te(ctx) is None:
            problems.append(
                Problem(
                    code="FIELDMAP_TE_MISSING",
                    message="The echo time difference of the fieldmap is not known.",
                    probable_cause="The phase-difference image has no EchoTime1/EchoTime2 "
                    "recorded in its sidecar.",
                    suggested_action="Enter the echo time difference in milliseconds (often "
                    "2.46 on Siemens scanners; ask your scanner operator).",
                )
            )
        return problems

    def prepare(self, ctx: StepContext[FieldmapPrepInput, FieldmapPrepParams]) -> None:
        super().prepare(ctx)
        shutil.rmtree(ctx.run_dir / "work", ignore_errors=True)  # leftover of an earlier run

    def run(self, ctx: StepContext[FieldmapPrepInput, FieldmapPrepParams]) -> StepResult:
        delta_te = self._delta_te(ctx)
        assert delta_te is not None  # checked in validate_inputs
        work = ctx.run_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        mag_brain = work / "mag_brain"
        ctx.run_command(
            [
                "bet",
                str(ctx.input_path(ctx.inputs.magnitude1)),
                str(mag_brain),
                "-f",
                f"{ctx.params.bet_fraction:g}",
            ]
        )
        ctx.run_command(
            [
                "fsl_prepare_fieldmap",
                "SIEMENS",
                str(ctx.input_path(ctx.inputs.phasediff)),
                f"{mag_brain}.nii.gz",
                str(work / "fmap_rads"),
                f"{delta_te:g}",
            ]
        )
        out = self.expected_outputs(ctx)
        os.replace(work / "fmap_rads.nii.gz", ctx.output_dir / out.fieldmap)
        os.replace(work / "mag_brain.nii.gz", ctx.output_dir / out.magnitude_brain)
        info = {
            "Units": "rad/s",
            "Tool": "fsl_prepare_fieldmap SIEMENS",
            "DeltaTE_ms": delta_te,
            "Magnitude": ctx.inputs.magnitude1,
            "PhaseDifference": ctx.inputs.phasediff,
        }
        (ctx.output_dir / out.info).write_text(json.dumps(info, indent=2) + "\n")
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()
