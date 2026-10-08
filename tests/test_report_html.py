"""Stage 8c: the report as an API and as a self-contained HTML file."""

import base64
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mrforge.api.app import create_app
from mrforge.engine import run_step
from mrforge.provenance import read_provenance, write_provenance
from mrforge.runner.jobs import list_jobs
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.base import QCItem, SliceRef
from mrforge.workspace import Workspace

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path))
    return TestClient(create_app(tmp_path / "workspaces"))


def make_subject(client: TestClient, root: Path) -> tuple[str, Workspace, list[str]]:
    wsid = client.post("/api/workspaces", json={"name": "r"}).json()["id"]
    ws = Workspace.open(root / wsid)
    run_step(ws, LocalJobQueue(ws), "fake", "sub-001", params={"content": "x"})
    job = next(j for j in list_jobs(ws) if j.step_name == "fake")
    out = ws.abspath(job.output_dir or "")
    prov = read_provenance(ws.abspath(job.run_dir or ""))
    assert prov is not None
    refs, paths = [], []
    for k in range(3):
        (out / f"s{k}.png").write_bytes(PNG)
        refs.append(SliceRef(plane="axial", position=0.1 * k, layer="mni", path=f"s{k}.png"))
        paths.append(ws.relpath(out / f"s{k}.png"))
    prov.qc = [
        QCItem(name="Mean FD (mm)", kind="metric", value=0.2),
        QCItem(name="Alignment", kind="image", path="s0.png", slices=refs),
    ]
    write_provenance(ws.abspath(job.run_dir or ""), prov)
    return wsid, ws, paths


def test_report_route_returns_the_recorded_figures(client: TestClient, tmp_path: Path) -> None:
    wsid, _, paths = make_subject(client, tmp_path / "workspaces")
    body = client.get(f"/api/workspaces/{wsid}/subjects/sub-001/report").json()
    run = next(r for s in body["sections"] for r in s["runs"])
    assert run["qc"][0]["value"] == "0.2"
    assert [s["image"] for s in run["qc"][1]["slices"]] == paths
    assert client.get(f"/api/workspaces/{wsid}/subjects/sub-999/report").status_code == 404


def test_export_is_self_contained_with_a_fixed_layout(client: TestClient, tmp_path: Path) -> None:
    wsid, ws, paths = make_subject(client, tmp_path / "workspaces")
    r = client.post(f"/api/workspaces/{wsid}/subjects/sub-001/report/export")
    assert r.status_code == 200
    info = r.json()
    page = (ws.root / "reports" / "sub-001" / info["name"]).read_text()
    assert "Mean FD (mm)" in page and "0.2" in page
    assert page.count("data:image/png;base64") == 3  # the three slices, in one plane column
    assert "class='planes'" in page
    assert not re.search(r"(?:src|href)=['\"]https?://", page)  # nothing is fetched from outside
    again = client.post(f"/api/workspaces/{wsid}/subjects/sub-001/report/export")
    assert again.json()["name"] != info["name"]  # a second export is a second file
    assert len(client.get(f"/api/workspaces/{wsid}/reports").json()) == 2
    assert client.get(info["url"]).status_code == 200  # served from the reports folder
