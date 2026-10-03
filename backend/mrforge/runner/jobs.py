"""Creating jobs, updating them, and recovering jobs whose process is gone."""

from __future__ import annotations

import hashlib
import json
import os
import signal
from datetime import UTC, datetime
from typing import Any

import psutil
from pydantic import ValidationError
from sqlalchemy import select

from mrforge.errors import StepError
from mrforge.models import Job, JobStatus
from mrforge.steps.base import Step, StepContext
from mrforge.steps.registry import get_step
from mrforge.workspace import Workspace

START_TIME_TOLERANCE_S = 1.0


def param_hash(params: dict[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def job_output_dir(ws: Workspace, subject: str, session: str | None, step_name: str) -> str:
    """Workspace-relative output directory: derivatives/<app>/<sub>/[<ses>/]<step>/"""
    parts = [subject] + ([session] if session else []) + [step_name]
    return ws.relpath(ws.derivatives_dir.joinpath(*parts))


def build_context(
    ws: Workspace,
    step_name: str,
    subject: str,
    session: str | None,
    inputs: dict[str, Any],
    params: dict[str, Any],
    label: str | None = None,
) -> tuple[Step[Any, Any, Any], StepContext[Any, Any]]:
    """The step instance and the context it would run in (used by the worker and resume)."""
    step, inputs, params = normalise_specs(step_name, inputs, params)
    ctx = StepContext(
        workspace=ws,
        subject=subject,
        session=session,
        inputs=step.InputSpec(**inputs),
        params=step.ParamSpec(**params),
        output_dir=ws.root / job_output_dir(ws, subject, session, label or step_name),
    )
    return step, ctx


def normalise_specs(
    step_name: str, inputs: dict[str, Any] | None, params: dict[str, Any] | None
) -> tuple[Step[Any, Any, Any], dict[str, Any], dict[str, Any]]:
    """Validate inputs/params against the step's specs; return them with defaults filled in."""
    step = get_step(step_name)
    try:
        inputs_model = step.InputSpec(**(inputs or {}))
        params_model = step.ParamSpec(**(params or {}))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise StepError(
            code="PARAMS_INVALID",
            message=f"The settings for '{step_name}' are not valid: {problems}",
            probable_cause="A value is missing, misspelled or outside the allowed range.",
            suggested_action="Correct the value and run again.",
        ) from exc
    return step, inputs_model.model_dump(mode="json"), params_model.model_dump(mode="json")


def create_job(
    ws: Workspace,
    step_name: str,
    subject: str,
    inputs: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    session: str | None = None,
    pipeline_run_id: int | None = None,
    label: str | None = None,
) -> int:
    """Validate inputs/params against the step's specs and queue a job. Returns the job id."""
    step, inputs_dict, params_dict = normalise_specs(step_name, inputs, params)
    subject_id = ws.get_or_create_subject(subject)
    with ws.session() as s:
        job = Job(
            step_name=step_name,
            step_version=step.version,
            label=label,
            subject_id=subject_id,
            session=session,
            inputs=inputs_dict,
            params=params_dict,
            param_hash=param_hash(params_dict),
            status=JobStatus.QUEUED.value,
            pipeline_run_id=pipeline_run_id,
            output_dir=job_output_dir(ws, subject, session, label or step_name),
        )
        s.add(job)
        s.flush()
        return job.id


def get_job(ws: Workspace, job_id: int) -> Job:
    with ws.session() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise StepError(
                code="UNKNOWN_JOB",
                message=f"There is no job number {job_id}.",
                suggested_action="Run 'mrforge status' to see the existing jobs.",
            )
        return job


def list_jobs(ws: Workspace) -> list[Job]:
    with ws.session() as s:
        return list(s.scalars(select(Job).order_by(Job.id)))


def update_job(ws: Workspace, job_id: int, **fields: Any) -> None:
    with ws.session() as s:
        job = s.get(Job, job_id)
        assert job is not None
        for key, value in fields.items():
            setattr(job, key, value)


def now() -> datetime:
    return datetime.now(UTC)


# -- liveness ---------------------------------------------------------------


def process_alive(pid: int | None, start_time: float | None) -> bool:
    """True only if ``pid`` is running and started when we recorded (PID reuse safe)."""
    if pid is None or start_time is None:
        return False
    try:
        proc = psutil.Process(pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            return False
        return abs(proc.create_time() - start_time) < START_TIME_TOLERANCE_S
    except psutil.NoSuchProcess:
        return False


def kill_orphans(worker_pid: int) -> None:
    """Kill leftover tool processes of a dead worker (they share its process group)."""
    for proc in psutil.process_iter():
        try:
            if proc.pid != worker_pid and os.getpgid(proc.pid) == worker_pid:
                proc.send_signal(signal.SIGKILL)
        except (psutil.Error, ProcessLookupError, PermissionError):
            continue


def recover_stale_jobs(ws: Workspace) -> list[int]:
    """Mark Running jobs whose worker is gone as Interrupted. Returns their ids."""
    recovered: list[int] = []
    for job in list_jobs(ws):
        if job.status != JobStatus.RUNNING.value:
            continue
        if process_alive(job.pid, job.pid_start_time):
            continue
        if job.pid:
            kill_orphans(job.pid)
        update_job(
            ws,
            job.id,
            status=JobStatus.INTERRUPTED.value,
            finished=now(),
            error_code="INTERRUPTED",
            error_message=(
                "This step was stopped before it finished, for example because the "
                "program was killed or the computer restarted."
            ),
        )
        recovered.append(job.id)
    return recovered
