"""Stage 10f: the table of correlation results and the index file with full paths (no FSL)."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mrforge import qc_decisions, roi_results
from mrforge.api.app import create_app
from mrforge.engine import Action, run_step
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.workspace import Workspace

SPACE = "space-MNI152NLin6Asym"


def func_dir(ws: Workspace, sub: str, ses: str | None = None) -> str:
    return f"derivatives/mrforge/{sub}/" + (f"{ses}/" if ses else "") + "func"


def make_result(
    ws: Workspace,
    sub: str,
    atlas: str = "schaefer100n7",
    run: str = "task-rest",
    ses: str | None = None,
    desc: str = "denoised",
    low: int = 0,
    empty: bool = False,
) -> str:
    """A time series and its extraction record as roi_timeseries writes them, then the real
    roi_correlation step on top of them."""
    func = func_dir(ws, sub, ses)
    folder = f"{func}/connectivity/{atlas}"
    sesname = f"_{ses}" if ses else ""
    stem = f"{sub}{sesname}_{run}_{SPACE}_seg-{atlas}"
    (ws.root / folder).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    x = 100 + rng.normal(size=(30, 4))
    if empty:
        x[:, 2] = np.nan
    header = ["L_A", "L_B", "R_A", "R_B"]
    lines = ["\t".join(header)] + ["\t".join(f"{v:.6f}" for v in row) for row in x]
    (ws.root / folder / f"{stem}_timeseries.tsv").write_text("\n".join(lines) + "\n")
    (ws.root / folder / f"{stem}_roi.json").write_text(
        json.dumps(
            {
                "atlas": atlas,
                "signal_definition": "inside the brain mask of the recording and varying over time",
                "n_low_coverage": low,
                "min_coverage": 0.5,
                "mean_coverage": 0.97,
            }
        )
    )
    source = f"{func}/{sub}{sesname}_{run}_{SPACE}_desc-{desc}_bold.nii.gz"
    ts_rel = f"{folder}/{stem}_timeseries.tsv"
    outcome = run_step(
        ws, LocalJobQueue(ws), "roi_correlation", sub, {"timeseries": ts_rel}, {},
        session=ses, label=f"roi_correlation_{atlas}",
    )  # fmt: skip
    assert outcome.action == Action.RAN, outcome.reason
    # roi_correlation records the time-series file as its input; say which data it came from
    info = ws.root / folder / f"{stem}_stat-pearsoncorrelation_relmat.json"
    record = json.loads(info.read_text())
    record["input"] = source
    info.write_text(json.dumps(record))
    return stem


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def test_an_empty_workspace_has_no_rows(ws: Workspace) -> None:
    assert roi_results.collect(ws) == [] and roi_results.list_exports(ws) == []


def test_a_row_per_recording_and_atlas_in_order(ws: Workspace) -> None:
    make_result(ws, "sub-002")
    make_result(ws, "sub-001", atlas="aal3v2")
    make_result(ws, "sub-001", atlas="schaefer100n7")
    make_result(ws, "sub-001", run="task-rest_run-2", ses="ses-01")
    rows = roi_results.collect(ws)
    assert [(r.subject, r.session, r.recording, r.atlas) for r in rows] == [
        ("sub-001", None, "task-rest", "aal3v2"),
        ("sub-001", None, "task-rest", "schaefer100n7"),
        ("sub-001", "ses-01", "task-rest_run-2", "schaefer100n7"),
        ("sub-002", None, "task-rest", "schaefer100n7"),
    ]
    first = rows[0]
    assert first.atlas_name == "AAL3 (version 3v2)" and first.regions == 4 and first.volumes == 30
    assert first.data == "denoised" and "brain mask" in first.averaging
    assert set(first.files) == {"timeseries", "pearson", "fisherz", "info", "roi"}
    assert all((ws.root / p).is_file() for p in first.files.values())
    assert first.flags == [] and first.decision is None


def test_the_data_a_result_comes_from_is_named(ws: Workspace) -> None:
    make_result(ws, "sub-001", desc="preproc")
    assert roi_results.collect(ws)[0].data == "preproc"


def test_flags_warn_but_nothing_is_left_out(ws: Workspace) -> None:
    make_result(ws, "sub-001", low=3, empty=True)
    (row,) = roi_results.collect(ws)
    assert row.regions_low_coverage == 3 and row.regions_without_values == 1
    assert any("under 50%" in f for f in row.flags) and any(
        "no usable signal" in f for f in row.flags
    )


def test_a_missing_file_is_flagged_not_hidden(ws: Workspace) -> None:
    stem = make_result(ws, "sub-001")
    (
        ws.derivatives_dir
        / "sub-001"
        / "func"
        / "connectivity"
        / "schaefer100n7"
        / f"{stem}_stat-fisherz_relmat.txt"
    ).unlink()
    (row,) = roi_results.collect(ws)
    assert any("missing files: fisherz" in f for f in row.flags)


def test_the_researchers_decision_is_shown(ws: Workspace) -> None:
    make_result(ws, "sub-001")
    qc_decisions.record(ws, "sub-001", "exclude", "moved a lot", "Jane")
    (row,) = roi_results.collect(ws)
    assert (row.decision, row.decision_reason, row.decision_who) == (
        "exclude", "moved a lot", "Jane",
    )  # fmt: skip


def test_the_index_has_full_paths_and_leaves_nobody_out_by_default(ws: Workspace) -> None:
    make_result(ws, "sub-001")
    make_result(ws, "sub-002")
    qc_decisions.record(ws, "sub-002", "exclude", "artefacts", None)
    (path,) = roi_results.export(ws)
    assert path.parent == ws.root / "reports" / "roi" and path.name.startswith("roi_matrices_")
    with path.open(newline="") as f:
        table = list(csv.DictReader(f))
    assert [r["subject"] for r in table] == ["sub-001", "sub-002"]  # excluded stays listed
    assert table[1]["qc_decision"] == "exclude" and table[1]["qc_reason"] == "artefacts"
    for r in table:
        for column in ("pearson_matrix", "fisherz_matrix", "timeseries", "record"):
            assert Path(r[column]).is_absolute() and Path(r[column]).is_file()
        m = np.loadtxt(r["pearson_matrix"])
        assert m.shape == (4, 4) and np.allclose(np.diag(m), 1.0)  # plain numbers, as written
    (left,) = roi_results.export(ws, leave_out_excluded=True)
    with left.open(newline="") as f:
        assert [r["subject"] for r in csv.DictReader(f)] == ["sub-001"]
    assert [p.name for p in roi_results.list_exports(ws)][0] in (path.name, left.name)
    assert len(roi_results.list_exports(ws)) == 2  # two exports in the same second do not clash


def test_the_routes(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    base = f"/api/workspaces/{ws_id}/roi-results"
    assert client.get(base).json() == [] and client.get(f"{base}/exports").json() == []
    made = (
        Workspace.open(tmp_path / "workspaces" / ws_id)
        if (tmp_path / "workspaces" / ws_id).exists()
        else None
    )
    if made is None:
        pytest.skip("cannot locate the workspace folder of the API test")
    make_result(made, "sub-001")
    rows = client.get(base).json()
    assert len(rows) == 1 and rows[0]["atlas"] == "schaefer100n7"
    exported = client.post(f"{base}/export").json()
    assert len(exported) == 1 and exported[0]["name"].endswith(".csv")
    assert client.get(exported[0]["url"]).status_code == 200  # served by the file route
    assert [e["name"] for e in client.get(f"{base}/exports").json()] == [exported[0]["name"]]
