"""Sorted subfolders of the func folder (layout.py) and the migration of flat workspaces."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mrforge import migrate_layout
from mrforge.errors import StepError
from mrforge.layout import placed, subfolder_for
from mrforge.models import File, Job
from mrforge.provenance import FileRecord, Provenance, StepRef, write_provenance
from mrforge.runner.jobs import create_job
from mrforge.steps import builtin  # noqa: F401
from mrforge.workspace import Workspace

S = "sub-001_task-rest"
CASES = [
    # results people open stay where they are
    (f"{S}_desc-preproc_bold.nii.gz", ""),
    (f"{S}_space-MNI152NLin6Asym_desc-denoised_bold.nii.gz", ""),
    (f"{S}_desc-brain_mask.nii.gz", ""),
    (f"{S}_desc-feat_boldref.nii.gz", ""),
    (f"{S}_space-T1w_desc-feat_boldref.nii.gz", ""),
    # quality control
    (f"{S}_desc-registration_qc.png", "qc"),
    (f"{S}_desc-registration_qc_slices", "qc"),
    (f"{S}_desc-metrics_qc.json", "qc"),
    (f"{S}_desc-motion_timeseries.tsv", "qc"),
    # components and noise removal
    (f"{S}_desc-melodic_components.nii.gz", "ica"),
    (f"{S}_desc-melodic_mixing.txt", "ica"),
    (f"{S}_desc-aroma_classification.json", "ica"),
    (f"{S}_desc-ica_labels.json", "ica"),
    (f"{S}_desc-icalabels_decision.json", "ica"),
    (f"{S}_desc-icalabels_draft.json", "ica"),
    (f"{S}_desc-variance_cleaning.png", "ica"),
    (f"{S}_desc-metrics_cleaning.json", "ica"),
    (f"{S}_bold.ica", "ica"),
    # transforms and tool folders
    (f"{S}_from-boldref_to-T1w_mode-image_desc-affine_xfm.mat", "transforms"),
    (f"{S}_bold.feat", "feat"),
    # connectivity: one folder per atlas
    (f"{S}_space-MNI152NLin6Asym_seg-aal3v2_timeseries.tsv", "connectivity/aal3v2"),
    (f"{S}_space-MNI152NLin6Asym_seg-schaefer100n7_stat-fisherz_relmat.txt",
     "connectivity/schaefer100n7"),
]  # fmt: skip


@pytest.mark.parametrize(("name", "folder"), CASES)
def test_where_a_result_goes(name: str, folder: str) -> None:
    assert subfolder_for(name, "func") == folder
    assert subfolder_for(f"derivatives/x/{name}", "func") == folder  # directories are ignored
    assert placed(name, "func") == (f"{folder}/{name}" if folder else name)


def test_other_datatypes_stay_flat() -> None:
    for datatype in ("anat", "dwi", "fmap"):
        assert subfolder_for(f"{S}_desc-registration_qc.png", datatype) == ""


# -- migration of a flat workspace ---------------------------------------------------------

F = "derivatives/mrforge/sub-001/func"
PREPROC = f"{F}/{S}_desc-preproc_bold.nii.gz"
QC_PNG = f"{F}/{S}_desc-registration_qc.png"
SLICES = f"{F}/{S}_desc-registration_qc_slices"
FEAT = f"{F}/{S}_bold.feat"
XFM = f"{F}/{S}_from-boldref_to-T1w_mode-image_desc-affine_xfm.mat"
OLD = [QC_PNG, SLICES, FEAT, XFM]


def flat_workspace(tmp_path: Path) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    meta = json.loads((ws.root / "workspace.json").read_text())
    meta.pop("layout_version")  # as made before the sorted layout
    (ws.root / "workspace.json").write_text(json.dumps(meta))
    sid = ws.get_or_create_subject("sub-001")
    (ws.root / F).mkdir(parents=True)
    for rel in (PREPROC, QC_PNG, XFM):
        (ws.root / rel).write_text("data")
    (ws.root / SLICES).mkdir()
    (ws.root / SLICES / "functional_axial0.png").write_text("x")
    (ws.root / FEAT / "mc").mkdir(parents=True)
    (ws.root / FEAT / "mc" / "prefiltered_func_data_mcf.par").write_text("0 0 0 0 0 0")
    run = ws.root / F / "_runs" / "func_qc_task-rest"
    write_provenance(
        run,
        Provenance(
            step=StepRef(name="func_qc", version="2"),
            job_id=1,
            subject="sub-001",
            parameters={},
            parameter_hash="p",
            inputs=[FileRecord(path=XFM, sha256="a" * 64)],
            outputs=[FileRecord(path=QC_PNG, sha256="b" * 64)],
            commands=[],
            tool_versions={},
            started=datetime.now(UTC),
            finished=datetime.now(UTC),
            status="Completed",
            qc=[{"name": "q", "kind": "image",
                 "slices": [{"plane": "axial", "position": 0.5, "layer": "functional",
                             "path": f"{S}_desc-registration_qc_slices/functional_axial0.png"}]}],  # type: ignore[list-item]
        ),
    )  # fmt: skip
    with ws.session() as s:
        s.add(File(subject_id=sid, relpath=QC_PNG, kind="func_qc"))
        s.add(File(subject_id=sid, relpath=XFM, kind="feat_preproc"))
        s.add(Job(step_name="func_qc", step_version="2", subject_id=sid, param_hash="x",
                  status="Completed", inputs={"transform": XFM}))  # fmt: skip
    return ws


def test_a_flat_workspace_is_sorted_and_its_records_follow(tmp_path: Path) -> None:
    ws = flat_workspace(tmp_path)
    assert migrate_layout.needs_migration(ws.root)
    dry = migrate_layout.migrate(ws, dry_run=True)
    assert set(dry.renames) == set(OLD) and (ws.root / QC_PNG).exists()  # nothing touched
    migrate_layout.migrate(ws)
    new = {old: old.replace("/func/", "/func/" + sub + "/")
           for old, sub in zip(OLD, ("qc", "qc", "feat", "transforms"), strict=True)}  # fmt: skip
    for old, moved in new.items():
        assert not (ws.root / old).exists() and (ws.root / moved).exists()
    assert (ws.root / PREPROC).exists()  # the main result stays
    assert (ws.root / new[FEAT] / "mc" / "prefiltered_func_data_mcf.par").exists()
    text = (ws.root / F / "_runs" / "func_qc_task-rest" / "provenance.json").read_text()
    assert new[XFM] in text and new[QC_PNG] in text and f'"{QC_PNG}"' not in text
    assert f'"qc/{S}_desc-registration_qc_slices/functional_axial0.png"' in text  # folder-relative
    with ws.session() as s:
        assert {f.relpath for f in s.query(File)} == {new[QC_PNG], new[XFM]}
        assert s.query(Job).one().inputs == {"transform": new[XFM]}
    assert not migrate_layout.needs_migration(ws.root)
    assert not migrate_layout.migrate(ws).renames  # a second run changes nothing
    assert (ws.root / "db.sqlite.before-layout").exists()


def test_recorded_hashes_follow_a_result_file_whose_paths_were_rewritten(tmp_path: Path) -> None:
    import hashlib

    ws = flat_workspace(tmp_path)
    summary = f"{F}/{S}_desc-melodic_components.json"  # lists a picture by workspace path
    (ws.root / summary).write_text(json.dumps({"planes": QC_PNG}))
    old_hash = hashlib.sha256((ws.root / summary).read_bytes()).hexdigest()
    record = ws.root / F / "_runs" / "func_qc_task-rest" / "provenance.json"
    record.write_text(record.read_text().replace("b" * 64, old_hash))
    migrate_layout.migrate(ws)
    moved = ws.root / F / "ica" / Path(summary).name
    new_hash = hashlib.sha256(moved.read_bytes()).hexdigest()
    assert json.loads(moved.read_text())["planes"] == f"{F}/qc/{Path(QC_PNG).name}"
    assert new_hash != old_hash and new_hash in record.read_text()
    assert old_hash not in record.read_text()


def test_an_interrupted_migration_is_finished_by_the_next_run(tmp_path: Path) -> None:
    ws = flat_workspace(tmp_path)
    plan = migrate_layout.plan_migration(ws)
    # simulate: the plan was written and one file moved, then the process died
    (ws.root / migrate_layout.MARKER).write_text(json.dumps({"renames": plan.renames, "local": {}}))
    (ws.root / F / "transforms").mkdir()
    (ws.root / XFM).rename(ws.root / F / "transforms" / Path(XFM).name)
    migrate_layout.migrate(ws)
    text = (ws.root / F / "_runs" / "func_qc_task-rest" / "provenance.json").read_text()
    assert f"{F}/transforms/{Path(XFM).name}" in text


def test_work_is_refused_until_a_flat_workspace_is_migrated(tmp_path: Path) -> None:
    ws = flat_workspace(tmp_path)
    with pytest.raises(StepError) as err:
        create_job(ws, "fake", "sub-001", {}, {})
    assert err.value.code == "WORKSPACE_LAYOUT_OLD"
    migrate_layout.migrate(ws)
    assert create_job(ws, "fake", "sub-001", {}, {})  # accepted now


def test_an_empty_old_workspace_just_gets_the_version(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    meta = json.loads((ws.root / "workspace.json").read_text())
    meta.pop("layout_version")
    (ws.root / "workspace.json").write_text(json.dumps(meta))
    assert create_job(ws, "fake", "sub-001", {}, {})
    assert not migrate_layout.needs_migration(ws.root)
