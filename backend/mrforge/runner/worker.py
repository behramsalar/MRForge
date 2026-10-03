"""Worker process: runs exactly one job.

Usage: python -m mrforge.runner.worker <workspace_root> <job_id>

The worker runs in its own session so it survives its parent; the queue and the
stale-job check find it again through the recorded PID and start time.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path
from types import FrameType

import psutil

from mrforge import __version__
from mrforge.errors import StepError
from mrforge.fsl_env import find_fsl
from mrforge.hashing import file_sha256
from mrforge.models import JobStatus, Subject
from mrforge.provenance import (
    FileRecord,
    Provenance,
    StepRef,
    remove_provenance,
    write_provenance,
)
from mrforge.runner.jobs import build_context, get_job, now, update_job
from mrforge.steps import builtin  # noqa: F401  (registers built-in steps)
from mrforge.steps.base import execute_step, input_relpaths
from mrforge.workspace import Workspace


class Cancelled(BaseException):
    """Raised inside the worker when it receives SIGTERM."""


def _on_sigterm(signum: int, frame: FrameType | None) -> None:
    for child in psutil.Process().children(recursive=True):
        try:
            child.kill()
        except psutil.Error:
            pass
    raise Cancelled


def run_job(ws: Workspace, job_id: int) -> JobStatus:
    job = get_job(ws, job_id)
    me = psutil.Process()
    update_job(
        ws,
        job_id,
        status=JobStatus.RUNNING.value,
        pid=me.pid,
        pid_start_time=me.create_time(),
        started=now(),
    )
    with ws.session() as sess:
        subject = sess.get(Subject, job.subject_id).label  # type: ignore[union-attr]
    step, ctx = build_context(
        ws, job.step_name, subject, job.session, job.inputs, job.params, job.label
    )
    # A record from an earlier run must never be mistaken for this run's result.
    remove_provenance(ctx.output_dir)
    inputs = [
        FileRecord(path=rel, sha256=file_sha256(ws, rel))
        for rel in input_relpaths(ctx.inputs)
        if ws.abspath(rel).is_file()
    ]
    error: StepError | None = None
    status = JobStatus.COMPLETED
    versions = {"mrforge": __version__}
    try:
        if step.requires_fsl:
            fsl = find_fsl()
            ctx.env = fsl.env
            versions["fsl"] = fsl.version
        execute_step(step, ctx)
    except Cancelled:
        status = JobStatus.CANCELLED
        error = StepError("CANCELLED", "The step was cancelled.")
    except StepError as err:
        # A tool killed by a signal means the run was interrupted, not that the data is bad.
        status = JobStatus.INTERRUPTED if err.code == "COMMAND_KILLED" else JobStatus.FAILED
        error = err
    finished = now()
    outputs: list[FileRecord] = []
    if status == JobStatus.COMPLETED:
        outputs = [
            FileRecord(path=rel, sha256=file_sha256(ws, rel)) for rel in step.output_relpaths(ctx)
        ]
    write_provenance(
        ctx.output_dir,
        Provenance(
            step=StepRef(name=step.name, version=step.version),
            job_id=job_id,
            subject=subject,
            session=job.session,
            parameters=job.params,
            parameter_hash=job.param_hash,
            inputs=inputs,
            outputs=outputs,
            commands=ctx.commands,
            tool_versions={**versions, **step.tool_versions(ctx)},
            started=get_job(ws, job_id).started,
            finished=finished,
            status=status.value,
            return_code=0 if error is None else 1,
            error_code=error.code if error else None,
            error_message=error.format() if error else None,
        ),
    )
    if error is None:
        _finish(ws, job_id, status, None, None, return_code=0)
    else:
        _finish(ws, job_id, status, error.code, error.format())
    return status


def _finish(
    ws: Workspace,
    job_id: int,
    status: JobStatus,
    code: str | None,
    message: str | None,
    return_code: int | None = 1,
) -> None:
    update_job(
        ws,
        job_id,
        status=status.value,
        finished=now(),
        return_code=return_code,
        error_code=code,
        error_message=message,
    )


def main(argv: list[str]) -> int:
    root, job_id = Path(argv[0]), int(argv[1])
    signal.signal(signal.SIGTERM, _on_sigterm)
    ws = Workspace.open(root)
    try:
        status = run_job(ws, job_id)
    except Cancelled:
        _finish(ws, job_id, JobStatus.CANCELLED, "CANCELLED", "The step was cancelled.")
        return 1
    return 0 if status == JobStatus.COMPLETED else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
