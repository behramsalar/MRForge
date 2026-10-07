"""Propose which ICA components are motion or noise with ICA-AROMA (Pruim et al. 2015).

ICA-AROMA is an established, separate program (not FSL); this step only runs its classification
on the MELODIC result MRForge already has (``-den no``: no denoising, the removal is done by the
separate ``regfilt`` step) and records what it says. Nothing is decided here: the proposal is
either shown to the researcher to confirm, or (automatic mode) used by ``ica_labels``.

The classification uses four features of each component: its correlation with head motion,
the fraction of its signal at the edge of the brain, the fraction in CSF, and its
high-frequency content. The thresholds are AROMA's own and are not changed here.
"""

from __future__ import annotations

import json
import shutil
import sys

import numpy as np
from pydantic import BaseModel

from mrforge.aroma_env import find_aroma
from mrforge.errors import StepError
from mrforge.icalabels import read_summary
from mrforge.niftiutil import image_info
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.registry import register_step


class AromaInput(BaseModel):
    melodic_summary: str  # the MELODIC result to classify
    bold: str  # the functional image the components came from (gives the TR)
    motion: str  # head motion parameters (TSV with a header, from feat_preproc)
    to_t1_affine: str  # functional -> T1 (FSL matrix)
    t1_to_mni_warp: str  # T1 -> MNI nonlinear warp coefficients (fsl_anat)
    brain_mask: str


class AromaParams(BaseModel):
    pass  # AROMA's own rules are used as they are


class AromaOutput(BaseModel):
    classification: str  # JSON: which components AROMA proposes as motion/noise
    features: str  # TSV: the four feature values of every component


@register_step
class AromaClassifyStep(Step[AromaInput, AromaParams, AromaOutput]):
    name = "aroma_classify"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = AromaInput, AromaParams, AromaOutput
    requires_fsl = True
    datatype = "func"

    def expected_outputs(self, ctx: StepContext[AromaInput, AromaParams]) -> AromaOutput:
        n = ctx.bids_name
        return AromaOutput(
            classification=n("classification", ".json", desc=self.desc(ctx, "aroma")),
            features=n("features", ".tsv", desc=self.desc(ctx, "aroma")),
        )

    def tool_versions(self, ctx: StepContext[AromaInput, AromaParams]) -> dict[str, str]:
        found = find_aroma()
        return {"ICA-AROMA": found.version} if found else {}

    def validate_inputs(self, ctx: StepContext[AromaInput, AromaParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        if find_aroma() is None:
            return [
                Problem(
                    code="AROMA_NOT_INSTALLED",
                    message="ICA-AROMA is not installed.",
                    probable_cause="It is a separate program that MRForge does not ship with.",
                    suggested_action="Run scripts/install_aroma.sh, or label the components "
                    "yourself instead.",
                )
            ]
        return []

    def prepare(self, ctx: StepContext[AromaInput, AromaParams]) -> None:
        super().prepare(ctx)
        shutil.rmtree(ctx.run_dir / "work", ignore_errors=True)

    def run(self, ctx: StepContext[AromaInput, AromaParams]) -> StepResult:
        aroma = find_aroma()
        assert aroma is not None  # checked in validate_inputs
        summary = read_summary(ctx.workspace, ctx.inputs.melodic_summary)
        work = ctx.run_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        rows = ctx.input_path(ctx.inputs.motion).read_text().splitlines()[1:]  # drop the header
        par = work / "motion.par"
        par.write_text("\n".join(" ".join(r.split()) for r in rows if r.strip()) + "\n")
        tr = image_info(ctx.input_path(ctx.inputs.bold))[1][3]
        outdir = work / "aroma"
        record = ctx.run_command(
            [
                sys.executable, str(aroma.script),
                "-o", str(outdir),
                "-i", str(ctx.input_path(ctx.inputs.bold)),
                "-mc", str(par),
                "-a", str(ctx.input_path(ctx.inputs.to_t1_affine)),
                "-w", str(ctx.input_path(ctx.inputs.t1_to_mni_warp)),
                "-m", str(ctx.input_path(ctx.inputs.brain_mask)),
                "-md", str(ctx.workspace.abspath(summary["melodic_folder"])),
                "-tr", f"{tr:g}",
                "-den", "no",
                "-np",
            ],
            check=False,
        )  # fmt: skip
        listing = outdir / "classified_motion_ICs.txt"
        overview = outdir / "classification_overview.txt"
        if record.return_code != 0 or not listing.is_file() or not overview.is_file():
            raise StepError(
                code="AROMA_FAILED",
                message="ICA-AROMA did not produce a classification.",
                probable_cause="One of its input files may be unusable, or the program stopped "
                "(it prints its own reason and still exits normally).",
                suggested_action="Open the raw log for ICA-AROMA's message, or label the "
                "components yourself.",
                log_path=ctx.workspace.abspath(record.stderr_log),
            )
        text = listing.read_text().strip()
        motion = [int(v) for v in text.split(",") if v.strip()] if text else []
        out = self.expected_outputs(ctx)
        shutil.copy2(overview, ctx.output_dir / out.features)
        classification = {
            "motion_components": motion,
            "n_components": summary["n_components"],
            "mixing_sha256": summary["mixing_sha256"],  # the decomposition this belongs to
            "tool": "ICA-AROMA",
            "tool_version": aroma.version,
            "rules": "ICA-AROMA's own thresholds, unchanged",
        }
        (ctx.output_dir / out.classification).write_text(
            json.dumps(classification, indent=2) + "\n"
        )
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def validate_outputs(self, ctx: StepContext[AromaInput, AromaParams]) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        out = self.expected_outputs(ctx)
        data = json.loads((ctx.output_dir / out.classification).read_text())
        features = np.loadtxt(ctx.output_dir / out.features, skiprows=1, usecols=(0,), ndmin=1)
        if len(features) != data["n_components"] or any(
            not 1 <= n <= data["n_components"] for n in data["motion_components"]
        ):
            return [
                Problem(
                    code="AROMA_RESULT_MISMATCH",
                    message="ICA-AROMA's result does not match the MELODIC components.",
                    probable_cause="It was run on a different decomposition.",
                    suggested_action="Run the component analysis and ICA-AROMA again.",
                )
            ]
        return []

    def generate_qc(self, ctx: StepContext[AromaInput, AromaParams]) -> list[QCItem]:
        data = json.loads((ctx.output_dir / self.expected_outputs(ctx).classification).read_text())
        return [
            QCItem(name="Components proposed as motion or noise", kind="metric",
                   value=f"{len(data['motion_components'])} of {data['n_components']}"),
        ]  # fmt: skip
