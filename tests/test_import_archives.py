"""Several archives in one folder become one group of scans; one bad archive does not stop the rest."""

import shutil
from pathlib import Path

import pytest
from dicomfactory import make_dicom, new_uid
from test_import_multi import make_study

from mrforge.errors import StepError
from mrforge.importing.archives import scan_archives
from mrforge.importing.inspect import inspect_source
from mrforge.importing.manifest import list_manifests
from mrforge.operations import _scan
from mrforge.workspace import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def make_archive(folder: Path, name: str) -> None:
    study = folder.parent / "_build" / name
    make_study(study / "PATIENT" / "20170101", new_uid())
    # real archives differ in size; identical synthetic ones would look like the same source
    (study / "notes.txt").write_text(name * 7)
    shutil.make_archive(str(folder / name), "zip", study)
    shutil.rmtree(study)


@pytest.fixture
def several(tmp_path: Path) -> Path:
    folder = tmp_path / "zips"
    folder.mkdir()
    for name in ("anna", "ben", "carla"):
        make_archive(folder, name)
    return folder


def test_every_archive_becomes_a_scan_in_one_group(ws: Workspace, several: Path) -> None:
    plan = inspect_source(several)
    manifests, failed, is_new = scan_archives(ws, several, plan.archives)
    assert is_new and not failed
    assert [m.subject for m in manifests] == ["sub-001", "sub-002", "sub-003"]
    assert {m.group.source for m in manifests if m.group} == {manifests[0].group.source}  # type: ignore[union-attr]
    assert [(m.group.index, m.group.of) for m in manifests if m.group] == [(1, 3), (2, 3), (3, 3)]
    assert all(len(m.series) == 2 for m in manifests)  # a T1 and a BOLD each


def test_scanning_the_folder_again_adds_nothing(ws: Workspace, several: Path) -> None:
    plan = inspect_source(several)
    first, _, _ = scan_archives(ws, several, plan.archives)
    again, failed, is_new = scan_archives(ws, several, plan.archives)
    assert not is_new and not failed
    assert [m.id for m in again] == [m.id for m in first]
    assert len(list_manifests(ws)) == 3


def test_a_bad_archive_is_reported_and_the_others_are_scanned(ws: Workspace, several: Path) -> None:
    (several / "broken.zip").write_bytes(b"not a zip at all")  # not recognised as an archive
    make_archive(several, "empty_one")
    empty = several / "empty_one.zip"
    empty.unlink()
    import zipfile

    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("readme.txt", "no scans in here")
    plan = inspect_source(several)
    assert "empty_one.zip" in plan.archives
    manifests, failed, _ = scan_archives(ws, several, plan.archives)
    assert len(manifests) == 3
    assert [name for name, _ in failed] == ["broken.zip", "empty_one.zip"]
    assert all("No scanner images" in m or "ZIP" in m or "archive" in m.lower() for _, m in failed)


def test_nothing_readable_is_one_clear_error(ws: Workspace, tmp_path: Path) -> None:
    import zipfile

    folder = tmp_path / "bad"
    folder.mkdir()
    for name in ("a", "b"):
        with zipfile.ZipFile(folder / f"{name}.zip", "w") as zf:
            zf.writestr("readme.txt", "x")
    plan = inspect_source(folder)
    with pytest.raises(StepError) as info:
        scan_archives(ws, folder, plan.archives)
    assert info.value.code == "IMPORT_NO_ARCHIVE_READABLE"
    assert list_manifests(ws) == []


def test_the_scan_operation_reports_everything(ws: Workspace, several: Path) -> None:
    lines: list[str] = []
    result = _scan(ws, {"source": str(several), "started_by": "Ayse"}, lines.append)
    assert result["group_size"] == 3 and result["source_kind"] == "archives"
    assert result["failed_sources"] == []
    assert all(m.created_by == "Ayse" for m in list_manifests(ws))
    assert any("Archive 2 of 3" in line for line in lines)


def test_a_single_dicom_folder_still_goes_the_old_way(ws: Workspace, tmp_path: Path) -> None:
    root = tmp_path / "one"
    make_study(root, new_uid())
    result = _scan(ws, {"source": str(root)}, lambda _m: None)
    assert result["group_size"] == 1 and result["source_kind"] == "dicom"
    _ = make_dicom  # (imported to keep the factory in this module's namespace for readers)
