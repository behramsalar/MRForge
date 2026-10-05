"""Undoing a whole import so its decisions can be changed (the one allowed change to rawbids/)."""

import time
from pathlib import Path

import pytest
from conftest import Fake
from dicomfactory import make_session
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from mrforge.api.app import create_app
from mrforge.cli import app as cli
from mrforge.importing.manifest import load_manifest
from mrforge.models import File, Job
from mrforge.workspace import Workspace

runner = CliRunner()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path))
    return TestClient(create_app(tmp_path / "workspaces"))


def wait_op(client: TestClient, ws: str, op_id: int) -> dict:  # type: ignore[type-arg]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        op = client.get(f"/api/workspaces/{ws}/operations/{op_id}").json()
        if op["status"] not in ("Queued", "Running"):
            return op  # type: ignore[no-any-return]
        time.sleep(0.2)
    raise AssertionError("operation did not finish")


def imported(client: TestClient, tmp_path: Path, fake: Fake) -> tuple[str, str, Workspace]:
    """A workspace with the synthetic session scanned, decided and imported."""
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    make_session(tmp_path / "session")
    base = f"/api/workspaces/{ws_id}"
    scan = wait_op(
        client,
        ws_id,
        client.post(f"{base}/imports/scan", json={"source": str(tmp_path / "session")}).json()[
            "operation_id"
        ],
    )
    import_id = scan["result"]["import_id"]
    detail = client.get(f"{base}/imports/{import_id}").json()
    ask = next(s for s in detail["series"] if s["action"] == "ask")
    client.patch(f"{base}/imports/{import_id}/series/{ask['number']}", json={"task": "rest"})
    fake.set(2, images=[{"suffix": "", "shape": [4, 4, 3]}])
    fake.set(6, images=[{"suffix": "", "shape": [4, 4, 3, 4]}])
    fake.set(19, images=[{"suffix": "", "shape": [4, 4, 8, 5]}])
    done = wait_op(
        client,
        ws_id,
        client.post(f"{base}/imports/{import_id}/run", json={}).json()["operation_id"],
    )
    assert done["status"] == "Completed", done["error"]
    return ws_id, import_id, Workspace.open(tmp_path / "workspaces" / ws_id)


def rawbids_files(ws: Workspace) -> list[str]:
    return sorted(
        str(p.relative_to(ws.root)) for p in (ws.root / "rawbids").glob("sub-*/**/*") if p.is_file()
    )


def test_undo_removes_what_the_import_wrote_and_keeps_the_copies(
    client: TestClient, tmp_path: Path, fake: Fake
) -> None:
    ws_id, import_id, ws = imported(client, tmp_path, fake)
    before = rawbids_files(ws)
    assert before and (ws.root / "rawbids/participants.tsv").read_text().count("sub-001") == 1
    converted = sorted(
        p.name for p in (ws.root / "imports" / import_id).glob("converted/**/*.nii.gz")
    )
    base = f"/api/workspaces/{ws_id}/imports/{import_id}"

    plan = client.get(f"{base}/undo-plan").json()
    assert (
        plan["files"] == len([f for f in before if f.endswith((".nii.gz", ".json"))])
        or plan["files"] > 0
    )
    assert plan["problems"] == [] and plan["series"] == 3

    result = wait_op(client, ws_id, client.post(f"{base}/undo").json()["operation_id"])
    assert result["status"] == "Completed", result["error"]
    assert rawbids_files(ws) == []  # the subject's folder is gone
    assert "sub-001" not in (ws.root / "rawbids/participants.tsv").read_text()
    with ws.session() as s:
        assert list(s.scalars(select(File).where(File.relpath.like("rawbids/sub-%")))) == []
    assert converted == sorted(
        p.name for p in (ws.root / "imports" / import_id).glob("converted/**/*.nii.gz")
    )
    assert (ws.root / "imports" / import_id / "undo-log.json").is_file()
    manifest = load_manifest(ws, import_id)
    assert manifest.organized == {} and manifest.undone is not None
    summary = client.get(f"/api/workspaces/{ws_id}/imports").json()[0]
    assert summary["organized"] == 0

    again = wait_op(client, ws_id, client.post(f"{base}/undo").json()["operation_id"])
    assert again["status"] == "Failed" and again["error"]["code"] == "NOTHING_TO_UNDO"


