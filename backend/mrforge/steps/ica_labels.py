"""The researcher's decision about ICA components, as a pipeline step.

This step does no computing. It is the point where a pipeline waits for the researcher: while
no valid decision exists (or the one that exists belongs to another MELODIC run) the step
reports "Waiting for you" and the pipeline stops there without using the computer. Once the
decision file exists (written when the researcher saves their labels), the step records it as
its result, so later steps depend on exactly those labels (they run again if the labels change).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from mrforge.errors import StepError
from mrforge.icalabels import problem_with, read_labels, read_summary
from mrforge.steps.base import Problem, Step, StepContext, StepResult
from mrforge.steps.registry import register_step


class IcaLabelsInput(BaseModel):
    melodic_summary: str  # the MELODIC result (names the decomposition the labels belong to)
    decision: str | None = None  # manual mode: where the decision file is (may not exist yet)
    aroma: str | None = None  # automatic mode: ICA-AROMA's classification


class IcaLabelsParams(BaseModel):
    # REVIEW(domain): what to do with components the researcher marked "uncertain". Keeping
    # them (as signal) removes less; removing them (as noise) removes more.
    uncertain_as: Literal["signal", "noise"] = "signal"
    # "manual": the researcher decides (the pipeline waits). "aroma": ICA-AROMA's classification
    # is used as it is, without waiting (the researcher chose this when starting the pipeline).
    mode: Literal["manual", "aroma"] = "manual"


class IcaLabelsOutput(BaseModel):
    labels: str  # JSON: which components are noise and who decided


@register_step
class IcaLabelsStep(Step[IcaLabelsInput, IcaLabelsParams, IcaLabelsOutput]):
    name = "ica_labels"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = IcaLabelsInput, IcaLabelsParams, IcaLabelsOutput
    datatype = "func"

    def expected_outputs(
        self, ctx: StepContext[IcaLabelsInput, IcaLabelsParams]
    ) -> IcaLabelsOutput:
        return IcaLabelsOutput(labels=ctx.bids_name("labels", ".json", desc=self.desc(ctx, "ica")))

    def ready(self, ctx: StepContext[IcaLabelsInput, IcaLabelsParams]) -> Problem | None:
        if ctx.params.mode == "aroma":
            return (
                None
                if ctx.inputs.aroma
                else Problem(
                    code="ICA_LABELS_SETUP",
                    message="Automatic labelling needs ICA-AROMA's classification.",
                    suggested_action="Include the ICA-AROMA step before this one.",
                )
            )
        if not ctx.inputs.decision:
            return Problem(
                code="ICA_LABELS_SETUP",
                message="No decision file is given for manual labelling.",
                suggested_action="Start the pipeline again from the Pipelines page.",
            )
        saved = read_labels(ctx.workspace, ctx.inputs.decision)
        why = problem_with(ctx.workspace, ctx.inputs.melodic_summary, saved)
        if why is None:
            return None
        return Problem(
            code="ICA_LABELS_NEEDED",
            message=f"Waiting for you: {why[0].lower()}{why[1:]}",
            probable_cause="Which components are noise is a decision only you can make.",
            suggested_action="Open Process, then Artifact rejection, label the components and "
            "press Save and continue.",
        )

    def run(self, ctx: StepContext[IcaLabelsInput, IcaLabelsParams]) -> StepResult:
        saved: dict[str, Any] | None
        if ctx.params.mode == "aroma":
            saved = self._from_aroma(ctx)
        else:
            assert ctx.inputs.decision is not None
            saved = read_labels(ctx.workspace, ctx.inputs.decision)
        assert saved is not None  # ready() checked it
        labels: dict[str, str] = saved["labels"]
        noise = sorted(
            int(k)
            for k, v in labels.items()
            if v == "noise" or (v == "uncertain" and ctx.params.uncertain_as == "noise")
        )
        result = {
            "noise_components": noise,
            "n_components": saved["n_components"],
            "counts": {
                name: sum(1 for v in labels.values() if v == name)
                for name in ("signal", "noise", "uncertain")
            },
            "uncertain_treated_as": ctx.params.uncertain_as,
            "decided_by": saved.get("who"),
            "decided_at": saved.get("when"),
            "source": saved.get("source"),
            "mode": ctx.params.mode,
            "mixing_sha256": saved["mixing_sha256"],
        }
        out = self.expected_outputs(ctx)
        (ctx.output_dir / out.labels).write_text(json.dumps(result, indent=2) + "\n")
        return StepResult()

    def _from_aroma(self, ctx: StepContext[IcaLabelsInput, IcaLabelsParams]) -> dict[str, Any]:
        """ICA-AROMA's motion components as noise, the rest as signal, as a decision record."""
        assert ctx.inputs.aroma is not None
        data = json.loads(ctx.input_path(ctx.inputs.aroma).read_text())
        summary = read_summary(ctx.workspace, ctx.inputs.melodic_summary)
        if data.get("mixing_sha256") != summary.get("mixing_sha256"):
            raise StepError(
                code="AROMA_RESULT_MISMATCH",
                message="ICA-AROMA classified a different set of components.",
                probable_cause="The component analysis was run again after ICA-AROMA.",
                suggested_action="Run ICA-AROMA again.",
            )
        noise = {int(n) for n in data["motion_components"]}
        n = int(summary["n_components"])
        return {
            "labels": {str(k): ("noise" if k in noise else "signal") for k in range(1, n + 1)},
            "n_components": n,
            "mixing_sha256": summary["mixing_sha256"],
            "who": f"ICA-AROMA {data.get('tool_version', '')} (automatic)".replace("  ", " "),
            "when": datetime.now(UTC).isoformat(),
            "source": "aroma",
        }
