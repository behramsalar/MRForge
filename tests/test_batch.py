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


def test_a_batch_plan_has_one_line_per_subject_and_says_why_one_cannot_run(tmp_path: Path) -> None:
    from test_processing import workspace as processing_workspace

    from mrforge.processing import BatchOptions, plan_batch

    ws = processing_workspace(tmp_path)  # sub-001 with a T1 and a run
    ws.get_or_create_subject("sub-002")  # nothing imported for it
    plan, specs = plan_batch(ws, BatchOptions(subjects=["sub-001", "sub-002"]))
    lines = {ln.subject: ln for ln in plan.subjects}
    assert lines["sub-001"].can_start and lines["sub-001"].steps > 0
    assert not lines["sub-002"].can_start and lines["sub-002"].reason
    assert plan.runnable == 1 and [s.subject for s in specs] == ["sub-001"]
    assert [s.id for s in plan.stages][0] == "anatomical"  # the stage texts for the dialog


def test_progress_of_a_batch_is_given_per_subject(tmp_path: Path) -> None:
    from mrforge.progress import operation_progress

    ws = Workspace.create(tmp_path / "ws")
    specs = [fake_spec("sub-001", duration=2.0), fake_spec("sub-002", fail_at="start")]
    op_id = start_operation(
        ws,
        "batch",
        "Batch",
        {"specs": [s.model_dump(mode="json") for s in specs], "max_subjects": 2},
    )
    saw_running = False
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        p = operation_progress(ws, get_operation(ws, op_id))
        saw_running = saw_running or any(s.state == "running" for s in p.subjects)
        if p.status not in ("Queued", "Running"):
            break
        time.sleep(0.3)
    p = operation_progress(ws, get_operation(ws, op_id))
    assert saw_running
    assert {s.subject: s.state for s in p.subjects} == {"sub-001": "done", "sub-002": "failed"}
    assert (p.done, p.total) == (1, 2)


def test_resume_after_a_batch_restarts_the_batch_not_a_single_subject(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from mrforge.api.app import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    ws = Workspace.open(tmp_path / "workspaces" / ws_id)
    specs = [fake_spec("sub-001"), fake_spec("sub-002", fail_at="start")]
    first = start_operation(
        ws,
        "batch",
        "Processing 2 subjects",
        {"specs": [s.model_dump(mode="json") for s in specs], "max_subjects": 2},
    )
    assert wait_for(ws, first) == "Failed"
    resumed = client.post(f"/api/workspaces/{ws_id}/resume").json()["operation_id"]
    op = get_operation(ws, resumed)
    assert op.kind == "batch" and op.title.startswith("Resuming Processing 2 subjects")
    wait_for(ws, resumed)


def test_jobs_left_waiting_by_a_killed_batch_are_closed_so_a_new_run_is_not_confused(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import json

    from mrforge.resources import ResourcePolicy

    cfg = tmp_path / "test-config.json"
    cfg.write_text(
        json.dumps(
            {
                "resources": ResourcePolicy(
                    preset="custom",
                    max_subjects=3,
                    threads_per_job=1,
                    cpu_cap=1,
                    memory_reserve_gb=0,
                ).model_dump()
            }
        )
    )
    monkeypatch.setenv("MRFORGE_CONFIG", str(cfg))  # one job at a time: the others stay Queued
    ws = Workspace.create(tmp_path / "ws")
    specs = [fake_spec(f"sub-{i:03d}", duration=3.0) for i in (1, 2, 3)]
    payload = {"specs": [s.model_dump(mode="json") for s in specs], "max_subjects": 3}
    op_id = start_operation(ws, "batch", "Batch", payload)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with ws.session() as s:
            statuses = sorted(j.status for j in s.query(Job))
        if statuses.count("Queued") >= 2 and "Running" in statuses:
            break
        time.sleep(0.2)
    os.kill(get_operation(ws, op_id).pid, signal.SIGKILL)  # type: ignore[arg-type]
    time.sleep(0.5)
    recover_stale_operations(ws)
    with ws.session() as s:
        left = [j.status for j in s.query(Job) if j.status == "Queued"]
    assert left == []  # nothing is left Queued for ever
    with ws.session() as s:
        assert {j.status for j in s.query(Job)} <= {"Running", "Completed", "Interrupted"}
    time.sleep(4)  # the job that was running finishes by itself
    again = start_operation(ws, "batch", "Batch again", payload)
    assert wait_for(ws, again, 120) == "Completed"


def test_a_subject_that_was_already_done_shows_as_done_when_another_one_fails(
    tmp_path: Path,
) -> None:
    from mrforge.progress import operation_progress

    ws = Workspace.create(tmp_path / "ws")
    specs = [fake_spec("sub-001"), fake_spec("sub-002", fail_at="start")]
    payload = {"specs": [s.model_dump(mode="json") for s in specs], "max_subjects": 2}
    first = start_operation(ws, "batch", "B", payload)
    assert wait_for(ws, first) == "Failed"
    second = start_operation(ws, "batch", "B again", payload)  # sub-001 is reused as a whole
    assert wait_for(ws, second) == "Failed"
    p = operation_progress(ws, get_operation(ws, second))
    states = {s.subject: s.state for s in p.subjects}
    assert states == {"sub-001": "done", "sub-002": "failed"}
    assert [s.state for s in p.subjects[0].steps] == ["reused"]
