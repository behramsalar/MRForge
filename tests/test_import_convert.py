"""Stage 2c: converting series with dcm2niix.

Most tests use a stand-in ``dcm2niix`` (a small script on PATH) so that behaviour such as
failures, missing echoes and wrong sizes can be produced on demand. The test marked
``realdata`` runs the real dcm2niix on the real session.
"""

import json
import os
from pathlib import Path

import pytest
from conftest import Fake
from dicomfactory import make_dicom, make_session, new_uid
from typer.testing import CliRunner

from mrforge.cli import app
from mrforge.errors import StepError
from mrforge.importing import convert as convert_module
from mrforge.importing import scan as scan_module
from mrforge.importing.classify import load_rules, set_override
from mrforge.importing.convert import (
    convert_import,
    is_up_to_date,
    scrub,
    stage_files,
)
from mrforge.importing.manifest import load_manifest, save_manifest
from mrforge.importing.models import CommandRecord, ImportManifest, SeriesOutput
from mrforge.importing.scan import scan_source
from mrforge.workspace import Workspace

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_sidecar_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_pass(dicom_dir, series):  # type: ignore[no-untyped-def]
        return CommandRecord(argv=["dcm2niix", "<dicom>"], return_code=0), "vTEST", []

    monkeypatch.setattr(scan_module, "sidecar_pass", fake_pass)


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


@pytest.fixture
def imported(tmp_path: Path, ws: Workspace, fake: Fake) -> ImportManifest:
    """A scanned synthetic session: series 2 (T1w) and 6 (resting) are set to import,
    series 19 (a BOLD run without a task name) is waiting."""
    source = tmp_path / "Zzyzx_Quentin_session"  # a folder name that must never reach dcm2niix
    make_session(source)
    fake.set(2, images=[{"suffix": "", "shape": [4, 4, 3]}])
    fake.set(6, images=[{"suffix": "", "shape": [4, 4, 3, 4]}])
    fake.set(19, images=[{"suffix": "", "shape": [4, 4, 8, 5]}])
    manifest, _ = scan_source(ws, source)
    return manifest


def plan(m: ImportManifest) -> dict[int, str]:
    from mrforge.importing.classify import effective_all

    classes = effective_all(m, load_rules())
    return {s.number or 0: classes[s.uid].action for s in m.series}


def conv(ws: Workspace, m: ImportManifest, **kw: object):  # type: ignore[no-untyped-def]
    return convert_import(ws, m, load_rules(), **kw)  # type: ignore[arg-type]


# -- what is converted ------------------------------------------------------------------------


