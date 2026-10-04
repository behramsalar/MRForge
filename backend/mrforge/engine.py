"""Running steps and pipelines with resume: never redo a valid completed step."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from mrforge.models import JobStatus, PipelineRun
from mrforge.pipeline import PipelineSpec, references, resolve_references
from mrforge.resume import check_reusable
from mrforge.runner.jobs import build_context, create_job, get_job, normalise_specs
from mrforge.runner.queue import JobQueue
from mrforge.workspace import Workspace


class Action(enum.StrEnum):
    REUSED = "Already completed"
    RAN = "Ran"
    FAILED = "Failed"
    NOT_RUN = "Not run"


@dataclass(frozen=True)
class StepOutcome:
    step_id: str
    step: str
    action: Action
    reason: str
    job_id: int | None = None
    job_status: str | None = None


def run_step(
    ws: Workspace,
    queue: JobQueue,
    step_name: str,
    subject: str,
    inputs: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    session: str | None = None,
    force: bool = False,
    force_reason: str = "rerun requested",
    pipeline_run_id: int | None = None,
    label: str | None = None,
    started_by: str | None = None,
) -> StepOutcome:
    """Run one step unless a valid completed run exists. Blocks until the job finishes."""
    sid = label or step_name
    normalise_specs(step_name, inputs, params)  # plain-language error for bad settings
    if not force:
        reuse = check_reusable(ws, step_name, subject, inputs, params, session, label)
        if reuse.reusable:
            return StepOutcome(sid, step_name, Action.REUSED, reuse.reason, reuse.job_id)
        reason = f"Running because {reuse.reason}."
    else:
        reason = f"Running because {force_reason}."
    job_id = create_job(
        ws, step_name, subject, inputs, params, session, pipeline_run_id, label, started_by
    )
    queue.submit(job_id)
    queue.wait()
    job = get_job(ws, job_id)
    if job.status == JobStatus.COMPLETED.value:
        return StepOutcome(sid, step_name, Action.RAN, reason, job_id, job.status)
    return StepOutcome(
        sid, step_name, Action.FAILED, job.error_message or job.status, job_id, job.status
    )


def run_pipeline(
    ws: Workspace, queue: JobQueue, spec: PipelineSpec, started_by: str | None = None
) -> list[StepOutcome]:
    """Run the steps in order. Steps that are still valid are skipped; the first step that is
    not reusable, and everything after it that depends on it, runs. Stops at the first
    failure; running the same spec again (resume) continues from there."""
    with ws.session() as s:
        run = PipelineRun(name=spec.name, spec=spec.model_dump(mode="json"))
        s.add(run)
        s.flush()
        run_id = run.id

    outcomes: list[StepOutcome] = []
    outputs: dict[str, dict[str, str]] = {}
    dirty: set[str] = set()  # steps that ran (so their dependants must rerun)
    failed = False
    for st in spec.steps:
        if failed:
            outcomes.append(StepOutcome(st.id, st.step, Action.NOT_RUN, "an earlier step failed"))
            continue
        subject = st.subject or spec.subject
        assert subject is not None
        inputs = resolve_references(st.inputs, outputs)
        upstream_dirty = sorted({r for r, _ in references(st.inputs)} & dirty)
        outcome = run_step(
            ws,
            queue,
            st.step,
            subject,
            inputs,
            st.params,
            st.session,
            force=bool(upstream_dirty),
            force_reason=(
                f"step '{upstream_dirty[0]}', which it uses, was just run" if upstream_dirty else ""
            ),
            pipeline_run_id=run_id,
            label=st.id,
            started_by=started_by,
        )
        outcomes.append(outcome)
        if outcome.action != Action.REUSED:
            dirty.add(st.id)
        if outcome.action == Action.FAILED:
            failed = True
            continue
        # Outputs of this step, for later steps to refer to.
        step, ctx = build_context(ws, st.step, subject, st.session, inputs, st.params, st.id)
        outputs[st.id] = {
            name: ws.relpath(ctx.output_dir / value)
            for name, value in step.expected_outputs(ctx)
            if isinstance(value, str)
        }
    return outcomes


def latest_pipeline_run(ws: Workspace) -> PipelineRun | None:
    with ws.session() as s:
        return s.scalar(select(PipelineRun).order_by(PipelineRun.id.desc()))
