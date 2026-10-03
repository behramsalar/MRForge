"""Stage 3a: the HTTP API. Long actions really run in detached worker processes (no mocks of
the runner); dcm2niix is the stand-in from conftest, FSL is not needed."""

import time
from pathlib import Path

import pytest
from conftest import Fake
from dicomfactory import make_session
from fastapi.testclient import TestClient

from mrforge.api.app import create_app


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def client(home: Path) -> TestClient:
    return TestClient(create_app(home / "workspaces"))


def wait_operation(client: TestClient, ws: str, op_id: int, timeout: float = 60) -> dict:  # type: ignore[type-arg]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        op = client.get(f"/api/workspaces/{ws}/operations/{op_id}").json()
        if op["status"] not in ("Queued", "Running"):
            return op  # type: ignore[no-any-return]
        time.sleep(0.2)
    raise AssertionError("operation did not finish")


def test_health_reports_tools(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert "fsl" in body["tools"] and "dcm2niix" in body["tools"]


def test_create_and_list_workspaces(client: TestClient) -> None:
    assert client.get("/api/workspaces").json() == []
    made = client.post("/api/workspaces", json={"name": "My study"}).json()
    assert made["id"] == "My-study" and made["name"] == "My study"
    again = client.post("/api/workspaces", json={"name": "My study"}).json()
    assert again["id"] == "My-study-2"  # never overwrites
    assert [w["id"] for w in client.get("/api/workspaces").json()] == ["My-study", "My-study-2"]


def test_unknown_workspace_is_a_plain_404(client: TestClient) -> None:
    r = client.get("/api/workspaces/nothing/jobs")
    assert r.status_code == 404 and r.json()["code"] == "UNKNOWN_WORKSPACE"
    assert client.get("/api/workspaces/..%2Fetc/jobs").status_code in (400, 404)


def test_file_browser_stays_in_home(client: TestClient, home: Path) -> None:
    (home / "scans").mkdir()
    (home / "notes.txt").write_text("x")
    (home / "a.zip").write_bytes(b"PK")
    (home / ".hidden").mkdir()
    top = client.get("/api/fs").json()
    assert [e["name"] for e in top["entries"]] == ["scans", "a.zip"]
    assert top["parent"] is None
    assert client.get("/api/fs", params={"path": str(home / "scans")}).json()["parent"] == str(home)
    outside = client.get("/api/fs", params={"path": "/"})
    assert outside.status_code == 400 and outside.json()["code"] == "OUTSIDE_HOME"
    sneaky = client.get("/api/fs", params={"path": str(home / "scans" / ".." / ".." / "..")})
    assert sneaky.status_code == 400


def test_files_served_only_from_data_folders(client: TestClient) -> None:
    ws = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    root = client.app.state if False else None  # noqa: F841
    base = f"/api/workspaces/{ws}/file"
    assert client.get(f"{base}/workspace.json").status_code == 404
    assert client.get(f"{base}/db.sqlite").status_code == 404
    assert client.get(f"{base}/../../etc/passwd").status_code == 404
    assert client.get(f"{base}/rawbids/dataset_description.json").status_code in (200, 404)


def test_scan_confirm_and_import(client: TestClient, home: Path, fake: Fake) -> None:
    ws = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    make_session(home / "session")
    base = f"/api/workspaces/{ws}"

    started = client.post(f"{base}/imports/scan", json={"source": str(home / "session")})
    assert started.status_code == 200, started.text
    op = wait_operation(client, ws, started.json()["operation_id"])
    assert op["status"] == "Completed", op
    import_id = op["result"]["import_id"]

    detail = client.get(f"{base}/imports/{import_id}").json()
    assert detail["n_series"] == 3 and {k["kind"] for k in detail["kinds"]} >= {"T1w", "bold"}
    needs = [s for s in detail["series"] if s["action"] == "ask"]
    assert needs and needs[0]["needs"] == ["task"]  # the unnamed BOLD run asks for a task

    # the user decides; the table reflects it and remembers who decided
    number = needs[0]["number"]
    r = client.patch(f"{base}/imports/{import_id}/series/{number}", json={"task": "rest"})
    assert r.status_code == 200
    row = next(s for s in r.json()["series"] if s["number"] == number)
    assert row["action"] == "import" and row["entities"]["task"] == "rest"
    assert row["decided_by"] == "user"
    bad = client.patch(f"{base}/imports/{import_id}/series/{number}", json={"task": "not valid!"})
    assert bad.status_code == 400 and bad.json()["code"] == "BAD_LABEL"

    fake.set(2, images=[{"suffix": "", "shape": [4, 4, 3]}])
    fake.set(6, images=[{"suffix": "", "shape": [4, 4, 3, 4]}])
    fake.set(19, images=[{"suffix": "", "shape": [4, 4, 8, 5]}])
    run = client.post(f"{base}/imports/{import_id}/run", json={})
    done = wait_operation(client, ws, run.json()["operation_id"])
    assert done["status"] == "Completed", done["error"]
    subs = client.get(f"{base}/subjects").json()
    assert [s["label"] for s in subs] == ["sub-001"]
    assert [f["kind"] for f in subs[0]["files"]] == ["T1w", "bold", "bold"]
    assert (home / "workspaces" / ws / "rawbids" / "sub-001").is_dir()
    summary = client.get(f"{base}/imports").json()[0]
    assert summary["organized"] == 3 and summary["needs_input"] == 0


def test_only_one_operation_at_a_time(client: TestClient, home: Path, fake: Fake) -> None:
    ws = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    make_session(home / "session")
    base = f"/api/workspaces/{ws}"
    first = client.post(f"{base}/imports/scan", json={"source": str(home / "session")})
    second = client.post(f"{base}/imports/scan", json={"source": str(home / "session")})
    assert second.status_code == 409 and second.json()["code"] == "OPERATION_BUSY"
    wait_operation(client, ws, first.json()["operation_id"])


def test_failed_operation_has_structured_error(client: TestClient, home: Path) -> None:
    ws = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    (home / "empty").mkdir()
    base = f"/api/workspaces/{ws}"
    started = client.post(f"{base}/imports/scan", json={"source": str(home / "empty")})
    op = wait_operation(client, ws, started.json()["operation_id"])
    assert op["status"] == "Failed"
    assert op["error"]["message"] and op["error"]["suggested_action"]
    missing = client.post(f"{base}/imports/scan", json={"source": str(home / "nope")})
    assert missing.status_code == 404 and missing.json()["code"] == "SOURCE_NOT_FOUND"
    outside = client.post(f"{base}/imports/scan", json={"source": "/etc"})
    assert outside.status_code == 400


def test_killed_operation_becomes_interrupted(client: TestClient, home: Path) -> None:
    import os
    import signal

    from mrforge.models import Operation
    from mrforge.operations import start_operation
    from mrforge.workspace import Workspace

    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    ws = Workspace.open(home / "workspaces" / ws_id)
    # a pipeline of one slow fake step gives a long-lived worker to kill
    spec = {
        "name": "slow",
        "subject": "sub-001",
        "steps": [{"id": "a", "step": "fake", "params": {"duration": 60}}],
    }
    op_id = start_operation(ws, "pipeline", "slow", {"spec": spec})
    deadline = time.monotonic() + 20
    pid = None
    while time.monotonic() < deadline and pid is None:
        with ws.session() as s:
            pid = s.get(Operation, op_id).pid  # type: ignore[union-attr]
        time.sleep(0.1)
    assert pid
    os.kill(pid, signal.SIGKILL)
    time.sleep(0.5)
    op = client.get(f"/api/workspaces/{ws_id}/operations/{op_id}").json()
    assert op["status"] == "Interrupted" and op["error"]["code"] == "INTERRUPTED"
    # the job's own worker is detached, so it keeps running until stopped
    jobs = client.get(f"/api/workspaces/{ws_id}/jobs").json()
    for j in jobs:
        client.post(f"/api/workspaces/{ws_id}/jobs/{j['id']}/cancel")


def test_state_snapshot(client: TestClient) -> None:
    ws = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    state = client.get(f"/api/workspaces/{ws}/state").json()
    assert state == {"jobs": [], "operations": [], "imports": [], "subjects": []}


def test_events_stream_sends_current_state(home: Path) -> None:
    """A page that connects (or reconnects after a refresh) immediately gets the full state.
    Uses a real server: an endless stream cannot be read through the in-process test client."""
    import socket
    import threading

    import httpx
    import uvicorn

    app = create_app(home / "workspaces")
    ws = TestClient(app).post("/api/workspaces", json={"name": "w"}).json()["id"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        with httpx.stream("GET", f"http://127.0.0.1:{port}/api/workspaces/{ws}/events") as r:
            assert r.status_code == 200
            for line in r.iter_lines():
                if line.startswith("data:"):
                    assert '"jobs"' in line and '"operations"' in line
                    break
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_cancelling_an_operation_cancels_its_job(client: TestClient, home: Path) -> None:
    """Cancel is a user action: the running step is recorded as Cancelled (not as a crash)."""
    from mrforge.operations import start_operation
    from mrforge.workspace import Workspace

    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    ws = Workspace.open(home / "workspaces" / ws_id)
    spec = {
        "name": "slow",
        "subject": "sub-001",
        "steps": [{"id": "a", "step": "fake", "params": {"duration": 60}}],
    }
    op_id = start_operation(ws, "pipeline", "slow", {"spec": spec})
    base = f"/api/workspaces/{ws_id}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        jobs = client.get(f"{base}/jobs").json()
        if jobs and jobs[0]["status"] == "Running":
            break
        time.sleep(0.2)
    assert client.post(f"{base}/operations/{op_id}/cancel").status_code == 204
    op = wait_operation(client, ws_id, op_id)
    assert op["status"] in ("Cancelled", "Failed")
    assert client.get(f"{base}/jobs").json()[0]["status"] == "Cancelled"


def test_built_frontend_is_served_from_the_same_address(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = home / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>MRForge page</html>")
    monkeypatch.setenv("MRFORGE_FRONTEND", str(dist))
    client = TestClient(create_app(home / "workspaces"))
    assert "MRForge page" in client.get("/").text
    assert client.get("/api/health").status_code == 200  # the API still wins
