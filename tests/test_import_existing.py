"""Stage 2f: importing existing NIfTI files and existing BIDS datasets (no conversion)."""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import nibabel
import numpy as np
import pytest
from sqlalchemy import select
from test_import_organize import fabricate, new_manifest
from typer.testing import CliRunner

from mrforge.cli import app
from mrforge.errors import StepError
from mrforge.hashing import sha256_of
from mrforge.importing import existing as existing_module
from mrforge.importing.bids_validate import find_validator, validate_dataset
from mrforge.importing.classify import RuleSet, load_rules
from mrforge.importing.existing import (
    import_bids,
    import_nifti,
    merge_participants,
)
from mrforge.importing.manifest import list_manifests
from mrforge.importing.organize import organize
from mrforge.models import File
from mrforge.workspace import Workspace

runner = CliRunner()
PRIVATE = {"StationName": "AWP1", "StudyDescription": "some clinic", "PatientName": "Doe^J"}

try:
    find_validator()
    HAVE_VALIDATOR = True
except StepError:
    HAVE_VALIDATOR = False
needs_validator = pytest.mark.skipif(
    not HAVE_VALIDATOR, reason="the BIDS validator is not installed"
)


@pytest.fixture(scope="module")
def rules() -> RuleSet:
    return load_rules()


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "study")


def make_nifti(
    path: Path, shape: tuple[int, ...] = (8, 8, 4), tr: float | None = None, unit: str = "sec",
    seed: int = 1,
) -> Path:  # fmt: skip
    data = np.random.default_rng(seed).integers(0, 1000, size=shape, dtype="int16")
    image = nibabel.Nifti1Image(data, np.eye(4))
    image.header.set_xyzt_units("mm", unit)
    if tr is not None and len(shape) == 4:
        image.header.set_zooms((1.0, 1.0, 1.0, tr))
    path.parent.mkdir(parents=True, exist_ok=True)
    nibabel.save(image, str(path))
    return path


def tree(ws: Workspace) -> list[str]:
    root = ws.root / "rawbids"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def sidecar(ws: Workspace, rel: str) -> dict[str, object]:
    return json.loads((ws.root / "rawbids" / rel).read_text())  # type: ignore[no-any-return]


# -- NIfTI files: what is written ----------------------------------------------------------------


