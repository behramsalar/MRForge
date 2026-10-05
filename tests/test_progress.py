"""Live progress: which step runs now, what finished, what was skipped, what the tool does."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from mrforge.api.app import create_app
from mrforge.models import Job, Operation, PipelineRun
from mrforge.progress import _phrase, _shorten, live_info, operation_progress
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001"
SPEC = {
    "name": "full-sub-001",
    "subject": "sub-001",
    "steps": [
        {"id": "fsl_anat", "step": "fsl_anat", "inputs": {"t1": "rawbids/sub-001/anat/sub-001_T1w.nii.gz"}},
        {"id": "feat_preproc__task-rest", "label": "feat_preproc", "step": "feat_preproc", "inputs": {"bold": "b"}},
        {"id": "func_qc__task-rest", "label": "func_qc", "step": "func_qc", "inputs": {"motion": "${feat_preproc__task-rest.motion}"}},
        {"id": "func_to_mni__task-rest", "label": "func_to_mni", "step": "func_to_mni", "inputs": {"bold": "${feat_preproc__task-rest.preproc_bold}"}},
    ],
}  # fmt: skip


def setup(tmp_path: Path, status: str = "Running") -> tuple[Workspace, Operation, int]:
    ws = Workspace.create(tmp_path / "ws")
    sid = ws.get_or_create_subject("sub-001")
    now = datetime.now(UTC)
    with ws.session() as s:
        op = Operation(kind="pipeline", title="Full processing of sub-001", args={"spec": SPEC},
                       status=status, started=now - timedelta(minutes=5), started_by="Jane Smith")  # fmt: skip
        run = PipelineRun(name="full-sub-001", spec=SPEC, created=now - timedelta(minutes=4))
        s.add_all([op, run])
        s.flush()
        return ws, op, run.id * 0 + sid  # sid is returned for the jobs below


def add_job(
    ws: Workspace,
    sid: int,
    step: str,
    status: str,
    label: str | None = None,
    run_folder: str = "",
    **kw: object,
) -> Job:
    with ws.session() as s:
        run_id = s.query(PipelineRun).order_by(PipelineRun.id.desc()).first().id  # type: ignore[union-attr]
        job = Job(
            step_name=step, step_version="1", param_hash="x", status=status, subject_id=sid,
            pipeline_run_id=run_id, label=label, run_dir=f"{D}/anat/_runs/{run_folder or step}",
            started=datetime.now(UTC) - timedelta(minutes=1), **kw,
        )  # fmt: skip
        s.add(job)
        s.flush()
        return job


def states(ws: Workspace, op: Operation) -> list[str]:
    return [s.state for s in operation_progress(ws, op).steps]


def test_a_step_is_running_and_the_rest_wait(tmp_path: Path) -> None:
    ws, op, sid = setup(tmp_path)
    add_job(ws, sid, "fsl_anat", "Completed")
    add_job(ws, sid, "feat_preproc", "Running", "feat_preproc", "feat_preproc_task-rest")
    p = operation_progress(ws, op)
    assert [s.state for s in p.steps] == ["done", "running", "waiting", "waiting"]
    assert (p.current, p.done, p.total) == (1, 1, 4)
    assert p.steps[1].run == "task-rest" and p.started_by == "Jane Smith"


def test_work_that_was_already_up_to_date_is_shown_as_skipped(tmp_path: Path) -> None:
    ws, op, sid = setup(tmp_path)  # fsl_anat was reused: it has no job
    add_job(ws, sid, "feat_preproc", "Completed", "feat_preproc", "feat_preproc_task-rest")
    add_job(ws, sid, "func_qc", "Running", "func_qc", "func_qc_task-rest")
    p = operation_progress(ws, op)
    assert [s.state for s in p.steps] == ["reused", "done", "running", "waiting"]
    assert p.done == 2 and p.current == 2


def test_a_finished_pipeline_with_nothing_to_do_shows_everything_skipped(tmp_path: Path) -> None:
    ws, op, _ = setup(tmp_path, status="Completed")
    assert states(ws, op) == ["reused"] * 4


def test_a_failed_step_stops_the_list(tmp_path: Path) -> None:
    ws, op, sid = setup(tmp_path, status="Failed")
    add_job(ws, sid, "fsl_anat", "Completed")
    add_job(ws, sid, "feat_preproc", "Failed", "feat_preproc", "feat_preproc_task-rest")
    assert states(ws, op) == ["done", "failed", "waiting", "waiting"]
    ws2, op2, sid2 = setup(tmp_path / "b", status="Interrupted")
    add_job(ws2, sid2, "fsl_anat", "Interrupted")
    assert states(ws2, op2)[0] == "stopped"


def test_two_recordings_are_told_apart(tmp_path: Path) -> None:
    spec = {
        "name": "full-sub-001",
        "subject": "sub-001",
        "steps": [
            {"id": f"feat_preproc__{r}", "label": "feat_preproc", "step": "feat_preproc", "inputs": {"bold": r}}
            for r in ("task-a", "task-b")
        ],
    }  # fmt: skip
    ws, op, sid = setup(tmp_path)
    with ws.session() as s:
        s.get(Operation, op.id).args = {"spec": spec}  # type: ignore[union-attr]
    add_job(
        ws, sid, "feat_preproc", "Running", "feat_preproc", "feat_preproc_task-b"
    )  # task-a was reused
    p = operation_progress(
        ws, Operation(**{**op.__dict__, "args": {"spec": spec}}) if False else _refetch(ws, op)
    )
    assert [s.state for s in p.steps] == ["reused", "running"]


def _refetch(ws: Workspace, op: Operation) -> Operation:
    with ws.session() as s:
        return s.get(Operation, op.id)  # type: ignore[return-value]


def test_plain_language_activity_from_the_tool_output(tmp_path: Path) -> None:
    assert _phrase(["/x/fsl/bin/mcflirt -in a -out b -plots"]) == "Correcting head motion"
    assert _phrase(["/x/bin/fslmaths a -bptf 37.5 -1 b"]) == "Removing slow signal drifts"
    assert _phrase(["nothing known here"]) is None
    assert _phrase(["Registration"]) == "Aligning the functional image to the T1"
    assert _phrase(["Preprocessing:Stage 2", "/x/bin/fslmaths a b"]) is not None
    assert _shorten("/Users/x/fsl/bin/fslmaths a b c") == "fslmaths a b c"
    assert len(_shorten("tool " + "x" * 400)) <= 160


def test_feat_activity_comes_from_its_own_report(tmp_path: Path) -> None:
    ws, op, sid = setup(tmp_path)
    job = add_job(ws, sid, "feat_preproc", "Running", "feat_preproc", "feat_preproc_task-rest")
    report = ws.abspath(job.run_dir or "") / "work/feat/result.feat/report_log.html"
    report.parent.mkdir(parents=True)
    report.write_text(
        "<pre>\n/fsl/bin/mcflirt -in prefiltered -out mcf\n\n/fsl/bin/susan a 1 2 3 1 1 mean_func 1 b\n"
    )
    now, lines = live_info(ws, job)
    assert now == "Smoothing the data" and lines[-1].startswith("susan ")


def test_fsl_anat_activity_uses_its_own_stage_names(tmp_path: Path) -> None:
    ws, op, sid = setup(tmp_path)
    job = add_job(
        ws,
        sid,
        "fsl_anat",
        "Running",
        None,
        "fsl_anat",
        inputs={"t1": "rawbids/sub-001/anat/sub-001_T1w.nii.gz"},
    )
    logs = ws.abspath(job.run_dir or "") / "logs"
    logs.mkdir(parents=True)
    (logs / "stdout.log").write_text(
        "Fast segmentation\nTanaka-inner-loop-iteration=1 x\nSkull-constrained registration (linear)\n"
    )
    now, lines = live_info(ws, job)
    assert now == "Skull-constrained registration (linear)"


def test_the_route(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    ws = Workspace.open(tmp_path / "workspaces" / ws_id)
    from mrforge.operations import start_operation

    op_id = start_operation(
        ws,
        "pipeline",
        "quick",
        {
            "spec": {
                "name": "quick",
                "subject": "sub-001",
                "steps": [{"id": "a", "step": "fake", "params": {"duration": 0.2}}],
            }
        },
    )
    body = {}
    import time

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        body = client.get(f"/api/workspaces/{ws_id}/operations/{op_id}/progress").json()
        if body["status"] == "Completed":
            break
        time.sleep(0.2)
    assert body["status"] == "Completed" and body["total"] == 1 and body["done"] == 1
    assert [s["state"] for s in body["steps"]] == ["done"]
    assert client.get(f"/api/workspaces/{ws_id}/operations/999/progress").status_code == 404
