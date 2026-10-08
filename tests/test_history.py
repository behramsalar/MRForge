"""Stage 8e: the record of one run (exact commands) and running a step again."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mrforge.api.app import create_app
from mrforge.engine import run_step
from mrforge.provenance import read_provenance, write_provenance
from mrforge.runner.jobs import list_jobs
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.base import CommandRecord
from mrforge.workspace import Workspace


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path))
    return TestClient(create_app(tmp_path / "workspaces"))


def make_run(client: TestClient, root: Path, **params: object) -> tuple[str, Workspace, int]:
    wsid = client.post("/api/workspaces", json={"name": "h"}).json()["id"]
    ws = Workspace.open(root / wsid)
    run_step(ws, LocalJobQueue(ws), "fake", "sub-001", params=params)
    return wsid, ws, list_jobs(ws)[-1].id


def finish(client: TestClient, wsid: str, op_id: int) -> dict:  # type: ignore[type-arg]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        op = client.get(f"/api/workspaces/{wsid}/operations/{op_id}").json()
        if op["status"] not in ("Queued", "Running"):
            return op  # type: ignore[no-any-return]
        time.sleep(0.2)
    raise AssertionError("operation did not finish")


def test_the_record_has_settings_files_and_copyable_commands(
    client: TestClient, tmp_path: Path
) -> None:
    wsid, ws, job_id = make_run(client, tmp_path / "workspaces", content="a b")
    rec = client.get(f"/api/workspaces/{wsid}/jobs/{job_id}/record").json()
    assert rec["subject"] == "sub-001" and rec["status"] == "Completed"
    assert rec["parameters"]["content"] == "a b"
    assert rec["outputs"] and len(rec["outputs"][0]["sha256"]) == 64
    assert rec["has_provenance"] is True
    # an argument with a space is quoted, so the command can be pasted into a terminal
    prov = read_provenance(ws.abspath(list_jobs(ws)[-1].run_dir or ""))
    assert prov is not None
    prov.commands = [
        CommandRecord(
            argv=["bet", "my brain.nii.gz", "out"], return_code=0, stdout_log="a", stderr_log="b"
        )
    ]
    write_provenance(ws.abspath(list_jobs(ws)[-1].run_dir or ""), prov)
    rec = client.get(f"/api/workspaces/{wsid}/jobs/{job_id}/record").json()
    assert rec["commands"][0]["command"] == "bet 'my brain.nii.gz' out"


def test_running_again_reuses_a_valid_result_unless_forced(
    client: TestClient, tmp_path: Path
) -> None:
    wsid, _, job_id = make_run(client, tmp_path / "workspaces")
    plain = client.post(f"/api/workspaces/{wsid}/jobs/{job_id}/rerun", json={})
    op = finish(client, wsid, plain.json()["operation_id"])
    assert op["status"] == "Completed" and op["result"]["action"] == "Already completed"
    forced = client.post(f"/api/workspaces/{wsid}/jobs/{job_id}/rerun", json={"force": True})
    op = finish(client, wsid, forced.json()["operation_id"])
    assert op["result"]["action"] == "Ran"
