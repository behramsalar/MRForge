"""Batch runs: the same pipeline for several subjects, a few at a time.

One batch is one operation (a detached worker, like any other). Inside it, a small pool of
threads takes subjects from a list; each thread runs the ordinary ``run_pipeline`` for one
subject with its own job queue. So nothing about a subject's processing is special: resume,
provenance and the "Waiting for you" pause work exactly as for a single subject, and a subject
that fails or waits only ends its own run, never the others'.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mrforge.engine import Action, StepOutcome, run_pipeline
from mrforge.pipeline import PipelineSpec
from mrforge.runner.local import LocalJobQueue
from mrforge.workspace import Workspace


@dataclass
class SubjectResult:
    subject: str
    status: str = "queued"  # queued | running | done | waiting | failed
    ran: bool = False  # something was actually run (not everything reused)
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None  # plain-language reason when it failed

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "status": self.status,
            "ran": self.ran,
            "steps": self.steps,
            "error": self.error,
        }


def gate_stamp(ws: Workspace, subject: str) -> float:
    """Changes whenever the researcher saves labels for this subject (saved label files are
    the only thing a waiting subject is waiting for), so a waiting subject is retried then and
    not before."""
    newest = 0.0
    for path in (ws.root / "derivatives").glob(f"*/{subject}/**/*_desc-icalabels_decision.json"):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def _summarise(result: SubjectResult, outcomes: list[StepOutcome]) -> None:
    result.steps = [
        {"id": o.step_id, "action": o.action.value, "job_id": o.job_id} for o in outcomes
    ]
    result.ran = any(o.action == Action.RAN for o in outcomes)
    failed = next((o for o in outcomes if o.action == Action.FAILED), None)
    if failed:
        result.status = "failed"
        result.error = f"The step '{failed.step_id}' did not finish: {failed.reason}"
    elif any(o.action == Action.WAITING for o in outcomes):
        result.status = "waiting"
    else:
        result.status = "done"


def run_batch(
    ws: Workspace,
    specs: list[PipelineSpec],
    max_subjects: int,
    started_by: str | None = None,
    log: Callable[[str], None] = lambda line: None,
    max_jobs: int | None = None,
    poll_seconds: float = 3.0,
) -> list[SubjectResult]:
    """Run every spec, at most ``max_subjects`` at the same time. Returns one result per spec
    (in the order given). Never raises for a subject's problem: that goes in its result."""
    results = [SubjectResult(subject=spec.subject or spec.name) for spec in specs]
    todo: list[int] = list(range(len(specs)))
    parked: dict[int, float] = {}  # subjects waiting for the researcher -> label stamp when parked
    running = 0
    lock = threading.Lock()

    def say(line: str) -> None:
        with lock:
            log(line)

    def next_job() -> int | None | str:
        """A subject to run: a new one, or a waiting one whose labels were saved meanwhile.
        None = nothing more can happen; "wait" = other subjects are still running."""
        with lock:
            if todo:
                return todo.pop(0)
            for i, stamp in list(parked.items()):
                if gate_stamp(ws, results[i].subject) != stamp:
                    del parked[i]
                    return i
            return "wait" if running else None

    def worker() -> None:
        nonlocal running
        while True:
            i = next_job()
            if i is None:
                return
            if i == "wait":
                time.sleep(poll_seconds)
                continue
            assert isinstance(i, int)
            with lock:
                running += 1
            result = results[i]
            result.status = "running"
            say(f"{result.subject}: started")
            try:
                jobs = LocalJobQueue(ws, max_concurrency=max_jobs or max_subjects)
                stamp = gate_stamp(ws, result.subject)
                outcomes = run_pipeline(ws, jobs, specs[i], started_by)
                _summarise(result, outcomes)
                if result.status == "waiting":
                    with lock:
                        parked[i] = stamp
            except Exception as exc:  # one subject's crash must not stop the others
                result.status = "failed"
                result.error = f"{type(exc).__name__}: {exc}"
            finally:
                with lock:
                    running -= 1
            say(f"{result.subject}: {result.status}")

    threads = [
        threading.Thread(target=worker, daemon=True, name=f"batch-{n}")
        for n in range(max(1, min(max_subjects, len(specs))))
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results
