"""The option to remove the workspace's copy of the original DICOM files (kept by default)."""

import hashlib
import os
import shutil
from pathlib import Path

import pytest
from conftest import Fake
from dicomfactory import make_session
from typer.testing import CliRunner

from mrforge.cli import app
from mrforge.errors import StepError
from mrforge.importing import scan as scan_module
from mrforge.importing.classify import load_rules
from mrforge.importing.convert import convert_import
from mrforge.importing.manifest import load_manifest
from mrforge.importing.models import CommandRecord, ImportManifest
from mrforge.importing.organize import organize
from mrforge.importing.scan import scan_source
from mrforge.importing.sourcedata import removal_plan, remove_dicom
from mrforge.workspace import Workspace

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_sidecar_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scan_module,
        "sidecar_pass",
        lambda d, s: (CommandRecord(argv=["dcm2niix"], return_code=0), "vTEST", []),
    )


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "original_session"
    make_session(path)
    return path


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "study")


@pytest.fixture
def scanned(ws: Workspace, source: Path, fake: Fake) -> ImportManifest:
    """Scanned (series 2 and 6 are set to import, 19 waits for a task)."""
    fake.set(2, images=[{"suffix": "", "shape": [4, 4, 3]}])
    fake.set(6, images=[{"suffix": "", "shape": [4, 4, 3, 4]}])
    return scan_source(ws, source, subject="sub-001")[0]


@pytest.fixture
def imported(ws: Workspace, scanned: ImportManifest) -> ImportManifest:
    rules = load_rules()
    assert convert_import(ws, scanned, rules).failed == []
    organize(ws, scanned, rules)
    return scanned


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            digest.update(
                f"{p.relative_to(root)}:{hashlib.sha256(p.read_bytes()).hexdigest()}".encode()
            )
    return digest.hexdigest()


def rawbids_files(ws: Workspace) -> dict[str, str]:
    root = ws.root / "rawbids"
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


# -- when removal is allowed --------------------------------------------------------------------------------------


def test_the_dicom_copy_is_kept_by_default(ws: Workspace, imported: ImportManifest) -> None:
    assert (ws.root / imported.dicom_dir).is_dir() and imported.dicom_removed is None


def test_removal_is_refused_until_everything_to_import_is_in_rawbids(
    ws: Workspace, scanned: ImportManifest
) -> None:
    rules = load_rules()
    with pytest.raises(StepError) as info:  # nothing converted yet
        remove_dicom(ws, scanned, rules)
    assert info.value.code == "DICOM_REMOVE_NOT_SAFE" and "series 2" in info.value.message
    convert_import(ws, scanned, rules)
    with pytest.raises(StepError) as info:  # converted, but not yet in rawbids/
        remove_dicom(ws, scanned, rules)
    assert info.value.code == "DICOM_REMOVE_NOT_SAFE"
    assert "mrforge import run" in info.value.suggested_action
    assert (ws.root / scanned.dicom_dir).is_dir()  # nothing was deleted


def test_removal_is_refused_when_a_file_in_rawbids_is_missing_or_changed(
    ws: Workspace, imported: ImportManifest
) -> None:
    rules = load_rules()
    target = ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    target.chmod(0o644)
    target.write_bytes(b"changed")
    with pytest.raises(StepError) as info:
        remove_dicom(ws, imported, rules)
    assert info.value.code == "DICOM_REMOVE_NOT_SAFE" and (ws.root / imported.dicom_dir).is_dir()


def test_nifti_and_bids_imports_have_no_dicom_copy(ws: Workspace, tmp_path: Path) -> None:
    from test_import_existing import make_nifti

    from mrforge.importing.existing import import_nifti

    rules = load_rules()
    result = import_nifti(ws, [make_nifti(tmp_path / "t1.nii.gz")], "T1w", rules)
    with pytest.raises(StepError) as info:
        remove_dicom(ws, result.manifest, rules)
    assert info.value.code == "DICOM_NOT_APPLICABLE"


# -- what removal does and does not touch ----------------------------------------------------------------------------


def test_removal_deletes_only_the_dicom_copy(
    ws: Workspace, imported: ImportManifest, source: Path
) -> None:
    rules = load_rules()
    original, raw_before = tree_hash(source), rawbids_files(ws)
    plan = removal_plan(ws, imported, rules)
    assert plan.size_bytes > 0 and plan.not_safe == []
    assert any("series 19" in s for s in plan.only_in_dicom)  # waiting for a task: only in DICOM
    remove_dicom(ws, imported, rules)
    assert not (ws.root / imported.dicom_dir).exists()
    assert imported.dicom_removed is not None
    assert load_manifest(ws).dicom_removed is not None  # saved
    assert rawbids_files(ws) == raw_before  # every imported file is unchanged
    assert tree_hash(source) == original  # the user's own originals are never touched
    assert (ws.root / "imports/import-001/converted").is_dir()  # the series table etc. stay
    assert [s.number for s in load_manifest(ws).series] == [2, 6, 19]


