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

from mrforge.errors import StepError
from mrforge.models import JobStatus, Subject
from mrforge.runner.jobs import get_job, now, update_job
from mrforge.steps import builtin  # noqa: F401  (registers built-in steps)
from mrforge.steps.base import StepContext, execute_step
from mrforge.steps.registry import get_step
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
    step = get_step(job.step_name)
    assert job.output_dir is not None
    with ws.session() as sess:
        subject = sess.get(Subject, job.subject_id).label  # type: ignore[union-attr]
    ctx = StepContext(
        workspace=ws,
        subject=subject,
        session=job.session,
        inputs=step.InputSpec(**job.inputs),
        params=step.ParamSpec(**job.params),
        output_dir=ws.abspath(job.output_dir),
    )
    try:
        execute_step(step, ctx)
    except Cancelled:
        _finish(ws, job_id, JobStatus.CANCELLED, "CANCELLED", "The step was cancelled.")
        return JobStatus.CANCELLED
    except StepError as err:
        # A tool killed by a signal means the run was interrupted, not that the data is bad.
        status = JobStatus.INTERRUPTED if err.code == "COMMAND_KILLED" else JobStatus.FAILED
        _finish(ws, job_id, status, err.code, err.format())
        return status
    _finish(ws, job_id, JobStatus.COMPLETED, None, None, return_code=0)
    return JobStatus.COMPLETED


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
