"""Local JobQueue: one worker subprocess per job, up to ``max_concurrency`` at a time."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections import deque

from mrforge.models import JobStatus
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
            )
            return
        job = get_job(self.ws, job_id)
        if job.status == JobStatus.RUNNING.value and process_alive(job.pid, job.pid_start_time):
            assert job.pid is not None
            os.kill(job.pid, signal.SIGTERM)

    def cancel_all(self) -> None:
        for job_id in list(self._pending) + list(self._running):
            self.cancel(job_id)

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
        while self._pending and len(self._running) < self.max_concurrency:
            self._start(self._pending.popleft())

    def _start(self, job_id: int) -> None:
        job = get_job(self.ws, job_id)
        assert job.output_dir is not None
        log_dir = self.ws.abspath(job.output_dir) / "logs"
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
                if job.pid:
                    kill_orphans(job.pid)
                update_job(
                    self.ws,
                    job_id,
                    status=(JobStatus.INTERRUPTED if killed else JobStatus.FAILED).value,
                    finished=now(),
                    return_code=code,
                    error_code="INTERRUPTED" if killed else "WORKER_CRASHED",
                    error_message=(
                        "This step was stopped before it finished."
                        if killed
                        else "The worker process crashed. See the worker log for details."
                    ),
                )