def test_the_import_still_works_without_the_dicom_files(
    ws: Workspace, imported: ImportManifest
) -> None:
    rules = load_rules()
    remove_dicom(ws, imported, rules)
    summary = convert_import(ws, imported, rules)  # finished series need no DICOM
    assert (summary.converted, summary.up_to_date) == ([], [2, 6])
    assert organize(ws, imported, rules).written == []
    with pytest.raises(StepError) as info:
        remove_dicom(ws, imported, rules)
    assert info.value.code == "DICOM_ALREADY_REMOVED"


def test_anything_that_needs_the_dicom_files_says_how_to_get_them_back(
    ws: Workspace, imported: ImportManifest
) -> None:
    rules = load_rules()
    remove_dicom(ws, imported, rules)
    with pytest.raises(StepError) as info:
        convert_import(ws, imported, rules, force=True)
    err = info.value
    assert err.code == "DICOM_REMOVED" and "2, 6" in err.message
    assert (
        "mrforge import scan" in err.suggested_action
        and "--subject sub-001" in err.suggested_action
    )


def test_scanning_the_original_again_restores_the_copy(
    ws: Workspace, imported: ImportManifest, source: Path, fake: Fake
) -> None:
    rules = load_rules()
    remove_dicom(ws, imported, rules)
    manifest, is_new = scan_source(ws, source, subject="sub-001")
    assert not is_new and manifest.id == imported.id and manifest.dicom_removed is None
    assert (ws.root / manifest.dicom_dir).is_dir()
    assert convert_import(ws, manifest, rules, force=True).converted == [2, 6]  # usable again


def test_cli_scan_says_when_it_restored_the_copy(
    ws: Workspace, imported: ImportManifest, source: Path
) -> None:
    w = str(ws.root)
    runner.invoke(app, ["import", "remove-dicom", "-w", w, "--yes"])
    r = runner.invoke(app, ["import", "scan", str(source), "-w", w, "--subject", "sub-001"])
    assert r.exit_code == 0 and "restored from the original" in r.output
    assert (ws.root / imported.dicom_dir).is_dir()
    again = runner.invoke(app, ["import", "scan", str(source), "-w", w, "--subject", "sub-001"])
    assert "nothing was copied again" in again.output


def test_links_between_imports_and_rawbids_cannot_hurt_the_dataset(
    ws: Workspace, imported: ImportManifest
) -> None:
    """The files in rawbids/ are hard links of the converted ones. Deleting the converted
    folder and the DICOM copy leaves rawbids/ complete and unchanged."""
    raw = ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    before = rawbids_files(ws)
    assert os.stat(raw).st_nlink == 2
    shutil.rmtree(ws.root / "imports/import-001/converted")
    shutil.rmtree(ws.root / imported.dicom_dir)
    assert os.stat(raw).st_nlink == 1 and rawbids_files(ws) == before


# -- CLI ----------------------------------------------------------------------------------------------------------------


def test_cli_asks_first_and_explains_what_is_lost(ws: Workspace, imported: ImportManifest) -> None:
    w = str(ws.root)
    declined = runner.invoke(app, ["import", "remove-dicom", "-w", w], input="n\n")
    assert declined.exit_code == 1 and "Nothing was deleted" in declined.output
    assert "Delete the DICOM copy?" in declined.output
    assert "skipped or are undecided" in declined.output and "series 19" in declined.output
    assert "original source again" in declined.output
    assert (ws.root / imported.dicom_dir).is_dir()
    accepted = runner.invoke(app, ["import", "remove-dicom", "-w", w], input="y\n")
    assert accepted.exit_code == 0 and "Deleted." in accepted.output and "freed" in accepted.output
    assert not (ws.root / imported.dicom_dir).exists()
    shown = runner.invoke(app, ["import", "show", "-w", w]).output
    assert "copy of the DICOM files was removed" in shown
    again = runner.invoke(app, ["import", "remove-dicom", "-w", w, "--yes"])
    assert again.exit_code == 1 and "already removed" in again.output


def test_cli_refuses_in_plain_language_when_not_safe(
    ws: Workspace, scanned: ImportManifest
) -> None:
    r = runner.invoke(app, ["import", "remove-dicom", "-w", str(ws.root), "--yes"])
    assert r.exit_code == 1 and "DICOM_REMOVE_NOT_SAFE" in r.output
    assert "Traceback" not in r.output and (ws.root / scanned.dicom_dir).is_dir()


def test_cli_run_can_remove_the_copy_afterwards(ws: Workspace, scanned: ImportManifest) -> None:
    w = str(ws.root)
    kept = runner.invoke(app, ["import", "run", "-w", w])  # default: the copy is kept
    assert kept.exit_code == 0 and (ws.root / scanned.dicom_dir).is_dir()
    r = runner.invoke(app, ["import", "run", "-w", w, "--remove-dicom", "--yes"])
    assert r.exit_code == 0, r.output
    assert "Deleted." in r.output and not (ws.root / scanned.dicom_dir).exists()
    assert (ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz").is_file()


def test_cli_run_does_not_remove_anything_when_the_import_fails(
    ws: Workspace, scanned: ImportManifest, fake: Fake
) -> None:
    fake.set(6, mode="fail")
    r = runner.invoke(app, ["import", "run", "-w", str(ws.root), "--remove-dicom", "--yes"])
    assert r.exit_code == 1 and "Conversion failed" in r.output
    assert (ws.root / scanned.dicom_dir).is_dir()
