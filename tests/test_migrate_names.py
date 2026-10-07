"""Stage 6.5: results made before the new naming are renamed, not recomputed."""

import json
from datetime import UTC, datetime
from pathlib import Path

from mrforge.migrate_names import migrate, needs_migration
from mrforge.models import File, Job
from mrforge.provenance import FileRecord, Provenance, StepRef, write_provenance
from mrforge.workspace import Workspace

F = "derivatives/mrforge/sub-001/func"
CLEANED = f"{F}/sub-001_task-rest_desc-cleaned_bold.nii.gz"
MNI_OLD = f"{F}/sub-001_task-rest_space-MNI152NLin6Asym_desc-preproc_bold.nii.gz"
PREPROC = f"{F}/sub-001_task-rest_desc-preproc_bold.nii.gz"


def record(ws: Workspace, step: str, folder: str, inputs: list[str], outputs: list[str]) -> Path:
    run = ws.root / F / "_runs" / folder
    prov = Provenance(
        step=StepRef(name=step, version="1"),
        job_id=1,
        subject="sub-001",
        parameters={},
        parameter_hash="p",
        inputs=[FileRecord(path=p, sha256="a" * 64, size=1) for p in inputs],
        outputs=[FileRecord(path=p, sha256="b" * 64, size=1) for p in outputs],
        commands=[],
        tool_versions={},
        started=datetime.now(UTC),
        finished=datetime.now(UTC),
        status="Completed",
    )
    write_provenance(run, prov)
    return run


def make(tmp_path: Path, denoised_input: bool = True) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    ws.get_or_create_subject("sub-001")
    for rel in (CLEANED, MNI_OLD, PREPROC):
        (ws.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws.root / rel).write_text("data")
    record(ws, "regfilt", "regfilt_task-rest", [PREPROC], [CLEANED])
    record(
        ws,
        "func_to_mni",
        "func_to_mni_task-rest",
        [CLEANED if denoised_input else PREPROC],
        [MNI_OLD],
    )
    sid = ws.get_or_create_subject("sub-001")
    with ws.session() as s:
        s.add(File(subject_id=sid, relpath=CLEANED, kind="regfilt"))
        s.add(File(subject_id=sid, relpath=MNI_OLD, kind="func_to_mni"))
        s.add(Job(step_name="func_to_mni", step_version="1", subject_id=sid, param_hash="x",
                  status="Completed", inputs={"bold": CLEANED}, run_dir=f"{F}/_runs/func_to_mni_task-rest"))  # fmt: skip
    meta = json.loads((ws.root / "workspace.json").read_text())
    meta.pop("names_version")  # a workspace made before the new naming
    (ws.root / "workspace.json").write_text(json.dumps(meta))
    return ws


def test_a_dry_run_lists_the_changes_and_touches_nothing(tmp_path: Path) -> None:
    ws = make(tmp_path)
    plan = migrate(ws, dry_run=True)
    assert plan.renames == {
        CLEANED: CLEANED.replace("desc-cleaned", "desc-denoised"),
        MNI_OLD: MNI_OLD.replace("desc-preproc", "desc-denoised"),
    }
    assert (ws.root / CLEANED).exists() and needs_migration(ws.root)


def test_files_records_and_database_are_brought_to_the_new_names(tmp_path: Path) -> None:
    ws = make(tmp_path)
    migrate(ws)
    new_clean = CLEANED.replace("desc-cleaned", "desc-denoised")
    new_mni = MNI_OLD.replace("desc-preproc", "desc-denoised")
    assert (ws.root / new_clean).exists() and not (ws.root / CLEANED).exists()
    assert (ws.root / new_mni).exists() and (
        ws.root / PREPROC
    ).exists()  # the FEAT result keeps its name
    prov = Provenance.model_validate_json(
        (ws.root / F / "_runs/func_to_mni_task-rest/provenance.json").read_text()
    )
    assert (
        prov.step.version == "2"
        and prov.inputs[0].path == new_clean
        and prov.outputs[0].path == new_mni
    )
    with ws.session() as s:
        assert {f.relpath for f in s.query(File)} == {new_clean, new_mni}
        job = s.query(Job).one()
        assert job.step_version == "2" and job.inputs == {"bold": new_clean}
    assert not needs_migration(ws.root)
    assert (ws.root / "db.sqlite.before-naming").exists()


def test_a_standard_space_result_made_from_preprocessed_data_keeps_its_name(tmp_path: Path) -> None:
    ws = make(tmp_path, denoised_input=False)
    migrate(ws)
    assert (ws.root / MNI_OLD).exists()  # still desc-preproc: it never came from denoised data
    prov = Provenance.model_validate_json(
        (ws.root / F / "_runs/func_to_mni_task-rest/provenance.json").read_text()
    )
    assert prov.step.version == "2"  # content identical, so the record stays valid


def test_running_it_twice_changes_nothing_more(tmp_path: Path) -> None:
    ws = make(tmp_path)
    migrate(ws)
    again = migrate(ws, dry_run=True)
    assert again.renames == {} and again.records == []
