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


def test_extra_slices_after_whole_volumes_are_reported_as_a_stopped_acquisition(
    tmp_path: Path,
) -> None:
    uid = new_uid()
    for volume in range(2):  # 2 complete volumes of 3 slices ...
        for z in range(3):
            make_dicom(tmp_path / "s" / f"v{volume}_{z}.dcm", uid, 1, position_z=float(z))
    for z in range(2):  # ... and a third one that was never finished
        make_dicom(tmp_path / "s" / f"v2_{z}.dcm", uid, 1, position_z=float(z))
    (series,), _ = scan_directory(tmp_path / "s")
    assert series.slices == 3 and series.volumes == 2 and series.n_files == 8
    note = next(w for w in series.warnings if "do not fill whole volumes" in w)
    assert "2 extra slice(s) after 2 complete volume(s)" in note and "stopped early" in note


def test_a_series_without_a_slice_count_has_no_volume_count(tmp_path: Path) -> None:
    make_dicom(tmp_path / "s" / "a.dcm", new_uid(), 1, position_z=None)  # no position, no frames
    (series,), _ = scan_directory(tmp_path / "s")
    assert series.volumes is None
    assert any("number of volumes" in w for w in series.warnings)


@pytest.mark.parametrize(
    "object_has_rows", [False, True], ids=["no-rows", "private-object-with-rows"]
)
def test_scanner_objects_without_an_image_do_not_count_as_slices(
    tmp_path: Path, object_has_rows: bool
) -> None:
    """Philips adds one extra object to every series. Sometimes it has no size at all, sometimes
    it carries Rows and Columns but no ImageType, no position and no pixels."""
    uid = new_uid()
    for z in range(3):
        make_dicom(
            tmp_path / "s" / f"img_{z}.dcm",
            uid,
            401,
            "",
            protocol="sT1W_3D_TFE",
            position_z=float(z),
        )
    # sorts first, so it must not be used to describe the series
    make_dicom(
        tmp_path / "s" / "a_object.dcm", uid, 401, "", protocol="sT1W_3D_TFE",
        image_type=(), position_z=None, rows=4 if object_has_rows else None,
        columns=4 if object_has_rows else None,
    )  # fmt: skip
    (series,), _ = scan_directory(tmp_path / "s")
    assert (series.n_files, series.slices, series.volumes) == (3, 3, 1)
    assert series.rows == 4 and series.image_type == ["ORIGINAL", "PRIMARY", "M", "NONE"]
    assert any("1 file(s) without an image" in w for w in series.warnings)
    assert not any("number of volumes" in w or "stopped early" in w for w in series.warnings)


def test_objects_without_any_image_share_series_number_zero_quietly(tmp_path: Path) -> None:
    for name in ("ExamCard", "Presentation"):
        make_dicom(
            tmp_path / "s" / f"{name}.dcm", new_uid(), 0, "", protocol=name, image_type=(),
            position_z=None, rows=None, columns=None, modality="PR",
        )  # fmt: skip
    make_dicom(tmp_path / "s" / "t1.dcm", new_uid(), 2, "t1w", position_z=0.0)
    series, _ = scan_directory(tmp_path / "s")
    objects = [s for s in series if s.number == 0]
    assert len(objects) == 2 and all(s.rows is None and s.n_files == 1 for s in objects)
    assert {s.label for s in objects} == {"ExamCard", "Presentation"}  # protocol as the name


def test_the_series_name_falls_back_to_the_protocol_name(tmp_path: Path) -> None:
    make_dicom(tmp_path / "s" / "a.dcm", new_uid(), 5, "", protocol="RSTNG_FE_EPI1 SENSE")
    make_dicom(tmp_path / "t" / "b.dcm", new_uid(), 6, "", protocol="")
    (named,), _ = scan_directory(tmp_path / "s")
    (anonymous,), _ = scan_directory(tmp_path / "t")
    assert named.label == "RSTNG_FE_EPI1 SENSE" and anonymous.label == "series 6"


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


# -- macOS / Windows debris in sources ---------------------------------------------------------------


def add_junk(root: Path) -> list[str]:
    junk = ["__MACOSX/session/._img_0.dcm", "session/._img_1.dcm", "session/.DS_Store", "Thumbs.db"]
    for rel in junk:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x05\x16\x07 AppleDouble debris")
    return junk