def test_only_series_set_to_import_are_converted(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    assert plan(imported) == {2: "import", 6: "import", 19: "ask"}
    summary = conv(ws, imported)
    assert (summary.converted, summary.failed, summary.up_to_date) == ([2, 6], [], [])
    assert sorted(c["number"] for c in fake.calls()) == [2, 6]  # series 19 was not touched
    base = ws.root / "imports" / "import-001" / "converted"
    assert sorted(p.name for p in base.iterdir()) == ["s2", "s6"]
    assert (base / "s2" / "2.nii.gz").is_file() and (base / "s6" / "6.json").is_file()

    t1 = next(s for s in imported.series if s.number == 2)
    result = imported.conversions[t1.uid]
    assert result.status == "ok" and result.problems == [] and result.tool_version
    (image,) = result.images
    assert (
        image.shape == [4, 4, 3] and image.sidecar and image.nifti.endswith("converted/s2/2.nii.gz")
    )
    assert set(image.sha256) == {image.nifti, image.sidecar}
    assert load_manifest(ws).conversions[t1.uid].status == "ok"  # saved to disk


def test_each_call_sees_only_its_own_series_under_neutral_names(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    conv(ws, imported)
    by_number = {c["number"]: c for c in fake.calls()}
    assert len(by_number[2]["names"]) == 3 and len(by_number[6]["names"]) == 12  # type: ignore[arg-type]
    for call in by_number.values():
        assert all(n.startswith("f") and n[1:].isdigit() for n in call["names"])  # type: ignore[attr-defined]
        assert "Zzyzx" not in json.dumps(call) and "mixed" not in json.dumps(call)


def test_command_and_logs_are_recorded_without_source_paths(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    conv(ws, imported)
    result = next(iter(imported.conversions.values()))
    assert result.command is not None and result.command.return_code == 0
    argv = result.command.argv
    assert argv[1:9] == ["-b", "y", "-ba", "y", "-z", "y", "-f", "%s"]
    assert "<converted>" in argv and "<series>" in argv
    stored = (ws.root / "imports" / "import-001" / "manifest.json").read_text()
    assert str(ws.root) not in stored.replace(str(ws.root / "imports"), "")  # no source paths
    assert (ws.root / "imports" / "import-001" / "logs" / "convert-s2.log").is_file()


def test_scratch_folders_are_removed(ws: Workspace, imported: ImportManifest) -> None:
    conv(ws, imported)
    leftovers = [p.name for p in (ws.root / "imports" / "import-001").iterdir()]
    assert not any(n.startswith("convert-") for n in leftovers)


def test_staging_hard_links_without_copying_and_falls_back_to_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "src" / "deep folder"
    source.mkdir(parents=True)
    files = [source / "a", source / "b"]
    for i, f in enumerate(files):
        f.write_text(f"data {i}")
    stage_files(files, tmp_path / "linked")
    assert os.path.samefile(files[0], tmp_path / "linked" / "f000000")
    assert sorted(p.name for p in (tmp_path / "linked").iterdir()) == ["f000000", "f000001"]

    def refuse(*_a: object, **_k: object) -> None:
        raise OSError("cross-device link")

    monkeypatch.setattr(convert_module.os, "link", refuse)
    stage_files(files, tmp_path / "copied")
    assert (tmp_path / "copied" / "f000001").read_text() == "data 1"
    assert not os.path.samefile(files[1], tmp_path / "copied" / "f000001")
    assert files[1].read_text() == "data 1"  # the original is untouched


# -- resume -----------------------------------------------------------------------------------


def test_second_run_converts_nothing(ws: Workspace, imported: ImportManifest, fake: Fake) -> None:
    conv(ws, imported)
    before = imported.model_dump_json()
    calls = len(fake.calls())
    summary = conv(ws, imported)
    assert (summary.converted, summary.up_to_date) == ([], [2, 6])
    assert len(fake.calls()) == calls and imported.model_dump_json() == before


def test_a_changed_or_deleted_result_is_converted_again(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    conv(ws, imported)
    t1 = next(s for s in imported.series if s.number == 2)
    nifti = ws.abspath(imported.conversions[t1.uid].images[0].nifti)
    nifti.write_bytes(nifti.read_bytes() + b"tamper")
    assert not is_up_to_date(ws, imported.conversions[t1.uid], "vTEST")
    summary = conv(ws, imported)
    assert (summary.converted, summary.up_to_date) == ([2], [6])
    nifti.unlink()
    assert conv(ws, imported).converted == [2]


def test_force_converts_everything_again(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    conv(ws, imported)
    assert conv(ws, imported, force=True).converted == [2, 6]
    assert len(fake.calls()) == 4


def test_a_new_dcm2niix_version_converts_again(
    ws: Workspace, imported: ImportManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    conv(ws, imported)
    monkeypatch.setattr(convert_module, "_dcm2niix_version", lambda exe: "v-other")
    assert conv(ws, imported).converted == [2, 6]


def test_turning_on_another_series_converts_only_that_one(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    conv(ws, imported)
    set_override(imported, load_rules(), 19, entities={"task": "visual"})
    summary = conv(ws, imported)
    assert (summary.converted, summary.up_to_date) == ([19], [2, 6])


# -- failures ---------------------------------------------------------------------------------


def test_one_failing_series_does_not_stop_the_others_and_retry_does_only_that_one(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    fake.set(6, mode="fail")
    summary = conv(ws, imported)
    assert (summary.converted, summary.failed) == ([2], [6])
    bad = imported.conversions[next(s.uid for s in imported.series if s.number == 6)]
    assert bad.status == "failed" and bad.images == []
    assert "exit code 2" in bad.problems[0] and "series 6 (resting)" in bad.problems[0]
    assert "Zzyzx" not in bad.problems[0] and str(ws.root) not in bad.problems[0]
    fake.set(6, images=[{"suffix": "", "shape": [4, 4, 3, 4]}])  # the cause is fixed
    summary = conv(ws, imported)
    assert (summary.converted, summary.up_to_date, summary.failed) == ([6], [2], [])


def test_no_output_is_reported(ws: Workspace, imported: ImportManifest, fake: Fake) -> None:
    fake.set(2, mode="nothing")
    summary = conv(ws, imported)
    assert summary.failed == [2]
    result = imported.conversions[next(s.uid for s in imported.series if s.number == 2)]
    assert "produced no image" in result.problems[0]


def test_wrong_size_and_wrong_volume_count_are_flagged(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    fake.set(2, images=[{"suffix": "", "shape": [9, 9, 9]}])
    fake.set(6, images=[{"suffix": "", "shape": [4, 4, 3, 7]}])
    summary = conv(ws, imported)
    assert summary.failed == [2, 6]
    t1 = imported.conversions[next(s.uid for s in imported.series if s.number == 2)]
    bold = imported.conversions[next(s.uid for s in imported.series if s.number == 6)]
    assert "size 9x9x9" in t1.problems[0] and "4x4x3" in t1.problems[0]
    assert "7 volume(s)" in bold.problems[0] and "found 4" in bold.problems[0]


def test_reordered_axes_are_accepted(ws: Workspace, imported: ImportManifest, fake: Fake) -> None:
    # dcm2niix may put the slice axis first (for example sagittal scans): same data, same sizes
    fake.set(2, images=[{"suffix": "", "shape": [3, 4, 4]}])
    assert conv(ws, imported).converted == [2, 6]


def test_missing_echo_image_is_flagged(ws: Workspace, imported: ImportManifest, fake: Fake) -> None:
    t1 = next(s for s in imported.series if s.number == 2)
    t1.outputs = [SeriesOutput(suffix="e1"), SeriesOutput(suffix="e2")]  # the scan expected two
    fake.set(2, images=[{"suffix": "e1", "shape": [4, 4, 3]}])
    assert conv(ws, imported).failed == [2]
    assert "should give the images ['e1', 'e2']" in imported.conversions[t1.uid].problems[0]


def test_missing_sidecar_is_flagged(ws: Workspace, imported: ImportManifest, fake: Fake) -> None:
    fake.set(2, images=[{"suffix": "", "shape": [4, 4, 3], "no_json": True}])
    assert conv(ws, imported).failed == [2]


def test_missing_dcm2niix_is_a_plain_error(
    ws: Workspace, imported: ImportManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(StepError) as info:
        conv(ws, imported)
    assert info.value.code == "TOOL_NOT_FOUND"


def test_repeated_series_numbers_are_refused(ws: Workspace, tmp_path: Path, fake: Fake) -> None:
    source = tmp_path / "twins"
    for uid in (new_uid(), new_uid()):
        for z in range(3):
            make_dicom(source / uid / f"{z}.dcm", uid, 2, "t1w", position_z=float(z))
    manifest, _ = scan_source(ws, source)
    with pytest.raises(StepError) as info:
        conv(ws, manifest)
    assert info.value.code == "AMBIGUOUS_SERIES"


# -- diffusion --------------------------------------------------------------------------------


@pytest.fixture
def dwi(tmp_path: Path, ws: Workspace, fake: Fake) -> ImportManifest:
    source = tmp_path / "dwi_session"
    uid = new_uid()
    for vol in range(7):
        for z in range(2):
            make_dicom(
                source / f"v{vol}_{z}.dcm", uid, 9, "dti",
                image_type=("ORIGINAL", "PRIMARY", "DIFFUSION", "NONE"), position_z=float(z),
            )  # fmt: skip
    manifest, _ = scan_source(ws, source)
    assert plan(manifest) == {9: "import"}
    return manifest


def test_diffusion_directions_are_converted_and_checked(
    ws: Workspace, dwi: ImportManifest, fake: Fake
) -> None:
    fake.set(9, images=[{"suffix": "", "shape": [4, 4, 2, 7], "bval": 7}])
    assert conv(ws, dwi).converted == [9]
    image = next(iter(dwi.conversions.values())).images[0]
    assert image.bval and image.bvec and set(image.sha256) == {
        image.nifti, image.sidecar, image.bval, image.bvec,
    }  # fmt: skip


@pytest.mark.parametrize(
    ("image", "complaint"),
    [
        ({"suffix": "", "shape": [4, 4, 2, 7]}, "missing"),
        ({"suffix": "", "shape": [4, 4, 2, 7], "bval": 5}, "5 b-values for 7 volumes"),
    ],
)
def test_diffusion_problems_are_flagged(
    ws: Workspace, dwi: ImportManifest, fake: Fake, image: dict[str, object], complaint: str
) -> None:
    fake.set(9, images=[image])
    assert conv(ws, dwi).failed == [9]
    assert complaint in next(iter(dwi.conversions.values())).problems[0]


# -- misc -------------------------------------------------------------------------------------


def test_scrub_removes_source_paths(tmp_path: Path) -> None:
    d = tmp_path / "sourcedata" / "dicom" / "import-001"
    text = f"Warning: bad file {d}/Patient Name/DICOM/1234 and more\nnext {d}"
    out = scrub(text, d)
    assert str(d) not in out and "Patient" not in out.replace("Patient Name/DICOM/1234", "")
    assert out.count("<dicom>") == 2


def test_cli_convert_and_show(ws: Workspace, imported: ImportManifest, fake: Fake) -> None:
    w = str(ws.root)
    first = runner.invoke(app, ["import", "convert", "-w", w])
    assert first.exit_code == 0, first.output
    assert "series 2 (t1w): converted (4x4x3)" in first.output
    assert "2 converted, 0 already done, 0 failed" in first.output
    again = runner.invoke(app, ["import", "convert", "-w", w])
    assert "0 converted, 2 already done" in again.output
    shown = runner.invoke(app, ["import", "show", "-w", w]).output
    assert "CONVERTED" in shown and "yes" in shown


def test_cli_convert_reports_failures_and_how_to_continue(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    fake.set(6, mode="fail")
    r = runner.invoke(app, ["import", "convert", "-w", str(ws.root)])
    assert r.exit_code == 1
    assert "FAILED" in r.output and "Failed series: 6" in r.output
    assert "only the failed series are converted again" in r.output
    assert "Traceback" not in r.output
    assert "FAILED" in runner.invoke(app, ["import", "show", "-w", str(ws.root)]).output


def test_manifest_with_conversions_round_trips(ws: Workspace, imported: ImportManifest) -> None:
    conv(ws, imported)
    save_manifest(ws, imported)
    again = ImportManifest.model_validate_json(imported.model_dump_json())
    assert again == imported and len(again.conversions) == 2


# -- the real session -------------------------------------------------------------------------


@pytest.mark.realdata
def test_real_session_converts_and_checks_out(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()  # real dcm2niix, real sidecar pass
    base = Path(os.environ.get("MRFORGE_TEST_DATA", "~/Documents/mri-test-data")).expanduser()
    if not (base / "test").is_dir():
        pytest.skip(f"test session not found: {base / 'test'}")
    manifest, _ = scan_source(ws, base / "test")
    summary = convert_import(ws, manifest, load_rules())
    assert summary.failed == [] and summary.converted == [2, 3, 4, 5, 6, 9, 17, 18]

    def result(number: int):  # type: ignore[no-untyped-def]
        return manifest.conversions[next(s.uid for s in manifest.series if s.number == number)]

    t1 = result(2).images[0]
    assert sorted(t1.shape) == [192, 256, 256] and t1.sidecar  # axes reordered, same data
    rest = result(6).images[0]
    assert rest.shape == [74, 74, 62, 360] and rest.voxel_size_mm[0] > 0
    dti = result(9).images[0]
    assert dti.shape[3] == 65 and dti.bval and dti.bvec
    assert len(ws.abspath(dti.bval).read_text().split()) == 65
    assert [i.suffix for i in result(4).images] == ["e1", "e2"]  # magnitude echoes
    assert [i.suffix for i in result(5).images] == ["e2_ph"]  # phase image
    assert all(c.status == "ok" and c.problems == [] for c in manifest.conversions.values())
    again = convert_import(ws, manifest, load_rules())
    assert again.converted == [] and len(again.up_to_date) == 8


# -- real-world behaviours found by importing Philips and other Siemens data -----------------------


def test_a_scanner_calculated_map_is_split_off_and_not_imported(
    ws: Workspace, dwi: ImportManifest, fake: Fake
) -> None:
    """Philips diffusion series: dcm2niix writes the complete data (7 volumes, including the
    scanner's ADC volume) as '<n>_ADC' and the diffusion volumes (6) as the main image."""
    fake.set(
        9,
        images=[
            {"suffix": "", "shape": [4, 4, 2, 6], "bval": 6},
            {"suffix": "ADC", "shape": [4, 4, 2, 7]},
        ],
    )
    summary = conv(ws, dwi)
    assert summary.converted == [9] and summary.failed == []
    result = next(iter(dwi.conversions.values()))
    assert [i.suffix for i in result.images] == [""]  # the ADC image is not registered
    assert result.images[0].shape[3] == 6 and result.images[0].bval
    text = " ".join(result.warnings)
    assert "scanner-calculated 'ADC'" in text and "removed 1 scanner-calculated volume" in text
    assert (ws.root / "imports/import-001/converted/s9/9_ADC.nii.gz").exists()  # kept on disk


def test_too_many_missing_volumes_are_still_a_problem_even_with_a_split_off_map(
    ws: Workspace, dwi: ImportManifest, fake: Fake
) -> None:
    fake.set(
        9,
        images=[
            {"suffix": "", "shape": [4, 4, 2, 3], "bval": 3},  # 4 volumes are missing, not 1
            {"suffix": "ADC", "shape": [4, 4, 2, 7]},
        ],
    )
    assert conv(ws, dwi).failed == [9]
    assert (
        "has 3 volume(s), but the scan found 7" in next(iter(dwi.conversions.values())).problems[0]
    )


def test_a_missing_volume_without_a_split_off_map_is_a_problem(
    ws: Workspace, dwi: ImportManifest, fake: Fake
) -> None:
    fake.set(9, images=[{"suffix": "", "shape": [4, 4, 2, 6], "bval": 6}])
    assert conv(ws, dwi).failed == [9]


def test_a_stopped_acquisition_that_cannot_be_converted_says_how_to_leave_it_out(
    ws: Workspace, tmp_path: Path, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "stopped"
    uid = new_uid()
    for volume in range(2):
        for z in range(3):
            make_dicom(
                source / f"v{volume}_{z}.dcm", uid, 6, "resting",
                image_type=("ORIGINAL", "PRIMARY", "FMRI", "NONE"), position_z=float(z),
            )  # fmt: skip
    make_dicom(source / "v2_0.dcm", uid, 6, "resting", position_z=0.0,
               image_type=("ORIGINAL", "PRIMARY", "FMRI", "NONE"))  # fmt: skip
    manifest, _ = scan_source(ws, source)
    series = manifest.series[0]
    assert series.volumes == 2 and any("stopped early" in w for w in series.warnings)
    fake.set(6, mode="fail")
    assert conv(ws, manifest).failed == [6]
    problems = manifest.conversions[series.uid].problems
    assert len(problems) == 2 and "exit code 2" in problems[0]
    assert "stopped early" in problems[1] and "mrforge import set 6 --skip" in problems[1]


def test_cli_shows_every_problem_and_the_skip_hint(
    ws: Workspace, imported: ImportManifest, fake: Fake
) -> None:
    fake.set(6, mode="fail")
    r = runner.invoke(app, ["import", "convert", "-w", str(ws.root)])
    assert r.exit_code == 1
    assert "series 6 (resting): FAILED\n      - dcm2niix stopped with an error" in r.output
    assert "mrforge import set <series> --skip" in r.output
