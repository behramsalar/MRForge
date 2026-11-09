"""Stage 6b: a pipeline that waits for the researcher's decision, and carries on afterwards."""

import json
from pathlib import Path

import pytest

from mrforge.engine import Action, run_pipeline
from mrforge.errors import StepError
from mrforge.icalabels import decision_path, draft_path, write_labels
from mrforge.models import Job, JobStatus, Operation
from mrforge.operations import run_operation
from mrforge.pipeline import parse_pipeline
from mrforge.runner.jobs import list_jobs
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001/func"
SUMMARY = f"{D}/ica/sub-001_task-rest_desc-melodic_components.json"
N = 4


def make_workspace(tmp_path: Path, mixing_hash: str = "aaa") -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    ws.get_or_create_subject("sub-001")
    write_summary(ws, mixing_hash)
    return ws


def write_summary(ws: Workspace, mixing_hash: str) -> None:
    path = ws.abspath(SUMMARY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"n_components": N, "mixing_sha256": mixing_hash}))


def spec() -> object:
    return parse_pipeline(
        {
            "name": "p",
            "subject": "sub-001",
            "steps": [
                {
                    "id": "labels",
                    "step": "ica_labels",
                    "inputs": {"melodic_summary": SUMMARY, "decision": decision_path(SUMMARY)},
                },
                {"id": "after", "step": "fake", "inputs": {"sources": ["${labels.labels}"]}},
            ],
        }
    )


def run(ws: Workspace) -> dict[str, Action]:
    return {o.step_id: o.action for o in run_pipeline(ws, LocalJobQueue(ws), spec())}  # type: ignore[arg-type]


def all_labelled(**changes: str) -> dict[int, str]:
    labels = {1: "signal", 2: "noise", 3: "signal", 4: "uncertain"}
    labels.update({int(k): v for k, v in changes.items()})
    return labels


def test_the_pipeline_stops_and_waits_without_a_decision(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    assert run(ws) == {"labels": Action.WAITING, "after": Action.NOT_RUN}
    jobs = [j for j in list_jobs(ws) if j.step_name == "ica_labels"]
    assert [j.status for j in jobs] == [JobStatus.WAITING.value]
    assert jobs[0].error and "Waiting for you" in str(jobs[0].error["message"])
    assert jobs[0].pid is None  # nothing is running while it waits


def test_asking_again_does_not_pile_up_waiting_records(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    for _ in range(3):
        run(ws)
    assert len([j for j in list_jobs(ws) if j.step_name == "ica_labels"]) == 1


def test_a_draft_is_not_a_decision(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_labels(ws, SUMMARY, {1: "noise"}, "Jane", complete=False)
    assert run(ws)["labels"] == Action.WAITING


def test_a_complete_decision_lets_the_pipeline_continue_and_is_recorded(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    run(ws)
    write_labels(ws, SUMMARY, all_labelled(), "Jane Smith", complete=True)
    assert run(ws) == {"labels": Action.RAN, "after": Action.RAN}
    result = json.loads(next((ws.root / D).rglob("*_labels.json")).read_text())
    assert result["noise_components"] == [2]  # "uncertain" is kept by default
    assert result["decided_by"] == "Jane Smith" and result["counts"]["uncertain"] == 1
    assert run(ws) == {"labels": Action.REUSED, "after": Action.REUSED}  # resume: nothing redone


def test_changing_a_label_reruns_what_depends_on_it(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_labels(ws, SUMMARY, all_labelled(), "Jane", complete=True)
    run(ws)
    write_labels(ws, SUMMARY, all_labelled(**{"3": "noise"}), "Jane", complete=True)
    assert run(ws) == {"labels": Action.RAN, "after": Action.RAN}


def test_labels_made_for_another_decomposition_are_not_used(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_labels(ws, SUMMARY, all_labelled(), "Jane", complete=True)
    assert run(ws)["labels"] == Action.RAN
    write_summary(ws, "bbb")  # MELODIC was run again with other settings
    assert run(ws) == {"labels": Action.WAITING, "after": Action.NOT_RUN}
    waiting = [j for j in list_jobs(ws) if j.status == JobStatus.WAITING.value][0]
    assert waiting.error and "found again" in str(waiting.error["message"])


def test_a_final_decision_must_label_every_component(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    with pytest.raises(StepError) as err:
        write_labels(ws, SUMMARY, {1: "signal"}, None, complete=True)
    assert err.value.code == "LABELS_INCOMPLETE" and "3 component" in err.value.message
    with pytest.raises(StepError) as bad:
        write_labels(ws, SUMMARY, {1: "maybe"}, None, complete=False)
    assert bad.value.code == "INVALID_LABELS"


def test_the_operation_ends_as_waiting_not_failed_and_other_work_can_start(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    with ws.session() as s:
        op = Operation(kind="pipeline", title="t", args={"spec": spec().model_dump(mode="json")},  # type: ignore[attr-defined]
                       status=JobStatus.QUEUED.value)  # fmt: skip
        s.add(op)
        s.flush()
        op_id = op.id
    assert run_operation(ws, op_id) == JobStatus.WAITING
    with ws.session() as s:
        stored = s.get(Operation, op_id)
        assert stored is not None and stored.status == "Waiting" and stored.error is None
        assert stored.result and stored.result["waiting"] == ["labels"]
    from mrforge.operations import active_operation

    assert active_operation(ws) is None  # a waiting pipeline does not block anything else


def test_a_waiting_record_survives_reopening_the_workspace(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    run(ws)
    again = Workspace.open(ws.root)  # like restarting the program
    assert [j.status for j in list_jobs(again) if isinstance(j, Job)][-1] == "Waiting"


def test_the_dashboard_lists_what_waits_for_the_researcher(tmp_path: Path) -> None:
    from mrforge.overview import build_overview

    ws = make_workspace(tmp_path)
    run(ws)
    waiting = build_overview(ws).review
    assert len(waiting) == 1 and waiting[0].subject == "sub-001"
    assert waiting[0].what.startswith("Label the components") and waiting[0].page == "process/ica"
    write_labels(ws, SUMMARY, all_labelled(), "Jane", complete=True)
    run(ws)
    assert build_overview(ws).review == []


def test_labels_through_the_api(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from mrforge.api.app import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    ws = Workspace.open(tmp_path / "workspaces" / ws_id)
    write_summary(ws, "aaa")
    url = f"/api/workspaces/{ws_id}/subjects/sub-001/ica/task-rest/labels"
    draft = client.put(url, json={"labels": {"1": "noise"}, "complete": False})
    assert draft.status_code == 200 and draft.json()["complete"] is False
    too_few = client.put(url, json={"labels": {"1": "noise"}, "complete": True})
    assert too_few.status_code >= 400 and too_few.json()["code"] == "LABELS_INCOMPLETE"
    ok = client.put(
        url, json={"labels": {str(n): "signal" for n in range(1, N + 1)}, "complete": True}
    )
    assert ok.status_code == 200
    assert ws.abspath(decision_path(SUMMARY)).is_file()
    assert not ws.abspath(draft_path(SUMMARY)).exists()  # the draft is gone once decided
