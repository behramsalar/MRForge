"""Researcher profiles: names (not logins) that tag what people start."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mrforge import accounts
from mrforge.api.app import create_app
from mrforge.errors import StepError
from mrforge.workspace import Workspace


@pytest.fixture(autouse=True)
def own_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets its own profile store (it lives next to the app settings)."""
    monkeypatch.setenv("MRFORGE_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("HOME", str(tmp_path))


def test_create_and_list_sorted_without_regard_to_case() -> None:
    accounts.create_researcher("zoe Adams")
    accounts.create_researcher("Jane  Smith")  # spaces are tidied
    names = [r.name for r in accounts.list_researchers()]
    assert names == ["Jane Smith", "zoe Adams"]


def test_names_are_unique_ignoring_case() -> None:
    accounts.create_researcher("Jane Smith")
    with pytest.raises(StepError) as err:
        accounts.create_researcher("jane smith")
    assert err.value.code == "NAME_TAKEN" and "Pick that name" in err.value.suggested_action


@pytest.mark.parametrize("bad", ["", "   ", "<script>", "a" * 61, "\n", "_hidden"])
def test_bad_names_are_explained(bad: str) -> None:
    with pytest.raises(StepError) as err:
        accounts.create_researcher(bad)
    assert err.value.code == "BAD_NAME" and err.value.suggested_action


def test_unusual_but_real_names_work() -> None:
    for name in ("Ayşe Yılmaz", "Anne-Marie O'Neil", "J. R. Tolkien", "李雷"):
        assert accounts.create_researcher(name).name == name


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "workspaces"))


def test_api_profile_flow(client: TestClient) -> None:
    assert client.get("/api/me").json() is None  # nobody picked a profile yet
    made = client.post("/api/researchers", json={"name": "Jane Smith"}).json()
    assert made["name"] == "Jane Smith"
    dup = client.post("/api/researchers", json={"name": "JANE SMITH"})
    assert dup.status_code == 400 and dup.json()["code"] == "NAME_TAKEN"
    assert [r["name"] for r in client.get("/api/researchers").json()] == ["Jane Smith"]
    me = client.get("/api/me", headers={"X-MRForge-User": str(made["id"])}).json()
    assert me["name"] == "Jane Smith"
    assert client.get("/api/me", headers={"X-MRForge-User": "999"}).json() is None
    assert client.get("/api/me", headers={"X-MRForge-User": "abc"}).json() is None
    again = client.get("/api/researchers").json()[0]
    assert again["last_seen"] is not None  # the visit was noted


def test_operations_remember_who_started_them(client: TestClient, tmp_path: Path) -> None:
    jane = client.post("/api/researchers", json={"name": "Jane Smith"}).json()["id"]
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    (tmp_path / "empty").mkdir()
    started = client.post(
        f"/api/workspaces/{ws_id}/imports/scan",
        json={"source": str(tmp_path / "empty")},
        headers={"X-MRForge-User": str(jane)},
    ).json()["operation_id"]
    deadline = time.monotonic() + 30
    op = {}
    while time.monotonic() < deadline:
        op = client.get(f"/api/workspaces/{ws_id}/operations/{started}").json()
        if op["status"] not in ("Queued", "Running"):
            break
        time.sleep(0.2)
    assert op["started_by"] == "Jane Smith"
    # without a profile the action still works and is simply not attributed
    second = client.post(
        f"/api/workspaces/{ws_id}/imports/scan", json={"source": str(tmp_path / "empty")}
    ).json()["operation_id"]
    while time.monotonic() < deadline:
        op2 = client.get(f"/api/workspaces/{ws_id}/operations/{second}").json()
        if op2["status"] not in ("Queued", "Running"):
            break
        time.sleep(0.2)
    assert op2["started_by"] is None


def test_workspaces_from_before_profiles_are_upgraded(tmp_path: Path) -> None:
    import json

    root = tmp_path / "old"
    ws = Workspace.create(root)
    with ws.engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE operation DROP COLUMN started_by")
    ws.engine.dispose()
    meta_path = root / "workspace.json"
    meta = json.loads(meta_path.read_text())
    meta["schema_version"] = 3
    meta_path.write_text(json.dumps(meta))
    reopened = Workspace.open(root)
    assert json.loads(meta_path.read_text())["schema_version"] == 4
    from mrforge.operations import list_operations

    assert list_operations(reopened) == []  # the table works with the new column
