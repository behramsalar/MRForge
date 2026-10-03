import json
from pathlib import Path

import pytest
from sqlalchemy import select

from mrforge.models import File, Job, JobStatus, Subject
from mrforge.models import Workspace as WorkspaceRow
from mrforge.workspace import SCHEMA_VERSION, Workspace, WorkspaceError


def test_create_makes_layout_and_metadata(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "demo")
    for sub in ("sourcedata/dicom", "rawbids", "derivatives/mrforge", "reports"):
        assert (ws.root / sub).is_dir()
    meta = json.loads((ws.root / "workspace.json").read_text())
    assert meta["name"] == "demo" and meta["schema_version"] == SCHEMA_VERSION
    assert (ws.root / "db.sqlite").is_file()


def test_reopen_round_trips_data(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "demo", name="My study")
    sid = ws.get_or_create_subject("sub-001")
    with ws.session() as s:
        s.add(File(subject_id=sid, relpath="rawbids/sub-001/anat/sub-001_T1w.nii.gz", kind="T1w"))
        s.add(Job(step_name="fake", step_version="1", subject_id=sid, param_hash="sha256:x"))

    reopened = Workspace.open(tmp_path / "demo")
    assert reopened.name == "My study"
    with reopened.session() as s:
        assert s.scalar(select(WorkspaceRow.name)) == "My study"
        assert s.scalar(select(Subject.label)) == "sub-001"
        assert s.scalar(select(File.kind)) == "T1w"
        job = s.scalars(select(Job)).one()
        assert job.status == JobStatus.QUEUED.value


def test_get_or_create_subject_is_idempotent(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "demo")
    assert ws.get_or_create_subject("sub-001") == ws.get_or_create_subject("sub-001")
    with ws.session() as s:
        assert len(s.scalars(select(Subject)).all()) == 1


def test_create_refuses_existing_or_nonempty(tmp_path: Path) -> None:
    Workspace.create(tmp_path / "demo")
    with pytest.raises(WorkspaceError, match="already exists"):
        Workspace.create(tmp_path / "demo")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "x.txt").write_text("hi")
    with pytest.raises(WorkspaceError, match="not empty"):
        Workspace.create(tmp_path / "other")


def test_open_missing_workspace_is_plain_error(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="No workspace found"):
        Workspace.open(tmp_path)


def test_relpath_round_trip(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "demo")
    p = ws.derivatives_dir / "sub-001" / "bet" / "brain.nii.gz"
    assert ws.relpath(p) == "derivatives/mrforge/sub-001/bet/brain.nii.gz"
    assert ws.abspath(ws.relpath(p)) == p.resolve()


def test_version_2_workspace_is_migrated(tmp_path: Path) -> None:
    """Older workspaces (no Job.error column) open and keep working."""
    import json

    root = tmp_path / "old"
    ws = Workspace.create(root)
    with ws.engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE job DROP COLUMN error")
    ws.engine.dispose()
    meta_path = root / "workspace.json"
    meta = json.loads(meta_path.read_text())
    meta["schema_version"] = 2
    meta_path.write_text(json.dumps(meta))

    reopened = Workspace.open(root)
    assert json.loads(meta_path.read_text())["schema_version"] == SCHEMA_VERSION
    from mrforge.runner.jobs import create_job, get_job
    from mrforge.steps import builtin  # noqa: F401

    jid = create_job(reopened, "fake", "sub-001")
    assert get_job(reopened, jid).error is None