def test_metadata_debris_is_not_copied_counted_or_listed_as_skipped(
    session: Path, ws: Workspace, tmp_path: Path
) -> None:
    clean = scan_source(Workspace.create(tmp_path / "clean"), session)[0]
    junk = add_junk(session)
    manifest, _ = scan_source(ws, session)
    copied = [
        str(p.relative_to(ws.root / manifest.dicom_dir))
        for p in (ws.root / manifest.dicom_dir).rglob("*")
        if p.is_file()
    ]
    assert not any(is_junk_name(c) for c in copied)
    assert manifest.source.n_files == clean.source.n_files  # real files only
    assert manifest.source.ignored == len(junk)
    assert manifest.skipped_files == []  # not reported as "not a DICOM file"
    assert any(f"{len(junk)} file(s) of macOS/Windows metadata" in w for w in manifest.warnings)
    assert manifest.source.fingerprint == clean.source.fingerprint  # the same data, the same source


def test_a_zip_with_macos_debris_gives_the_same_result(
    session: Path, ws: Workspace, tmp_path: Path
) -> None:
    archive = tmp_path / "session.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in session.rglob("*"):
            if path.is_file():
                zf.write(path, f"Folder/{path.relative_to(session)}")
        for rel in ("__MACOSX/Folder/._a", "Folder/mixed/._t1_0.dcm", "Folder/.DS_Store"):
            zf.writestr(rel, "debris")
    manifest, _ = scan_source(ws, archive)
    assert [s.number for s in manifest.series] == [2, 6, 19]
    assert manifest.source.ignored == 3 and manifest.skipped_files == []
    tree = [p.name for p in (ws.root / manifest.dicom_dir).rglob("*") if p.is_file()]
    assert not any(n.startswith("._") or n == ".DS_Store" for n in tree)
    assert not list((ws.root / manifest.dicom_dir).rglob("__MACOSX"))


def is_junk_name(rel: str) -> bool:
    from mrforge.importing.scan import is_junk

    return is_junk(rel)


@pytest.mark.parametrize(
    ("name", "mode"),
    [
        ("s.tar", "w"),
        ("s.tar.gz", "w:gz"),
        ("s.tgz", "w:gz"),
        ("s.tar.bz2", "w:bz2"),
        ("s.tbz2", "w:bz2"),
        ("s.tar.xz", "w:xz"),
    ],
)
def test_tar_archives_of_every_kind_are_unpacked_like_the_folder(
    session: Path, ws: Workspace, tmp_path: Path, name: str, mode: str
) -> None:
    import tarfile

    archive = tmp_path / name
    with tarfile.open(archive, mode) as tf:  # type: ignore[call-overload]
        tf.add(session, arcname="Some Patient Folder")
        (tmp_path / ".DS_Store").write_text("junk")
        tf.add(tmp_path / ".DS_Store", arcname="Some Patient Folder/.DS_Store")
    manifest, _ = scan_source(ws, archive)
    assert manifest.source.kind == "tar" and manifest.source.n_files > 0
    assert [s.number for s in manifest.series] == [2, 6, 19]
    assert "Some Patient" not in format_manifest(manifest)
    again, is_new = scan_source(ws, archive)  # the same archive is recognised
    assert again.id == manifest.id and not is_new


def test_a_tar_with_a_path_that_escapes_is_refused(ws: Workspace, tmp_path: Path) -> None:
    import io
    import tarfile

    archive = tmp_path / "evil.tar.bz2"
    with tarfile.open(archive, "w:bz2") as tf:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 2
        tf.addfile(info, io.BytesIO(b"no"))
    with pytest.raises(StepError) as err:
        scan_source(ws, archive)
    assert err.value.code == "IMPORT_TAR_UNSAFE"
    assert not (ws.root.parent / "escape.txt").exists()
    assert not list((ws.root / "sourcedata" / "dicom").iterdir())


def test_a_tar_with_a_link_to_somewhere_else_is_refused(ws: Workspace, tmp_path: Path) -> None:
    import tarfile

    archive = tmp_path / "link.tar"
    with tarfile.open(archive, "w") as tf:
        link = tarfile.TarInfo("looks-harmless")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    with pytest.raises(StepError) as err:
        scan_source(ws, archive)
    assert err.value.code == "IMPORT_TAR_UNSAFE"


def test_a_damaged_archive_is_explained(ws: Workspace, tmp_path: Path) -> None:
    import tarfile

    good = tmp_path / "g.tar.bz2"
    with tarfile.open(good, "w:bz2") as tf:
        (tmp_path / "x.txt").write_text("x" * 100000)
        tf.add(tmp_path / "x.txt", arcname="x.txt")
    broken = tmp_path / "broken.tar.bz2"
    broken.write_bytes(good.read_bytes()[:-40])  # cut off the end
    with pytest.raises(StepError) as err:
        scan_source(ws, broken)
    assert err.value.code in ("IMPORT_ARCHIVE_UNREADABLE", "IMPORT_SOURCE_INVALID")