def test_a_t1_becomes_a_bids_file_and_the_original_is_untouched(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    src = make_nifti(tmp_path / "Zzyzx_Quentin_t1.nii.gz")
    before = (src.read_bytes(), src.stat().st_mtime_ns, src.stat().st_mode)
    result = import_nifti(ws, [src], "T1w", rules)
    assert result.is_new and result.manifest.subject == "sub-001"
    assert tree(ws) == [
        "README", "dataset_description.json", "participants.tsv",
        "sub-001/anat/sub-001_T1w.json", "sub-001/anat/sub-001_T1w.nii.gz",
    ]  # fmt: skip
    assert (src.read_bytes(), src.stat().st_mtime_ns, src.stat().st_mode) == before
    out = ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    assert out.read_bytes() == src.read_bytes()  # a .nii.gz is copied as it is
    assert not out.stat().st_mode & stat.S_IWUSR  # read-only in rawbids...
    assert not os.path.samefile(src, out)  # ...and never a link to the user's file
    assert src.stat().st_mode & stat.S_IWUSR  # so the user's original stays writable


def test_the_users_file_name_is_never_stored(ws: Workspace, tmp_path: Path, rules: RuleSet) -> None:
    src = make_nifti(tmp_path / "Zzyzx_Quentin_t1.nii.gz")
    import_nifti(ws, [src], "T1w", rules)
    stored = "".join(p.read_text() for p in (ws.root / "imports").rglob("*.json"))
    assert "Zzyzx" not in stored and "Quentin" not in stored


def test_an_uncompressed_nifti_is_compressed_the_same_way_every_time(
    tmp_path: Path, rules: RuleSet
) -> None:
    src = make_nifti(tmp_path / "scan.nii")
    outputs = []
    for name in ("one", "two"):
        w = Workspace.create(tmp_path / name)
        import_nifti(w, [src], "T2w", rules)
        outputs.append((w.root / "rawbids/sub-001/anat/sub-001_T2w.nii.gz").read_bytes())
    assert outputs[0] == outputs[1]
    assert nibabel.load(w.root / "rawbids/sub-001/anat/sub-001_T2w.nii.gz").shape == (8, 8, 4)


def test_sidecar_privacy_filter_applies_to_existing_sidecars(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    src = make_nifti(tmp_path / "t1.nii.gz")
    (tmp_path / "t1.json").write_text(json.dumps({"FlipAngle": 8, **PRIVATE}))
    import_nifti(ws, [src], "T1w", rules)
    data = sidecar(ws, "sub-001/anat/sub-001_T1w.json")
    assert data == {"FlipAngle": 8}  # what analysis needs stays; the rest is removed


def test_files_are_registered_in_the_database(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    import_nifti(ws, [make_nifti(tmp_path / "t1.nii.gz")], "T1w", rules)
    with ws.session() as s:
        kinds = dict(s.execute(select(File.relpath, File.kind)).all())
    assert kinds["rawbids/sub-001/anat/sub-001_T1w.nii.gz"] == "T1w"
    assert ws.get_or_create_subject("sub-001")


def test_subject_and_session_labels(ws: Workspace, tmp_path: Path, rules: RuleSet) -> None:
    a = make_nifti(tmp_path / "a.nii.gz", seed=1)
    import_nifti(ws, [a], "T1w", rules)
    second = import_nifti(ws, [make_nifti(tmp_path / "b.nii.gz", seed=2)], "T1w", rules)
    assert second.manifest.subject == "sub-002"  # the next free label
    third = import_nifti(
        ws, [make_nifti(tmp_path / "c.nii.gz", seed=3)], "T1w", rules, subject="sub-010",
        session="ses-02",
    )  # fmt: skip
    assert "sub-010/ses-02/anat/sub-010_ses-02_T1w.nii.gz" in tree(ws)
    assert third.manifest.session == "ses-02"
    for bad in (("subject1", None), ("sub-001", "session 2")):
        with pytest.raises(StepError):
            import_nifti(ws, [a], "T1w", rules, subject=bad[0], session=bad[1])


def test_several_files_of_one_type_get_run_numbers(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    files = [make_nifti(tmp_path / f"{n}.nii.gz", seed=n) for n in (1, 2)]
    import_nifti(ws, files, "T1w", rules, subject="sub-001")
    assert [p for p in tree(ws) if p.endswith(".nii.gz")] == [
        "sub-001/anat/sub-001_run-1_T1w.nii.gz",
        "sub-001/anat/sub-001_run-2_T1w.nii.gz",
    ]


def test_another_type_can_be_added_to_the_same_subject(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    import_nifti(ws, [make_nifti(tmp_path / "t1.nii.gz")], "T1w", rules, subject="sub-001")
    import_nifti(ws, [make_nifti(tmp_path / "t2.nii.gz", seed=2)], "T2w", rules, subject="sub-001")
    assert {"sub-001/anat/sub-001_T1w.nii.gz", "sub-001/anat/sub-001_T2w.nii.gz"} <= set(tree(ws))
    assert (ws.root / "rawbids/participants.tsv").read_text() == "participant_id\nsub-001\n"


def test_importing_the_same_files_again_changes_nothing(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    src = make_nifti(tmp_path / "t1.nii.gz")
    first = import_nifti(ws, [src], "T1w", rules, subject="sub-001")
    snapshot = {p: (ws.root / "rawbids" / p).stat().st_mtime_ns for p in tree(ws)}
    again = import_nifti(ws, [src], "T1w", rules, subject="sub-001")
    assert (first.is_new, again.is_new) == (True, False)
    assert again.manifest.id == first.manifest.id and again.summary.written == []
    assert len(list_manifests(ws)) == 1
    assert snapshot == {p: (ws.root / "rawbids" / p).stat().st_mtime_ns for p in tree(ws)}


def test_a_different_file_for_the_same_name_is_refused_and_leaves_nothing_behind(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    import_nifti(ws, [make_nifti(tmp_path / "t1.nii.gz", seed=1)], "T1w", rules, subject="sub-001")
    before = tree(ws)
    other = make_nifti(tmp_path / "other.nii.gz", seed=99)
    with pytest.raises(StepError) as info:
        import_nifti(ws, [other], "T1w", rules, subject="sub-001")
    assert info.value.code == "ORGANIZE_COLLISION"
    assert tree(ws) == before
    assert [m.id for m in list_manifests(ws)] == ["import-001"]  # no half-made import
    assert not (ws.root / "imports" / "import-002").exists()


# -- NIfTI files: functional and diffusion ------------------------------------------------------------------


def test_bold_needs_a_task_and_gets_its_task_name_and_tr(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    src = make_nifti(tmp_path / "run.nii.gz", (8, 8, 4, 6), tr=2.0)
    with pytest.raises(StepError) as info:
        import_nifti(ws, [src], "bold", rules)
    assert info.value.code == "TASK_NEEDED"
    with pytest.raises(StepError) as info:
        import_nifti(ws, [src], "bold", rules, task="two words")
    assert info.value.code == "BAD_LABEL"
    result = import_nifti(ws, [src], "bold", rules, task="rest")
    data = sidecar(ws, "sub-001/func/sub-001_task-rest_bold.json")
    assert data["TaskName"] == "rest" and data["RepetitionTime"] == 2.0
    assert any("read from the image header" in n for n in result.notes)


def test_repetition_time_sources(ws: Workspace, tmp_path: Path, rules: RuleSet) -> None:
    ms = make_nifti(tmp_path / "ms.nii.gz", (8, 8, 4, 6), tr=2000.0, unit="msec")
    import_nifti(ws, [ms], "bold", rules, subject="sub-001", task="a")
    assert sidecar(ws, "sub-001/func/sub-001_task-a_bold.json")["RepetitionTime"] == 2.0  # ms -> s

    with_sidecar = make_nifti(tmp_path / "s.nii.gz", (8, 8, 4, 6), tr=9.0, seed=2)
    (tmp_path / "s.json").write_text(json.dumps({"RepetitionTime": 1.5}))
    result = import_nifti(ws, [with_sidecar], "bold", rules, subject="sub-002", task="b")
    assert sidecar(ws, "sub-002/func/sub-002_task-b_bold.json")["RepetitionTime"] == 1.5
    assert result.notes == []  # a sidecar value needs no remark

    given = import_nifti(ws, [with_sidecar], "bold", rules, subject="sub-003", task="b", tr=3.0)
    assert sidecar(ws, "sub-003/func/sub-003_task-b_bold.json")["RepetitionTime"] == 3.0
    assert any("--tr" in n for n in given.notes)

    unknown = make_nifti(tmp_path / "u.nii.gz", (8, 8, 4, 6), unit="unknown", seed=3)
    with pytest.raises(StepError) as info:
        import_nifti(ws, [unknown], "bold", rules, subject="sub-004", task="c")
    assert info.value.code == "TR_NEEDED" and "--tr" in info.value.suggested_action


def make_dwi(directory: Path, volumes: int = 7, n_bval: int | None = None) -> Path:
    src = make_nifti(directory / "dwi.nii.gz", (8, 8, 4, volumes))
    (directory / "dwi.bval").write_text(" ".join(["1000"] * (n_bval or volumes)) + "\n")
    zeros = " ".join(["0"] * volumes)
    (directory / "dwi.bvec").write_text("\n".join([zeros] * 3) + "\n")
    return src


def test_diffusion_directions_are_copied_and_checked(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    import_nifti(ws, [make_dwi(tmp_path)], "dwi", rules)
    assert (ws.root / "rawbids/sub-001/dwi/sub-001_dwi.bval").read_text().split() == ["1000"] * 7
    assert len((ws.root / "rawbids/sub-001/dwi/sub-001_dwi.bvec").read_text().splitlines()) == 3

    lonely = make_nifti(tmp_path / "lonely" / "d.nii.gz", (8, 8, 4, 7))
    with pytest.raises(StepError) as info:
        import_nifti(ws, [lonely], "dwi", rules, subject="sub-002")
    assert (
        info.value.code == "DWI_NEEDS_DIRECTIONS"
        and "next to the image" in info.value.probable_cause
    )

    wrong = make_dwi(tmp_path / "wrong", volumes=7, n_bval=5)
    with pytest.raises(StepError) as info:
        import_nifti(ws, [wrong], "dwi", rules, subject="sub-003")
    assert info.value.code == "DWI_DIRECTIONS_MISMATCH" and "5 b-values" in info.value.message


# -- NIfTI files: refusing what does not fit -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("shape", "kind"),
    [((8, 8, 4, 3), "T1w"), ((8, 8, 4), "bold"), ((8, 8, 4), "dwi"), ((8, 8, 4, 2, 2), "bold")],
)
def test_images_that_do_not_fit_the_type_are_refused(
    ws: Workspace, tmp_path: Path, rules: RuleSet, shape: tuple[int, ...], kind: str
) -> None:
    src = make_nifti(tmp_path / "x.nii.gz", shape, tr=2.0)
    (tmp_path / "x.bval").write_text("1000 1000 1000\n")
    (tmp_path / "x.bvec").write_text("0 0 0\n0 0 0\n0 0 0\n")
    with pytest.raises(StepError) as info:
        import_nifti(ws, [src], kind, rules, task="rest")
    assert info.value.code == "NIFTI_WRONG_SHAPE" and info.value.suggested_action
    assert not (ws.root / "rawbids" / "sub-001").exists()


def test_unsupported_and_unknown_types(ws: Workspace, tmp_path: Path, rules: RuleSet) -> None:
    src = make_nifti(tmp_path / "x.nii.gz")
    with pytest.raises(StepError) as info:
        import_nifti(ws, [src], "fieldmap-phase", rules)
    assert info.value.code == "NIFTI_TYPE_UNSUPPORTED" and "bold" in info.value.suggested_action
    with pytest.raises(StepError) as info:
        import_nifti(ws, [src], "banana", rules)
    assert info.value.code == "UNKNOWN_KIND"
    with pytest.raises(StepError) as info:
        import_nifti(ws, [], "T1w", rules)
    assert info.value.code == "NO_FILES"


def test_bad_files_are_refused_in_plain_language(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    fake = tmp_path / "fake.nii.gz"
    fake.write_text("not an image")
    wrong_ext = tmp_path / "scan.txt"
    wrong_ext.write_text("x")
    broken_json = make_nifti(tmp_path / "j.nii.gz")
    (tmp_path / "j.json").write_text("{nope")
    for path, code in ((fake, "INPUT_NOT_NIFTI"), (wrong_ext, "INPUT_NOT_NIFTI"),
                       (tmp_path / "missing.nii.gz", "INPUT_NOT_NIFTI"),
                       (broken_json, "INPUT_JSON_INVALID")):  # fmt: skip
        with pytest.raises(StepError) as info:
            import_nifti(ws, [path], "T1w", rules)
        assert info.value.code == code and info.value.suggested_action, path.name
    assert not (ws.root / "imports").exists() or not list(
        (ws.root / "imports").glob("import-*")
    )  # nothing half-imported


@pytest.mark.bidsvalidator
@needs_validator
def test_a_dataset_made_from_nifti_files_passes_the_bids_validator(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    import_nifti(ws, [make_nifti(tmp_path / "t1.nii.gz")], "T1w", rules, subject="sub-001")
    bold = make_nifti(tmp_path / "bold.nii.gz", (8, 8, 4, 6), tr=2.0, seed=2)
    import_nifti(ws, [bold], "bold", rules, subject="sub-001", task="rest")
    import_nifti(ws, [make_dwi(tmp_path)], "dwi", rules, subject="sub-001")
    report = validate_dataset(ws)
    assert report.ok, [i.what for i in report.errors]
    assert {i.code for i in report.warnings} <= {113, 13, 7, 9}  # no authors; optional fields


# -- existing BIDS datasets: building a source ---------------------------------------------------------------


def build_source(
    tmp_path: Path,
    rules: RuleSet,
    subjects: tuple[str, ...] = ("sub-001", "sub-002"),
    salt: str = "",
) -> Path:
    """A real BIDS dataset (written by MRForge's organizer, so valid) to import from."""
    src_ws = Workspace.create(tmp_path / "source_workspace")
    for number, subject in enumerate(subjects, start=1):
        m = new_manifest(src_ws, rules, f"import-00{number}", subject)
        fabricate(src_ws, m, rules, tag=subject + salt)
        organize(src_ws, m, rules)
    return src_ws.root / "rawbids"


def files_of(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha256_of(p) for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def source(tmp_path: Path, rules: RuleSet) -> Path:
    return build_source(tmp_path, rules)


def test_an_existing_dataset_is_copied_exactly_without_converting_anything(
    ws: Workspace, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = {p: (p.stat().st_mtime_ns, p.stat().st_mode) for p in source.rglob("*")}

    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("an external program was started")

    monkeypatch.setattr(subprocess, "run", forbidden)  # no dcm2niix, no validator
    result = import_bids(ws, source, check_source=False)
    assert result.is_new and result.summary.subjects == ["sub-001", "sub-002"]
    assert files_of(ws.root / "rawbids") == files_of(source)  # every file identical
    assert not (ws.root / "imports" / result.manifest.id / "converted").exists()
    assert {p: (p.stat().st_mtime_ns, p.stat().st_mode) for p in source.rglob("*")} == before
    # imaging files are read-only; the source's own permissions were not touched
    t1 = ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    assert not t1.stat().st_mode & stat.S_IWUSR and not os.path.samefile(
        t1, source / "sub-001/anat/sub-001_T1w.nii.gz"
    )


def test_subjects_and_files_are_registered(ws: Workspace, source: Path) -> None:
    result = import_bids(ws, source, check_source=False)
    with ws.session() as s:
        kinds = dict(s.execute(select(File.relpath, File.kind)).all())
    assert kinds["rawbids/sub-002/func/sub-002_task-rest_bold.nii.gz"] == "bold"
    assert kinds["rawbids/sub-001/dwi/sub-001_dwi.bval"] == "bval"
    assert kinds["rawbids/sub-001/fmap/sub-001_acq-fmap_phasediff.json"] == "phasediff.json"
    assert set(result.manifest.organized) == {"bids:sub-001", "bids:sub-002"}
    assert ws.get_or_create_subject("sub-002")


def test_importing_the_same_dataset_again_changes_nothing(ws: Workspace, source: Path) -> None:
    first = import_bids(ws, source, check_source=False)
    snapshot = {
        p: (ws.root / "rawbids" / p).stat().st_mtime_ns for p in files_of(ws.root / "rawbids")
    }
    again = import_bids(ws, source, check_source=False)
    assert (first.is_new, again.is_new) == (True, False) and again.summary.written == []
    assert len(again.summary.in_place) == len(first.summary.written)
    assert len(list_manifests(ws)) == 1
    now = {p: (ws.root / "rawbids" / p).stat().st_mtime_ns for p in files_of(ws.root / "rawbids")}
    assert snapshot == now


def test_a_dataset_can_be_added_to_one_that_already_has_some_of_its_subjects(
    ws: Workspace, tmp_path: Path, rules: RuleSet
) -> None:
    full = build_source(tmp_path / "a", rules)
    partial = tmp_path / "partial"
    shutil.copytree(full, partial)
    shutil.rmtree(partial / "sub-002")
    (partial / "participants.tsv").write_text("participant_id\nsub-001\n")
    import_bids(ws, partial, check_source=False)
    result = import_bids(ws, full, check_source=False)
    assert all(
        p.startswith("rawbids/sub-002/") or p == "rawbids/participants.tsv"
        for p in result.summary.written
    )
    assert any(p.startswith("rawbids/sub-001/") for p in result.summary.in_place)
    assert (
        ws.root / "rawbids/participants.tsv"
    ).read_text() == "participant_id\nsub-001\nsub-002\n"
    assert files_of(ws.root / "rawbids") == files_of(full)


def test_different_data_under_the_same_subject_is_refused_before_anything_is_written(
    ws: Workspace, source: Path, tmp_path: Path, rules: RuleSet
) -> None:
    import_bids(ws, source, check_source=False)
    other = build_source(tmp_path / "other", rules, subjects=("sub-001", "sub-003"), salt="x")
    before = files_of(ws.root / "rawbids")
    with pytest.raises(StepError) as info:
        import_bids(ws, other, check_source=False)
    assert info.value.code == "ORGANIZE_COLLISION"
    assert files_of(ws.root / "rawbids") == before  # sub-003 was not added either
    assert not (ws.root / "rawbids" / "sub-003").exists()


def test_other_files_are_not_copied_and_the_user_is_told(ws: Workspace, source: Path) -> None:
    for folder in ("derivatives", "sourcedata", "code", ".git"):
        (source / folder).mkdir()
        (source / folder / "x.txt").write_text("x")
    (source / ".DS_Store").write_text("junk")
    os.symlink(source / "README", source / "linked-readme")
    result = import_bids(ws, source, check_source=False)
    copied = files_of(ws.root / "rawbids")
    assert not any(p.startswith(("derivatives", "sourcedata", "code", ".git")) for p in copied)
    assert ".DS_Store" not in copied and "linked-readme" not in copied
    text = " ".join(result.summary.notes)
    for expected in (
        "'derivatives'",
        "'sourcedata'",
        "'code'",
        "hidden folder '.git'",
        "link 'linked-readme'",
    ):
        assert expected in text, expected


def test_existing_top_level_files_win_and_participants_are_merged(
    ws: Workspace, source: Path, tmp_path: Path, rules: RuleSet
) -> None:
    import_bids(ws, source, check_source=False)
    other = build_source(tmp_path / "other", rules, subjects=("sub-003",))
    (other / "dataset_description.json").write_text(
        json.dumps({"Name": "Another", "BIDSVersion": "1.9.0"})
    )
    result = import_bids(ws, other, check_source=False)
    description = json.loads((ws.root / "rawbids/dataset_description.json").read_text())
    assert description["Name"] == "source_workspace"  # the first import's description stays
    assert any("dataset_description.json already exists" in n for n in result.summary.notes)
    assert (
        ws.root / "rawbids/participants.tsv"
    ).read_text() == "participant_id\nsub-001\nsub-002\nsub-003\n"


def test_participants_tables_are_merged_without_losing_columns() -> None:
    mine = "participant_id\tage\nsub-001\t30\n"
    theirs = "participant_id\tsex\nsub-001\tF\nsub-002\tM\n"
    merged = merge_participants(mine, theirs).splitlines()
    assert merged == [  # existing rows win: sub-001 keeps its own values; new columns get n/a
        "participant_id\tage\tsex",
        "sub-001\t30\tn/a",
        "sub-002\tn/a\tM",
    ]
    assert merge_participants(None, theirs) == theirs
    assert merge_participants(mine, mine) == mine


def test_things_that_are_not_importable_bids_datasets(
    ws: Workspace, source: Path, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    cases = [
        (empty, "IMPORT_NOT_BIDS"),
        (tmp_path / "nope", "IMPORT_SOURCE_INVALID"),
        (ws.root / "rawbids", "IMPORT_BIDS_SELF"),
    ]
    derivative = tmp_path / "derivative"
    derivative.mkdir()
    (derivative / "dataset_description.json").write_text(
        json.dumps({"Name": "d", "BIDSVersion": "1.9.0", "DatasetType": "derivative"})
    )
    cases.append((derivative, "IMPORT_BIDS_IS_DERIVATIVE"))
    for path, code in cases:
        with pytest.raises(StepError) as info:
            import_bids(ws, path, check_source=False)
        assert info.value.code == code and info.value.suggested_action, code
    assert list_manifests(ws) == []


def test_a_missing_validator_is_a_note_not_a_failure(
    ws: Workspace, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*_a: object, **_k: object) -> None:
        raise StepError(
            code="VALIDATOR_NOT_FOUND", message="The BIDS validator could not be found."
        )

    monkeypatch.setattr(existing_module, "validate_path", missing)
    result = import_bids(ws, source)
    assert result.is_new and any("not checked" in n for n in result.summary.notes)


@pytest.mark.bidsvalidator
@needs_validator
def test_a_dataset_with_bids_errors_is_refused_unless_allowed(
    ws: Workspace, source: Path, tmp_path: Path
) -> None:
    (source / "sub-001/anat/sub-001_T1w.json").rename(source / "sub-001/anat/sub-001_T1w_typo.json")
    with pytest.raises(StepError) as info:
        import_bids(ws, source)
    err = info.value
    assert err.code == "IMPORT_BIDS_INVALID" and "--allow-errors" in err.suggested_action
    assert not (ws.root / "rawbids" / "sub-001").exists()
    result = import_bids(ws, source, allow_errors=True)
    assert result.is_new and result.source_report is not None and result.source_report.errors


@pytest.mark.bidsvalidator
@needs_validator
def test_a_valid_dataset_passes_the_check_before_and_after_copying(
    ws: Workspace, source: Path
) -> None:
    result = import_bids(ws, source)
    assert result.source_report is not None and result.source_report.ok
    assert validate_dataset(ws).ok


# -- CLI ---------------------------------------------------------------------------------------------------------


def test_cli_nifti_and_list(ws: Workspace, tmp_path: Path) -> None:
    w = str(ws.root)
    src = make_nifti(tmp_path / "scan.nii.gz")
    r = runner.invoke(app, ["import", "nifti", str(src), "--type", "T1w", "-s", "sub-005", "-w", w])
    assert r.exit_code == 0, r.output
    assert "file 1 (scan.nii.gz)" in r.output and "sub-005_T1w.nii.gz" in r.output
    assert "2 file(s) written" in r.output
    again = runner.invoke(
        app, ["import", "nifti", str(src), "--type", "T1w", "-s", "sub-005", "-w", w]
    )
    assert "already imported" in again.output and "0 file(s) written" in again.output
    listing = runner.invoke(app, ["import", "list", "-w", w]).output
    assert "import-001  NIfTI" in listing and "sub-005" in listing
    shown = runner.invoke(app, ["import", "show", "-w", w]).output
    assert "NIfTI file 1" in shown and "import as anat/T1w" in shown and "scan.nii.gz" not in shown


def test_cli_nifti_errors_are_plain(ws: Workspace, tmp_path: Path) -> None:
    w = str(ws.root)
    src = make_nifti(tmp_path / "bold.nii.gz", (8, 8, 4, 6), tr=2.0)
    for args, text in (
        (["--type", "bold"], "needs a task name"),
        (["--type", "banana"], "cannot be imported"),
        (["--type", "fieldmap-phase"], "only supported when converting DICOM"),
    ):
        r = runner.invoke(app, ["import", "nifti", str(src), *args, "-w", w])
        assert r.exit_code == 1 and text in r.output and "Traceback" not in r.output, args
    missing = runner.invoke(
        app, ["import", "nifti", str(tmp_path / "x.nii.gz"), "--type", "T1w", "-w", w]
    )
    assert missing.exit_code == 1 and "does not exist" in missing.output


def test_cli_bids_and_list(ws: Workspace, source: Path) -> None:
    w = str(ws.root)
    r = runner.invoke(app, ["import", "bids", str(source), "-w", w])
    assert r.exit_code == 0, r.output
    assert "BIDS dataset 'rawbids': 2 subject(s)" in r.output
    again = runner.invoke(app, ["import", "bids", str(source), "-w", w])
    assert "already imported" in again.output
    listing = runner.invoke(app, ["import", "list", "-w", w]).output
    assert "BIDS" in listing and "(whole dataset)" in listing
    assert "subjects: sub-001, sub-002" in runner.invoke(app, ["import", "show", "-w", w]).output
    bad = runner.invoke(app, ["import", "bids", str(source.parent / "nope"), "-w", w])
    assert bad.exit_code == 1 and "not a folder" in bad.output


# -- the real dataset ----------------------------------------------------------------------------------------------


@pytest.mark.realdata
@pytest.mark.bidsvalidator
@needs_validator
def test_the_real_rawbids_of_the_demo_workspace_imports_unchanged(ws: Workspace) -> None:
    real = Path("~/Documents/mrforge-workspaces/import-test/rawbids").expanduser()
    if not real.is_dir():
        pytest.skip("the demo workspace is not available")
    result = import_bids(ws, real)
    assert result.source_report is not None and result.source_report.ok
    assert files_of(ws.root / "rawbids") == files_of(real)
    assert validate_dataset(ws).ok
