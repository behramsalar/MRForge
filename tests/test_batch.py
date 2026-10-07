"""Stage 7a: the same pipeline for several subjects, a few at a time."""

import os
import signal
import time
from pathlib import Path

from test_ica_labels import SUMMARY, make_workspace

from mrforge.batch import run_batch
from mrforge.icalabels import decision_path
from mrforge.models import Job
from mrforge.operations import get_operation, recover_stale_operations, start_operation
from mrforge.pipeline import PipelineSpec, parse_pipeline
from mrforge.steps import builtin  # noqa: F401
from mrforge.workspace import Workspace


def fake_spec(subject: str, **params: object) -> PipelineSpec:
    return parse_pipeline(
        {
            "name": f"full-{subject}",
            "subject": subject,
            "steps": [{"id": "work", "step": "fake", "params": params}],
        }
    )


def overlap(ws: Workspace) -> int:
    """The largest number of jobs that were running at the same moment."""
    with ws.session() as s:
        spans = [
            (j.started.timestamp(), j.finished.timestamp())
            for j in s.query(Job)
            if j.started and j.finished
        ]
    edges = sorted([(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans])
    now = best = 0
    for _, delta in edges:
        now += delta
        best = max(best, now)
    return best


def test_at_most_the_chosen_number_of_subjects_run_at_the_same_time(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    specs = [fake_spec(f"sub-{i:03d}", duration=1.0) for i in range(1, 6)]
    results = run_batch(ws, specs, max_subjects=2)
    assert [r.status for r in results] == ["done"] * 5
    assert overlap(ws) == 2  # parallel, but never more than asked


def test_one_failing_subject_does_not_stop_the_others(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    specs = [fake_spec("sub-001"), fake_spec("sub-002", fail_at="start"), fake_spec("sub-003")]
    a, b, c = run_batch(ws, specs, max_subjects=3)
    assert (a.status, b.status, c.status) == ("done", "failed", "done")
    assert b.error and "work" in b.error


def test_resume_runs_only_the_subject_that_did_not_finish(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    marker = str(tmp_path / "ws" / "failed-once.marker")
    specs = [
        fake_spec("sub-001"),
        fake_spec("sub-002", fail_once_marker=marker),
        fake_spec("sub-003"),
    ]
    first = run_batch(ws, specs, max_subjects=2)
    assert [r.status for r in first] == ["done", "failed", "done"]
    second = run_batch(ws, specs, max_subjects=2)
    assert [r.status for r in second] == ["done", "done", "done"]
    assert [r.ran for r in second] == [False, True, False]  # finished subjects are not redone


def test_a_subject_waiting_for_the_researcher_does_not_hold_up_the_others(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)  # sub-001 has a MELODIC result waiting for labels
    labels = parse_pipeline(
        {
            "name": "full-sub-001",
            "subject": "sub-001",
            "steps": [
                {
                    "id": "labels",
                    "step": "ica_labels",
                    "inputs": {"melodic_summary": SUMMARY, "decision": decision_path(SUMMARY)},
                }
            ],
        }
    )
    results = run_batch(ws, [labels, fake_spec("sub-002"), fake_spec("sub-003")], max_subjects=1)
    assert [r.status for r in results] == ["waiting", "done", "done"]


def wait_for(ws: Workspace, op_id: int, seconds: float = 60) -> str:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        op = get_operation(ws, op_id)
        if op.status not in ("Queued", "Running"):
            return op.status
        time.sleep(0.3)
    raise AssertionError("the operation did not finish in time")


def test_a_batch_operation_reports_failed_subjects_in_plain_words(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    specs = [fake_spec("sub-001"), fake_spec("sub-002", fail_at="start")]
    op_id = start_operation(
        ws,
        "batch",
        "Batch",
        {"specs": [s.model_dump(mode="json") for s in specs], "max_subjects": 2},
    )
    assert wait_for(ws, op_id) == "Failed"
    op = get_operation(ws, op_id)
    assert (
        op.error
        and op.error["code"] == "BATCH_SUBJECTS_FAILED"
        and "1 of 2" in str(op.error["message"])
    )


def test_killing_the_batch_worker_is_recorded_and_the_batch_can_be_started_again(
    tmp_path: Path,
) -> None:
    ws = Workspace.create(tmp_path / "ws")
    specs = [fake_spec(f"sub-{i:03d}", duration=4.0) for i in (1, 2)]
    payload = {"specs": [s.model_dump(mode="json") for s in specs], "max_subjects": 2}
    op_id = start_operation(ws, "batch", "Batch", payload)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not get_operation(ws, op_id).pid:
        time.sleep(0.2)
    time.sleep(1.5)  # the jobs are running now
    os.kill(get_operation(ws, op_id).pid, signal.SIGKILL)  # type: ignore[arg-type]
    time.sleep(0.5)
    recover_stale_operations(ws)
    assert get_operation(ws, op_id).status == "Interrupted"
    again = start_operation(ws, "batch", "Batch again", payload)
    assert wait_for(ws, again, 90) == "Completed"
