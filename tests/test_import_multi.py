"""After Stage 7: a folder that holds several subjects' scans becomes one import per scan."""

import tarfile
from pathlib import Path

import pytest
from dicomfactory import SECRET_ID, SECRET_NAME, make_dicom, new_uid

from mrforge.errors import StepError
from mrforge.importing.manifest import list_manifests
from mrforge.importing.scan import scan_group, scan_source
from mrforge.workspace import Workspace


def make_study(root: Path, study_uid: str, t1_number: int = 501, with_bold: bool = True) -> None:
    """One scan: a 3-slice T1 and optionally a 3-slice x 4-volume BOLD run. Every study uses
    the same series numbers, as real sessions do."""
    t1, bold = new_uid(), new_uid()
    for z in range(3):
        make_dicom(
            root / f"t1_{z}.dcm", t1, t1_number, "t1w", position_z=float(z), study_uid=study_uid
        )
    if with_bold:
        for vol in range(4):
            for z in range(3):
                make_dicom(root / f"bold_{vol}_{z}.dcm", bold, 401, "resting",
                           image_type=("ORIGINAL", "PRIMARY", "FMRI", "NONE"), position_z=float(z), study_uid=study_uid)  # fmt: skip


@pytest.fixture
def several(tmp_path: Path) -> Path:
    root = tmp_path / "study"
    for name in ("1", "2", "3"):
        make_study(root / name / "PATIENT" / "20170101", new_uid(), with_bold=name != "2")
    return root


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def test_each_scan_in_a_folder_becomes_its_own_import_with_its_own_subject(
    several: Path, ws: Workspace
) -> None:
    manifests, is_new = scan_group(ws, several)
    assert is_new and len(manifests) == 3
    assert [m.subject for m in manifests] == ["sub-001", "sub-002", "sub-003"]  # folder order
    assert [(m.group.index, m.group.of) for m in manifests if m.group] == [(1, 3), (2, 3), (3, 3)]
    # The same series numbers in every scan do not clash: each import has its own series.
    assert [sorted(s.number or 0 for s in m.series) for m in manifests] == [
        [401, 501],
        [501],
        [401, 501],
    ]
    assert [m.id for m in list_manifests(ws)] == ["import-001", "import-002", "import-003"]


def test_the_files_of_each_scan_are_copied_apart_and_the_source_is_untouched(
    several: Path, ws: Workspace
) -> None:
    before = sorted(p.relative_to(several) for p in several.rglob("*") if p.is_file())
    manifests, _ = scan_group(ws, several)
    assert sorted(p.relative_to(several) for p in several.rglob("*") if p.is_file()) == before
    counts = [sum(1 for p in (ws.root / m.dicom_dir).rglob("*") if p.is_file()) for m in manifests]
    assert counts == [15, 3, 15]  # 3 T1 + 12 BOLD, 3 T1, 3 T1 + 12 BOLD
    assert "2" in {
        part
        for p in (ws.root / manifests[1].dicom_dir).rglob("*")
        if p.is_file()
        for part in p.parts
    }  # structure kept


def test_scanning_the_same_folder_again_finds_the_same_imports(
    several: Path, ws: Workspace
) -> None:
    first, _ = scan_group(ws, several)
    again, is_new = scan_group(ws, several)
    assert not is_new and [m.id for m in again] == [m.id for m in first]
    assert len(list_manifests(ws)) == 3  # nothing was added


def test_nothing_that_identifies_a_study_or_a_person_is_stored(
    tmp_path: Path, ws: Workspace
) -> None:
    root = tmp_path / "ids"
    uids = [new_uid(), new_uid()]
    for i, uid in enumerate(uids):
        make_study(root / str(i), uid)
    manifests, _ = scan_group(ws, root)
    for m, uid in zip(manifests, uids, strict=True):
        text = m.model_dump_json()
        assert SECRET_NAME not in text and SECRET_ID not in text
        assert uid not in text and m.group and len(m.group.study) == 12  # only a short hash
        assert (
            uid not in (ws.root / "imports" / m.id / "manifest.json").read_text()
            if (ws.root / "imports" / m.id / "manifest.json").exists()
            else True
        )


def test_a_source_with_one_scan_still_gives_one_import_exactly_as_before(
    tmp_path: Path, ws: Workspace
) -> None:
    root = tmp_path / "one"
    make_study(root / "A", new_uid())
    manifests, is_new = scan_group(ws, root)
    assert is_new and len(manifests) == 1 and manifests[0].group is None
    assert manifests[0].subject == "sub-001"
    again, is_new2 = scan_group(ws, root)
    assert not is_new2 and again[0].id == manifests[0].id


def test_one_label_cannot_be_given_to_several_scans(several: Path, ws: Workspace) -> None:
    with pytest.raises(StepError) as err:
        scan_group(ws, several, subject="sub-007")
    assert err.value.code == "IMPORT_LABELS_FOR_SEVERAL" and "3 scans" in err.value.message
    assert list_manifests(ws) == []  # nothing was left behind


def test_an_archive_with_several_scans_is_split_the_same_way(
    several: Path, ws: Workspace, tmp_path: Path
) -> None:
    archive = tmp_path / "all.tar.bz2"
    with tarfile.open(archive, "w:bz2") as tf:
        tf.add(several, arcname="all")
    manifests, _ = scan_group(ws, archive)
    assert [m.subject for m in manifests] == ["sub-001", "sub-002", "sub-003"]
    assert all(m.source.kind == "tar" for m in manifests)
    assert not (ws.root / "sourcedata" / "dicom" / ".staging").exists()  # staging is cleaned up


def test_removed_copies_come_back_from_the_original(several: Path, ws: Workspace) -> None:
    import shutil
    from datetime import UTC, datetime

    from mrforge.importing.manifest import save_manifest

    manifests, _ = scan_group(ws, several)
    for m in manifests:  # what removing the DICOM copy does
        shutil.rmtree(ws.root / m.dicom_dir)
        m.dicom_removed = datetime.now(UTC)
        save_manifest(ws, m)
    again, is_new = scan_group(ws, several)
    assert not is_new and all(m.dicom_removed is None for m in again)
    counts = [sum(1 for p in (ws.root / m.dicom_dir).rglob("*") if p.is_file()) for m in again]
    assert counts == [15, 3, 15]  # each copy holds only its own scan again


def test_scan_source_keeps_its_old_meaning_for_a_single_scan(tmp_path: Path, ws: Workspace) -> None:
    root = tmp_path / "x"
    make_study(root, new_uid())
    manifest, is_new = scan_source(ws, root)
    assert is_new and manifest.subject == "sub-001"
