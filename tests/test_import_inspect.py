"""inspect_source: what is in the chosen folder, decided before anything is copied."""

import tarfile
import zipfile
from pathlib import Path

import pytest

from mrforge.errors import StepError
from mrforge.importing.inspect import inspect_source


def touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def make_zip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a/1.dcm", b"x")


def test_several_archives_in_a_folder(tmp_path: Path) -> None:
    src = tmp_path / "in"
    make_zip(src / "s1.zip")
    make_zip(src / "sub" / "s2.zip")
    with tarfile.open(src / "s3.tar.gz", "w:gz") as tf:
        tf.add(touch(tmp_path / "elsewhere" / "f.dcm"), arcname="f.dcm")
    touch(src / "__MACOSX" / "._s1.zip")
    touch(src / "notes.txt")
    plan = inspect_source(src)
    assert plan.kind == "archives"
    assert sorted(plan.archives) == ["s1.zip", "s3.tar.gz", "sub/s2.zip"]
    assert plan.summary.startswith("Found 3 archives")


def test_one_archive_is_dicom_as_before(tmp_path: Path) -> None:
    make_zip(tmp_path / "scan.zip")
    assert inspect_source(tmp_path / "scan.zip").kind == "dicom"


def test_a_dicom_folder(tmp_path: Path) -> None:
    for i in range(3):
        touch(tmp_path / "PATIENT" / "20170101" / f"IM{i}")
    touch(tmp_path / "DICOMDIR")
    assert inspect_source(tmp_path).kind == "dicom"


def test_nifti_files_are_grouped_by_folder_and_by_sub_label(tmp_path: Path) -> None:
    touch(tmp_path / "anna" / "t1.nii.gz")
    touch(tmp_path / "anna" / "rest.nii.gz")
    touch(tmp_path / "anna" / "rest.json")
    touch(tmp_path / "ben" / "t1.nii")
    touch(tmp_path / "flat" / "sub-07_T1w.nii.gz")
    touch(tmp_path / "flat" / "sub-08_T1w.nii.gz")
    plan = inspect_source(tmp_path)
    assert plan.kind == "nifti"
    groups = {g.label: sorted(g.files) for g in plan.nifti}
    assert groups == {
        "anna": ["anna/rest.nii.gz", "anna/t1.nii.gz"],
        "ben": ["ben/t1.nii"],
        "sub-07": ["flat/sub-07_T1w.nii.gz"],
        "sub-08": ["flat/sub-08_T1w.nii.gz"],
    }
    assert "5 NIfTI files for 4 subjects" in plan.summary


def test_a_bids_dataset(tmp_path: Path) -> None:
    touch(tmp_path / "dataset_description.json", b"{}")
    touch(tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    assert inspect_source(tmp_path).kind == "bids"


def test_a_dicom_folder_with_stray_files_is_still_dicom(tmp_path: Path) -> None:
    for i in range(3):
        touch(tmp_path / f"IM{i}")
    make_zip(tmp_path / "backup.zip")
    plan = inspect_source(tmp_path)
    assert plan.kind == "dicom" and "Not imported: 1 archive" in plan.summary


def test_mixed_kinds_are_explained_not_guessed(tmp_path: Path) -> None:
    make_zip(tmp_path / "s1.zip")
    touch(tmp_path / "t1.nii.gz")
    with pytest.raises(StepError) as info:
        inspect_source(tmp_path)
    assert info.value.code == "IMPORT_SOURCE_MIXED"
    assert "1 archive" in info.value.message and "1 NIfTI file" in info.value.message


def test_empty_and_wrong_sources(tmp_path: Path) -> None:
    touch(tmp_path / "readme.txt")
    with pytest.raises(StepError) as info:
        inspect_source(tmp_path)
    assert info.value.code == "IMPORT_SOURCE_EMPTY"
    with pytest.raises(StepError) as missing:
        inspect_source(tmp_path / "nope")
    assert missing.value.code == "SOURCE_NOT_FOUND"
    with pytest.raises(StepError) as notarchive:
        inspect_source(tmp_path / "readme.txt")
    assert notarchive.value.code == "IMPORT_SOURCE_INVALID"
