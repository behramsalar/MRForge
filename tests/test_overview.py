"""The dashboard overview: where each subject stands, derived from files and jobs."""

import json
from pathlib import Path

import nibabel as nib
import numpy as np

from mrforge.functional import ANAT_FILES
from mrforge.models import File, Job
from mrforge.overview import build_overview
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001"
BOLD = "rawbids/sub-001/func/sub-001_task-rest_bold.nii.gz"
BOLD2 = "rawbids/sub-001/func/sub-001_task-other_bold.nii.gz"


def image(path: Path, shape: tuple[int, ...] = (4, 4, 4)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.ones(shape, dtype="float32"), np.eye(4)), path)


def workspace(tmp_path: Path, *, t1: bool = True, runs: tuple[str, ...] = (BOLD,)) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    sid = ws.get_or_create_subject("sub-001")
    with ws.session() as s:
        if t1:
            s.add(
                File(subject_id=sid, relpath="rawbids/sub-001/anat/sub-001_T1w.nii.gz", kind="T1w")
            )
        for run in runs:
            image(ws.root / run, (4, 4, 4, 5))
            (ws.root / run.replace(".nii.gz", ".json")).write_text(
                json.dumps({"RepetitionTime": 2})
            )
            s.add(File(subject_id=sid, relpath=run, kind="bold"))
    return ws


def anat_done(ws: Workspace) -> None:
    for ending in ANAT_FILES.values():
        image(ws.derivatives_dir / "sub-001" / "anat" / f"sub-001{ending}")


def add_job(ws: Workspace, step: str, status: str, run: str = "") -> None:
    sid = ws.get_or_create_subject("sub-001")
    folder = step + (f"_{run}" if run else "")
    with ws.session() as s:
        s.add(
            Job(
                step_name=step,
                step_version="1",
                subject_id=sid,
                param_hash="x",
                status=status,
                run_dir=f"{D}/func/_runs/{folder}",
                started_by="Jane Smith",
            )
        )


def subject(ws: Workspace):  # type: ignore[no-untyped-def]
    [row] = build_overview(ws).subjects
    return row


def test_a_fresh_subject_has_nothing_started(tmp_path: Path) -> None:
    row = subject(workspace(tmp_path))
    assert row.anatomical.state == "none" and row.functional.state == "none"
    o = build_overview(workspace(tmp_path / "b"))
    assert (o.subjects_total, o.processed, o.needs_attention, o.running) == (1, 0, 0, 0)


def test_without_a_t1_or_a_run_the_stage_is_unavailable(tmp_path: Path) -> None:
    ws = workspace(tmp_path, t1=False, runs=())
    row = subject(ws)
    assert row.anatomical.state == "unavailable" and "T1" in (row.anatomical.detail or "")
    assert row.functional.state == "unavailable"


