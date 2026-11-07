"""The ALPS results table and its CSV / Excel export (Stage 9h)."""

import csv
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from mrforge import alps_results, qc_decisions
from mrforge.workspace import Workspace

ROIS = ("proj_L", "assoc_L", "proj_R", "assoc_R")
SETTINGS = {
    "preprocessing": "none",
    "distortion correction": "none",
    "eddy": "eddy_cpu",
    "registration": "linear",
    "template": "jhu_fa",
    "tensor transform": "flirt",
    "regions": "default",
}


def record(alps: float, notes: list[str] | None = None) -> dict:
    comp = {
        k: 0.0005 + i * 1e-5
        for i, k in enumerate(
            ["x_proj_L", "x_assoc_L", "y_proj_L", "z_assoc_L"]
            + ["x_proj_R", "x_assoc_R", "y_proj_R", "z_assoc_R"]
        )
    }
    maps = {k: 0.5 for k in ROIS} | {"mean_proj": 0.5, "mean_assoc": 0.5}
    return {
        "id": "x", "scanner": "Siemens", "alps_L": alps, "alps_R": alps, "alps": alps,
        "components": comp, "fa": maps, "md": maps | {"mean_proj": 0.0007},
        "voxels": dict.fromkeys(ROIS, 81), "settings": SETTINGS, "notes": notes or [],
        "checks": [], "versions": {"FSL": "6.0.7", "mrforge_step": "alps_index 1"},
    }  # fmt: skip


def put(ws: Workspace, subject: str, alps: float, *, session: str | None = None,
        run: str | None = None, tag: str = "", regions: str = "packaged 2.5 mm spheres",
        notes: list[str] | None = None, movement: float | None = None) -> None:  # fmt: skip
    folder = ws.derivatives_dir / subject / (session or "") / "dwi"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{subject}_run-{run}" if run else subject
    data = record(alps, notes)
    data["settings"] = {**SETTINGS, "regions": regions}
    (folder / f"{stem}_desc-alps{tag}_alps.json").write_text(json.dumps(data))
    if movement is not None:
        (folder / f"{stem}_desc-dwimetrics_qc.json").write_text(
            json.dumps({"mean_rms_previous_mm": movement})
        )


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def test_one_row_per_series_with_numbers_straight_from_the_record(ws: Workspace) -> None:
    put(ws, "sub-002", 1.5)
    put(ws, "sub-001", 1.2, session="ses-01", run="1")
    put(ws, "sub-001", 1.3, session="ses-01", run="2")
    rows = alps_results.collect(ws)
    assert [(r.subject, r.session, r.series) for r in rows] == [
        ("sub-001", "ses-01", "run-1"),
        ("sub-001", "ses-01", "run-2"),
        ("sub-002", None, ""),
    ]
    assert rows[0].alps == 1.2 and rows[0].fa == 0.5 and rows[0].md == 0.0007 / 2 + 0.25


def test_two_sets_of_regions_for_one_series_are_two_rows_with_the_right_motion(
    ws: Workspace,
) -> None:
    put(ws, "sub-001", 1.5, movement=0.4)
    put(ws, "sub-001", 1.1, tag="legacy5", regions="packaged 5 mm boxes (older)", movement=0.4)
    by = {r.regions: r for r in alps_results.collect(ws)}
    assert len(by) == 2
    assert (
        by["packaged 2.5 mm spheres"].alps == 1.5 and by["packaged 5 mm boxes (older)"].alps == 1.1
    )
    assert all(r.mean_movement_mm == 0.4 for r in by.values())  # both see the same series' motion
    (_, xlsx) = alps_results.export(ws)
    summary = list(load_workbook(xlsx)["Summary"].iter_rows(values_only=True))
    assert summary[0][3] == "regions" and {r[3] for r in summary[1:]} == set(by)


def test_results_made_before_region_sets_existed_get_a_readable_name(ws: Workspace) -> None:
    put(ws, "sub-001", 1.5, regions="default")  # what the first version of the step recorded
    (row,) = alps_results.collect(ws)
    assert row.regions == "packaged 2.5 mm spheres"


