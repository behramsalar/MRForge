"""Local JobQueue: one worker subprocess per job, up to ``max_concurrency`` at a time."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from sqlalchemy import select

from mrforge.errors import StepError
from mrforge.models import Job, JobStatus
from mrforge.resources import load_policy, why_not_now, worker_pids
from mrforge.runner.jobs import (
    get_job,
    kill_orphans,
    now,
    process_alive,
    recover_stale_jobs,
    update_job,
)
from mrforge.runner.queue import JobQueue
from mrforge.workspace import Workspace

POLL_INTERVAL_S = 0.1


_START_LOCK = threading.Lock()  # checking the limits and starting a job is one step
_STARTED: dict[int, subprocess.Popen[bytes]] = {}  # jobs started by this process


class LocalJobQueue(JobQueue):
    def __init__(self, ws: Workspace, max_concurrency: int = 2) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.ws = ws
        self.max_concurrency = max_concurrency
        self._pending: deque[int] = deque()
        self._running: dict[int, subprocess.Popen[bytes]] = {}
        recover_stale_jobs(ws)  # Running jobs with no live process become Interrupted

    # -- JobQueue -----------------------------------------------------------

    def submit(self, job_id: int) -> None:
        job = get_job(self.ws, job_id)
        if job.status != JobStatus.QUEUED.value:
            raise ValueError(f"Job {job_id} is {job.status}, not Queued")
        self._pending.append(job_id)
        self._pump()

    def cancel(self, job_id: int) -> None:
        if job_id in self._pending:
            self._pending.remove(job_id)
            update_job(
                self.ws,
                job_id,
                status=JobStatus.CANCELLED.value,
                finished=now(),
                error_code="CANCELLED",
                error_message="The step was cancelled before it started.",
                error=StepError("CANCELLED", "The step was cancelled before it started.").to_dict(),
            )
            return
        job = get_job(self.ws, job_id)
        if job.status == JobStatus.RUNNING.value and process_alive(job.pid, job.pid_start_time):
            assert job.pid is not None
            os.kill(job.pid, signal.SIGTERM)

    def cancel_all(self) -> None:
        for job_id in list(self._pending) + list(self._running):
            self.cancel(job_id)

    def adopt_queued(self) -> list[int]:
        """Take over Queued jobs this queue does not know yet (for example after the server
        restarted with jobs waiting). Returns the adopted ids, oldest first."""
        with self.ws.session() as s:
            queued = list(
                s.scalars(
                    select(Job.id).where(Job.status == JobStatus.QUEUED.value).order_by(Job.id)
                )
            )
        known = set(self._pending) | set(self._running)
        adopted = [j for j in queued if j not in known]
        self._pending.extend(adopted)
        return adopted

    def tick(self) -> None:
        """One scheduling step: mark dead workers, reap finished ones, start waiting jobs.
        A long-running server calls this regularly; ``wait`` calls it in a loop."""
        recover_stale_jobs(self.ws)
        self._pump()

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._pending or self._running:
            self._pump()
            if deadline is not None and time.monotonic() > deadline:
                return False
            time.sleep(POLL_INTERVAL_S)
        return True

    # -- internals ----------------------------------------------------------

    def _pump(self) -> None:
        self._reap()
        while self._pending and self._busy() < self.max_concurrency:
            with _START_LOCK:
                # Jobs this process started count at once, even before they show up in the
                # process list; others (another workspace, another server) come from the list.
                mine = {pid for pid, proc in _STARTED.items() if proc.poll() is None}
                for pid in [p for p in _STARTED if p not in mine]:
                    del _STARTED[pid]
                running = len(mine | worker_pids())
                if why_not_now(load_policy(), running) is not None:
                    return  # waits for free capacity; the next tick tries again
                self._start(self._pending.popleft())

    def _busy(self) -> int:
        """Workers in use: ours, plus live ones started by an earlier server process."""
        with self.ws.session() as s:
            running = list(s.scalars(select(Job).where(Job.status == JobStatus.RUNNING.value)))
        alive = {j.id for j in running if process_alive(j.pid, j.pid_start_time)}
        return len(alive | set(self._running))

    def _start(self, job_id: int) -> None:
        job = get_job(self.ws, job_id)
        assert job.run_dir is not None
        log_dir = self.ws.abspath(job.run_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "worker.log").open("ab") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "mrforge.runner.worker", str(self.ws.root), str(job_id)],
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # own process group: outlives parent, killable as a unit
            )
        self._running[job_id] = proc
        _STARTED[proc.pid] = proc

    def _reap(self) -> None:
        for job_id, proc in list(self._running.items()):
            code = proc.poll()
            if code is None:
                continue
            del self._running[job_id]
            job = get_job(self.ws, job_id)
            if job.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
                # The worker died without recording an outcome.
                killed = code < 0
                crash_msg = (
                    "This step was stopped before it finished."
                    if killed
                    else "The worker process crashed. See the worker log for details."
                )
                if job.pid:
                    kill_orphans(job.pid)
                update_job(
                    self.ws,
                    job_id,
                    status=(JobStatus.INTERRUPTED if killed else JobStatus.FAILED).value,
                    finished=now(),
                    return_code=code,
                    error_code="INTERRUPTED" if killed else "WORKER_CRASHED",
                    error_message=crash_msg,
                    error=_crash_error(killed, crash_msg, job.run_dir),
                )


def _crash_error(killed: bool, message: str, run_dir: str | None) -> dict[str, object]:
    return StepError(
        "INTERRUPTED" if killed else "WORKER_CRASHED",
        message,
        probable_cause=(
            "The program was stopped or the computer restarted."
            if killed
            else "The worker hit an unexpected problem."
        ),
        suggested_action="Resume the pipeline; finished steps are not repeated."
        if killed
        else "Open the log for details, then retry the step.",
        log_path=Path(run_dir) / "logs" / "worker.log" if run_dir else None,
    ).to_dict()