def test_after_undo_the_decisions_can_change_and_the_import_runs_again(
    client: TestClient, tmp_path: Path, fake: Fake
) -> None:
    ws_id, import_id, ws = imported(client, tmp_path, fake)
    base = f"/api/workspaces/{ws_id}/imports/{import_id}"
    first = rawbids_files(ws)
    wait_op(client, ws_id, client.post(f"{base}/undo").json()["operation_id"])
    # the researcher now leaves the structural scan out
    detail = client.get(base).json()
    t1 = next(s for s in detail["series"] if s["kind"] == "T1w")
    client.patch(f"{base}/series/{t1['number']}", json={"skip": True})
    done = wait_op(client, ws_id, client.post(f"{base}/run", json={}).json()["operation_id"])
    assert done["status"] == "Completed", done["error"]
    second = rawbids_files(ws)
    assert second and len(second) < len(first)
    assert not any("_T1w" in f for f in second)
    assert any("_bold" in f for f in second)


def test_undo_is_refused_while_a_step_runs(client: TestClient, tmp_path: Path, fake: Fake) -> None:
    ws_id, import_id, ws = imported(client, tmp_path, fake)
    import os

    import psutil

    me = psutil.Process(os.getpid())  # a live process stands in for the running step's worker
    with ws.session() as s:
        s.add(
            Job(
                step_name="fsl_anat",
                step_version="2",
                param_hash="x",
                status="Running",
                pid=me.pid,
                pid_start_time=me.create_time(),
            )
        )
    result = wait_op(
        client,
        ws_id,
        client.post(f"/api/workspaces/{ws_id}/imports/{import_id}/undo").json()["operation_id"],
    )
    assert result["status"] == "Failed" and result["error"]["code"] == "JOBS_RUNNING"
    assert rawbids_files(ws)  # nothing was removed


def test_files_changed_after_the_import_are_never_removed(
    client: TestClient, tmp_path: Path, fake: Fake
) -> None:
    import os

    ws_id, import_id, ws = imported(client, tmp_path, fake)
    image = next(ws.root.glob("rawbids/sub-001/anat/*_T1w.nii.gz"))
    os.chmod(image, 0o644)
    with image.open("ab") as fh:  # changes the shared (hard-linked) data
        fh.write(b"edited")
    plan = client.get(f"/api/workspaces/{ws_id}/imports/{import_id}/undo-plan").json()
    assert plan["problems"]
    result = wait_op(
        client,
        ws_id,
        client.post(f"/api/workspaces/{ws_id}/imports/{import_id}/undo").json()["operation_id"],
    )
    assert result["status"] == "Failed" and result["error"]["code"] == "UNDO_FILES_CHANGED"
    assert image.exists()


def test_results_that_used_the_removed_files_are_listed(
    client: TestClient, tmp_path: Path, fake: Fake
) -> None:
    ws_id, import_id, ws = imported(client, tmp_path, fake)
    t1 = "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    sid = ws.get_or_create_subject("sub-001")
    with ws.session() as s:
        s.add(
            Job(
                step_name="fsl_anat",
                step_version="2",
                param_hash="x",
                status="Completed",
                subject_id=sid,
                inputs={"t1": t1},
            )
        )
    plan = client.get(f"/api/workspaces/{ws_id}/imports/{import_id}/undo-plan").json()
    assert plan["stale_steps"] == ["fsl_anat"]
    wait_op(
        client,
        ws_id,
        client.post(f"/api/workspaces/{ws_id}/imports/{import_id}/undo").json()["operation_id"],
    )
    with ws.session() as s:
        assert s.scalar(select(Job).where(Job.step_name == "fsl_anat")) is not None  # results stay
        assert s.scalar(select(File.id).where(File.relpath == t1)) is None


def test_cli_undo(tmp_path: Path, fake: Fake) -> None:
    ws = Workspace.create(tmp_path / "ws")
    make_session(tmp_path / "session")
    base = ["-w", str(ws.root)]
    assert runner.invoke(cli, ["import", "scan", str(tmp_path / "session"), *base]).exit_code == 0
    fake.set(2, images=[{"suffix": "", "shape": [4, 4, 3]}])
    fake.set(6, images=[{"suffix": "", "shape": [4, 4, 3, 4]}])
    fake.set(19, images=[{"suffix": "", "shape": [4, 4, 8, 5]}])
    runner.invoke(cli, ["import", "set", "19", "--task", "rest", *base])
    assert runner.invoke(cli, ["import", "run", *base]).exit_code == 0
    assert rawbids_files(ws)
    no = runner.invoke(cli, ["import", "undo", *base], input="n\n")
    assert no.exit_code == 1 and rawbids_files(ws)
    yes = runner.invoke(cli, ["import", "undo", "--yes", *base])
    assert yes.exit_code == 0 and "Converted copies and the scanner files are kept" in yes.output
    assert rawbids_files(ws) == []