def test_flags_warn_and_never_exclude(ws: Workspace) -> None:
    put(ws, "sub-001", 1.0, notes=["no distortion correction"], movement=2.5, run="1")
    put(ws, "sub-002", 1.0, movement=0.3)
    flagged, clean = alps_results.collect(ws)
    assert (
        any("2.50 mm" in f for f in flagged.flags) and "no distortion correction" in flagged.flags
    )
    assert clean.flags == [] and flagged.decision is None  # nothing decided for the researcher


def test_the_researchers_decision_is_shown_with_its_reason(ws: Workspace) -> None:
    put(ws, "sub-001", 1.0)
    qc_decisions.record(ws, "sub-001", "exclude", "slept in the scanner", "Jane")
    (row,) = alps_results.collect(ws)
    assert (row.decision, row.decision_reason, row.decision_who) == (
        "exclude", "slept in the scanner", "Jane",
    )  # fmt: skip


def test_export_writes_csv_and_a_workbook_that_reads_back_equal(ws: Workspace) -> None:
    put(ws, "sub-001", 1.23456789012, movement=0.2)
    put(ws, "sub-002", 1.4, notes=["denoising skipped: MRtrix3 is not installed"])
    csv_path, xlsx_path = alps_results.export(ws)
    assert csv_path.parent == ws.root / "reports" / "alps" and csv_path.suffix == ".csv"
    with csv_path.open(newline="") as f:
        table = list(csv.DictReader(f))
    assert [r["subject"] for r in table] == ["sub-001", "sub-002"]
    assert float(table[0]["ALPS"]) == 1.23456789012  # full precision
    wb = load_workbook(xlsx_path)
    assert wb.sheetnames == [
        "Summary", "ROI diffusivities", "FA & MD", "Settings & versions", "Flags & notes", "About",
    ]  # fmt: skip
    summary = list(wb["Summary"].iter_rows(values_only=True))
    assert summary[0][4] == "ALPS" and summary[1][4] == 1.23456789012  # a number, not text
    flags = [r for r in wb["Flags & notes"].iter_rows(min_row=2, values_only=True)]
    assert any("MRtrix3" in str(r[-1]) for r in flags)
    about = {r[0]: r[1] for r in wb["About"].iter_rows(min_row=2, values_only=True)}
    assert "Aging and Disease" in about["Please cite"] and "linear" in about["Methods"]
    assert wb["ROI diffusivities"]["B1"].value == "session"


def test_excluded_subjects_stay_unless_the_researcher_leaves_them_out(ws: Workspace) -> None:
    put(ws, "sub-001", 1.0)
    put(ws, "sub-002", 1.1)
    qc_decisions.record(ws, "sub-002", "exclude", "artefacts", None)
    kept = load_workbook(alps_results.export(ws)[1])
    assert kept["Summary"].max_row == 3  # header + both
    out = load_workbook(alps_results.export(ws, leave_out_excluded=True)[1])
    assert out["Summary"].max_row == 2
    about = {r[0]: r[1] for r in out["About"].iter_rows(min_row=2, values_only=True)}
    assert about["Left out at export"] == "sub-002"  # it is still said


def test_two_exports_in_the_same_second_do_not_overwrite_each_other(ws: Workspace) -> None:
    put(ws, "sub-001", 1.0)
    first = alps_results.export(ws)
    second = alps_results.export(ws)
    assert set(first).isdisjoint(second) and len(alps_results.list_exports(ws)) == 4


def test_an_empty_workspace_gives_an_empty_table_and_a_valid_workbook(ws: Workspace) -> None:
    assert alps_results.collect(ws) == []
    wb = load_workbook(alps_results.export(ws)[1])
    assert wb["Summary"].max_row == 1


def test_the_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from mrforge.api.app import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    assert client.get(f"/api/workspaces/{ws_id}/alps-results").json() == []
    ws = Workspace.open(tmp_path / "workspaces" / ws_id)
    put(ws, "sub-001", 1.0)
    rows = client.get(f"/api/workspaces/{ws_id}/alps-results").json()
    assert rows[0]["subject"] == "sub-001" and rows[0]["alps"] == 1.0
    made = client.post(f"/api/workspaces/{ws_id}/alps-results/export").json()
    assert sorted(m["name"].rsplit(".", 1)[1] for m in made) == ["csv", "xlsx"]
    listed = client.get(f"/api/workspaces/{ws_id}/alps-results/exports").json()
    assert len(listed) == 2
    assert client.get(listed[0]["url"]).status_code == 200
