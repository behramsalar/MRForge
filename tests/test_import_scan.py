"""Stage 2a: scanning DICOM sources. Uses synthetic DICOM files; the real session is covered
by the test marked ``realdata`` at the end."""

import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from dicomfactory import (
    DICOMDIR_CLASS,
    SECRET_DATE,
    SECRET_ID,
    SECRET_NAME,
    make_dicom,
    make_session,
    new_uid,
)
from typer.testing import CliRunner

from mrforge.cli import app
from mrforge.errors import StepError
from mrforge.importing import scan as scan_module
from mrforge.importing.manifest import list_manifests, load_manifest
from mrforge.importing.models import CommandRecord, ImportManifest
from mrforge.importing.report import format_manifest
from mrforge.importing.scan import (
    PARALLEL_THRESHOLD,
    check_labels,
    next_subject_label,
    read_header,
    scan_directory,
    scan_source,
)
from mrforge.workspace import Workspace

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_dcm2niix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests do not need the sidecar pass (synthetic files are not convertible)."""

    def fake(dicom_dir, series):  # type: ignore[no-untyped-def]
        return CommandRecord(argv=["dcm2niix", "<dicom>"], return_code=0), "dcm2niix test", []

    monkeypatch.setattr(scan_module, "sidecar_pass", fake)


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


@pytest.fixture
def session(tmp_path: Path) -> Path:
    root = tmp_path / "source_session"
    make_session(root)
    return root


# -- reading and grouping -----------------------------------------------------------------


def test_series_are_grouped_and_counted(session: Path) -> None:
    series, skipped = scan_directory(session)
    assert skipped == []
    by_number = {s.number: s for s in series}
    assert sorted(by_number) == [2, 6, 19]  # sorted by series number

    t1 = by_number[2]  # classic: files of two series interleaved in one folder
    assert (t1.n_files, t1.slices, t1.volumes, t1.multiframe) == (3, 3, 1, False)
    assert t1.matrix == "4x4x3" and t1.description == "t1w"

    bold = by_number[6]
    assert (bold.n_files, bold.slices, bold.volumes) == (12, 3, 4)
    assert bold.repetition_time_s == 2.0 and bold.echo_time_s == 0.03
    assert bold.image_type == ["ORIGINAL", "PRIMARY", "FMRI", "NONE"]

    enhanced = by_number[19]  # one file per volume, slices are frames
    assert (enhanced.n_files, enhanced.slices, enhanced.volumes, enhanced.multiframe) == (
        5,
        8,
        5,
        True,
    )


def test_dicomdir_text_and_damaged_files_are_skipped_with_reasons(tmp_path: Path) -> None:
    root = tmp_path / "src"
    make_dicom(root / "a.dcm", new_uid(), 1)
    make_dicom(root / "DICOMDIR", new_uid(), 2)  # by name
    make_dicom(root / "index_by_class", new_uid(), 3, sop_class=DICOMDIR_CLASS)  # by content
    (root / "notes.txt").write_text("hello")
    (root / "empty").write_bytes(b"")
    good = root / "damaged.dcm"
    shutil.copy(root / "a.dcm", good)
    good.write_bytes(good.read_bytes()[:200])  # truncated
    series, skipped = scan_directory(root)
    assert [s.number for s in series] == [1]
    reasons = {s.name: s.reason for s in skipped}
    assert "DICOMDIR" in reasons["DICOMDIR"] and "directory index" in reasons["index_by_class"]
    assert reasons["notes.txt"] == "not a DICOM file" and reasons["empty"] == "not a DICOM file"
    assert "damaged or incomplete" in reasons["damaged.dcm"]
    assert all("/" not in s.name for s in skipped)  # names only, never folder paths


def test_series_with_disagreeing_files_gets_a_warning(tmp_path: Path) -> None:
    uid = new_uid()
    make_dicom(tmp_path / "s" / "a.dcm", uid, 1, rows=4, columns=4, position_z=0)
    make_dicom(tmp_path / "s" / "b.dcm", uid, 1, rows=8, columns=8, position_z=1)
    (series,), _ = scan_directory(tmp_path / "s")
    assert any("image size" in w for w in series.warnings)


def test_odd_file_count_is_reported_not_guessed(tmp_path: Path) -> None:
    uid = new_uid()
    for z in (0, 1, 2):  # 3 slices ...
        make_dicom(tmp_path / "s" / f"a{z}.dcm", uid, 1, position_z=z)
    make_dicom(tmp_path / "s" / "b.dcm", uid, 1, position_z=0)  # ... plus a stray repeat
    (series,), _ = scan_directory(tmp_path / "s")
    assert series.slices == 3 and series.volumes is None
    assert any("number of volumes" in w for w in series.warnings)


def test_parallel_and_serial_scans_agree(tmp_path: Path) -> None:
    root = tmp_path / "big"
    uid = new_uid()
    for i in range(PARALLEL_THRESHOLD + 12):
        make_dicom(root / f"f{i:03d}.dcm", uid, 1, position_z=float(i % 4))
    serial = scan_directory(root, workers=1)
    parallel = scan_directory(root, workers=2)
    assert serial == parallel
    assert serial[0][0].volumes == (PARALLEL_THRESHOLD + 12) // 4


# -- privacy --------------------------------------------------------------------------------


def test_no_patient_information_is_read_stored_or_shown(
    session: Path, ws: Workspace, tmp_path: Path
) -> None:
    header = read_header(str(next((session / "mixed").glob("t1_0.dcm"))))
    assert not any(
        secret in json.dumps(header, default=str)
        for secret in (SECRET_NAME, SECRET_ID, SECRET_DATE, "Secret Hospital")
    )
    manifest, _ = scan_source(ws, session)
    stored = (ws.root / "imports" / manifest.id / "manifest.json").read_text()
    shown = format_manifest(manifest)
    for secret in (SECRET_NAME.split("^")[0], SECRET_ID, SECRET_DATE, "Secret Hospital"):
        assert secret not in stored and secret not in shown


# -- bringing the source into the workspace -------------------------------------------------


def test_source_is_copied_and_the_original_is_untouched(session: Path, ws: Workspace) -> None:
    before = sorted((p.name, p.stat().st_size) for p in session.rglob("*") if p.is_file())
    manifest, is_new = scan_source(ws, session)
    assert is_new and manifest.id == "import-001" and manifest.subject == "sub-001"
    assert manifest.dicom_dir == "sourcedata/dicom/import-001"  # neutral name, not the source's
    copied = sorted(
        (p.name, p.stat().st_size) for p in (ws.root / manifest.dicom_dir).rglob("*") if p.is_file()
    )
    assert copied == before
    assert sorted((p.name, p.stat().st_size) for p in session.rglob("*") if p.is_file()) == before
    assert manifest.source.kind == "folder" and manifest.source.n_files == len(before)
    assert load_manifest(ws).id == manifest.id
    assert manifest.tool_versions["pydicom"]


def test_scanning_twice_does_not_duplicate_anything(session: Path, ws: Workspace) -> None:
    first, new1 = scan_source(ws, session)
    second, new2 = scan_source(ws, session)
    assert (new1, new2) == (True, False) and first.id == second.id
    assert len(list_manifests(ws)) == 1
    assert [p.name for p in (ws.root / "sourcedata" / "dicom").iterdir()] == ["import-001"]
    with pytest.raises(StepError) as info:  # same data, other label: refused, not duplicated
        scan_source(ws, session, subject="sub-007")
    assert info.value.code == "IMPORT_ALREADY_SCANNED"


def test_a_different_source_gets_the_next_subject_and_import(
    session: Path, ws: Workspace, tmp_path: Path
) -> None:
    scan_source(ws, session)
    other = tmp_path / "other"
    make_dicom(other / "x.dcm", new_uid(), 1, "t1w")
    manifest, _ = scan_source(ws, other, session="ses-02")
    assert manifest.id == "import-002" and manifest.subject == "sub-002"
    assert manifest.session == "ses-02"
    assert next_subject_label(ws) == "sub-003"


def test_zip_is_unpacked_and_matches_the_folder(
    session: Path, ws: Workspace, tmp_path: Path
) -> None:
    archive = tmp_path / "session.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in session.rglob("*"):
            if path.is_file():
                zf.write(path, f"Some Patient Folder/{path.relative_to(session)}")
    manifest, _ = scan_source(ws, archive)
    assert manifest.source.kind == "zip"
    assert [s.number for s in manifest.series] == [2, 6, 19]
    assert "Some Patient" not in format_manifest(manifest)  # folder names inside never shown


def test_unsafe_zip_is_rejected(ws: Workspace, tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "no")
    with pytest.raises(StepError) as info:
        scan_source(ws, archive)
    assert info.value.code == "IMPORT_ZIP_UNSAFE"
    assert not (ws.root.parent / "escape.txt").exists()
    assert not list((ws.root / "sourcedata" / "dicom").iterdir())  # nothing half-copied left


def test_invalid_sources_and_labels(ws: Workspace, tmp_path: Path) -> None:
    (tmp_path / "plain.txt").write_text("x")
    for bad in (tmp_path / "plain.txt", tmp_path / "missing"):
        with pytest.raises(StepError) as info:
            scan_source(ws, bad)
        assert info.value.code == "IMPORT_SOURCE_INVALID"
    with pytest.raises(StepError, match="not a valid subject"):
        check_labels("subject1", None)
    with pytest.raises(StepError, match="not a valid session"):
        check_labels("sub-001", "session 2")
    check_labels("sub-001", "ses-01")


def test_leftover_partial_copy_is_replaced(session: Path, ws: Workspace) -> None:
    stale = ws.root / "sourcedata" / "dicom" / "import-001.partial"
    stale.mkdir(parents=True)
    (stale / "junk.txt").write_text("from an interrupted copy")
    manifest, _ = scan_source(ws, session)
    names = [p.name for p in (ws.root / "sourcedata" / "dicom").iterdir()]
    assert names == ["import-001"] and manifest.series


def test_unreadable_manifest_is_ignored_not_fatal(session: Path, ws: Workspace) -> None:
    scan_source(ws, session)
    broken = ws.root / "imports" / "import-009"
    broken.mkdir()
    (broken / "manifest.json").write_text("{not json")
    assert [m.id for m in list_manifests(ws)] == ["import-001"]


# -- CLI --------------------------------------------------------------------------------------


def test_cli_scan_and_show(session: Path, ws: Workspace) -> None:
    result = runner.invoke(app, ["import", "scan", str(session), "-w", str(ws.root)])
    assert result.exit_code == 0, result.output
    assert "import-001" in result.output and "3 series" in result.output
    assert "resting" in result.output and "4x4x3" in result.output
    for secret in (SECRET_ID, "Zzyzx", "Secret Hospital"):
        assert secret not in result.output
    again = runner.invoke(app, ["import", "scan", str(session), "-w", str(ws.root)])
    assert "already scanned" in again.output
    shown = runner.invoke(app, ["import", "show", "-w", str(ws.root)])
    assert shown.exit_code == 0 and "ep2d_bold_moco_p2" in shown.output


def test_cli_plain_errors(ws: Workspace, tmp_path: Path) -> None:
    nothing = runner.invoke(app, ["import", "show", "-w", str(ws.root)])
    assert nothing.exit_code == 1 and "Nothing has been imported" in nothing.output
    bad = runner.invoke(app, ["import", "scan", str(tmp_path / "nope"), "-w", str(ws.root)])
    assert bad.exit_code == 1 and "not a folder or a ZIP" in bad.output
    assert "Traceback" not in bad.output + nothing.output


def test_manifest_round_trips(session: Path, ws: Workspace) -> None:
    manifest, _ = scan_source(ws, session)
    again = ImportManifest.model_validate_json(manifest.model_dump_json())
    assert again == manifest


# -- the real session ---------------------------------------------------------------------------


@pytest.mark.realdata
def test_real_session(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # use the real dcm2niix sidecar pass
    base = Path(os.environ.get("MRFORGE_TEST_DATA", "~/Documents/mri-test-data")).expanduser()
    source = base / "test"
    if not source.is_dir():
        pytest.skip(f"test session not found: {source}")
    manifest, _ = scan_source(ws, source)
    by_number = {s.number: s for s in manifest.series}
    assert len(manifest.series) == 27 and manifest.source.n_files == 1064
    assert [s.name for s in manifest.skipped_files] == ["DICOMDIR"]

    t1 = by_number[2]
    assert (t1.matrix, t1.volumes, t1.multiframe) == ("256x256x192", 1, True)
    resting = by_number[6]
    assert (resting.matrix, resting.volumes) == ("74x74x62", 360)
    assert resting.repetition_time_s == 2.0 and resting.phase_encoding_direction == "j-"
    assert by_number[9].volumes == 65  # diffusion
    assert by_number[19].volumes == 60 and by_number[25].volumes == 60
    assert [o.suffix for o in by_number[4].outputs] == ["e1", "e2"]  # magnitude echoes
    assert [o.suffix for o in by_number[5].outputs] == ["e2_ph"]  # phase image
    assert by_number[4].volumes == 1  # the two echoes are not counted as two volumes

    # the rules find the same 8 / 17 / 2 split on the freshly scanned real data
    plan = [c.action for c in manifest.classifications.values()]
    assert (plan.count("import"), plan.count("skip"), plan.count("ask")) == (8, 17, 2)