def test_anatomical_results_make_it_done_and_a_running_job_overrides(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    anat_done(ws)
    assert subject(ws).anatomical.state == "done"
    add_job(ws, "fsl_anat", "Running")  # processing again
    assert subject(ws).anatomical.state == "running"


def test_failed_and_interrupted_steps_need_attention(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    add_job(ws, "fsl_anat", "Failed")
    o = build_overview(ws)
    assert o.subjects[0].anatomical.state == "failed" and o.needs_attention == 1
    add_job(ws, "fsl_anat", "Interrupted")
    assert subject(ws).anatomical.state == "stopped"


def test_functional_run_is_done_only_when_qc_and_standard_space_finished(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    anat_done(ws)
    add_job(ws, "feat_preproc", "Completed", "task-rest")
    assert subject(ws).functional.state == "partial"
    add_job(ws, "func_qc", "Completed", "task-rest")
    add_job(ws, "func_to_mni", "Completed", "task-rest")
    row = subject(ws)
    assert row.functional.state == "done"
    assert build_overview(ws).processed == 1


def test_several_runs_are_counted(tmp_path: Path) -> None:
    ws = workspace(tmp_path, runs=(BOLD, BOLD2))
    anat_done(ws)
    for step in ("feat_preproc", "func_qc", "func_to_mni"):
        add_job(ws, step, "Completed", "task-rest")
    f = subject(ws).functional
    assert f.state == "partial" and f.detail == "1 of 2 runs"
    add_job(ws, "feat_preproc", "Failed", "task-other")
    assert subject(ws).functional.state == "failed"


def test_a_failed_fieldmap_step_stops_the_run_before_it_starts(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    anat_done(ws)
    add_job(ws, "fieldmap_prep", "Failed")
    assert subject(ws).functional.state == "failed"


def test_activity_shows_who_and_what_ran_last(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    add_job(ws, "fsl_anat", "Completed")
    row = subject(ws)
    assert row.last_activity_by == "Jane Smith" and row.last_activity is not None


def test_the_overview_route(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from mrforge.api.app import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    empty = client.get(f"/api/workspaces/{ws_id}/overview").json()
    assert empty["subjects_total"] == 0 and empty["subjects"] == [] and empty["running"] == 0
    assert [s["id"] for s in empty["stages"]] == [
        "import",
        "anatomical",
        "preprocessing",
        "artifact_rejection",
        "standard_space",
    ]
    assert client.get("/api/workspaces/nothing/overview").status_code == 404


def test_a_failed_task_that_was_repeated_successfully_is_not_shown_as_recent_failure(
    tmp_path: Path,
) -> None:
    from mrforge.models import Operation

    ws = Workspace.create(tmp_path / "ws")
    with ws.session() as s:
        s.add_all(
            [
                Operation(kind="scan", title="Reading test.zip", status="Failed"),
                Operation(kind="scan", title="Reading test.zip", status="Completed"),
                Operation(kind="scan", title="Reading other.zip", status="Failed"),
            ]
        )
    shown = [(a.title, a.status) for a in build_overview(ws).recent]
    assert ("Reading test.zip", "Failed") not in shown
    assert ("Reading other.zip", "Failed") in shown


def chips(row) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {c.id: c.state for c in row.stages}


def test_every_subject_has_the_same_five_stage_chips(tmp_path: Path) -> None:
    row = subject(workspace(tmp_path))
    assert [c.id for c in row.stages] == [
        "import", "anatomical", "preprocessing", "artifact_rejection", "standard_space",
    ]  # fmt: skip
    assert chips(row)["import"] == "none" or chips(row)["import"] == "done"
    assert not row.complete


def test_a_subject_is_complete_when_the_standard_pipeline_is_done(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    anat_done(ws)
    for step in ("feat_preproc", "func_qc"):
        add_job(ws, step, "Completed", "task-rest")
    row = subject(ws)
    assert chips(row)["preprocessing"] == "done" and not row.complete  # standard space missing
    add_job(ws, "func_to_mni", "Completed", "task-rest")
    row = subject(ws)
    assert chips(row)["standard_space"] == "done" and row.complete
    assert chips(row)["artifact_rejection"] == "none"  # optional: not done, not required


def test_artifact_rejection_waiting_for_the_researcher_shows_as_review(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    add_job(ws, "melodic", "Completed", "task-rest")
    add_job(ws, "ica_labels", "Waiting", "task-rest")
    assert chips(subject(ws))["artifact_rejection"] == "review"
    add_job(ws, "ica_labels", "Completed", "task-rest")
    add_job(ws, "regfilt", "Completed", "task-rest")
    assert chips(subject(ws))["artifact_rejection"] == "done"


def test_a_failed_standard_space_step_is_flagged_on_its_own_chip(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    anat_done(ws)
    for step in ("feat_preproc", "func_qc"):
        add_job(ws, step, "Completed", "task-rest")
    add_job(ws, "func_to_mni", "Failed", "task-rest")
    row = subject(ws)
    assert chips(row)["preprocessing"] == "done" and chips(row)["standard_space"] == "failed"
    assert not row.complete


def test_motion_numbers_are_taken_from_the_qc_record(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    folder = ws.derivatives_dir / "sub-001" / "func"
    folder.mkdir(parents=True)
    (folder / "sub-001_task-rest_desc-metrics_qc.json").write_text(
        json.dumps(
            {
                "fd_mean_mm": 0.1234,
                "fd_max_mm": 0.9,
                "fd_above_threshold": 3,
                "n_volumes": 355,
                "fd_threshold_mm": 0.5,
            }
        )  # fmt: skip
    )
    qc = subject(ws).qc
    assert (
        qc is not None and qc.fd_mean_mm == 0.123 and qc.volumes_above == 3 and qc.n_volumes == 355
    )
