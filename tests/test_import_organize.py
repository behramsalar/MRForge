"""Stage 2d: writing converted series into rawbids/ as a BIDS dataset.

Converted files are fabricated from the real 27-series table (tests/data), so naming, fieldmap
and privacy rules are tested without running dcm2niix. The test marked ``realdata`` runs the
whole import on the real session.
"""

import json
import os
import stat
import zlib
from pathlib import Path

import nibabel
import numpy as np
import pytest
from conftest import Fake
from sqlalchemy import select
from typer.testing import CliRunner

from mrforge.cli import app
from mrforge.errors import StepError
from mrforge.importing import organize as organize_module
from mrforge.importing.classify import RuleSet, apply_rules, effective_all, load_rules, set_override
from mrforge.importing.convert import _read_image, convert_import, converted_dir
from mrforge.importing.manifest import load_manifest, save_manifest
from mrforge.importing.models import Conversion, DicomSeries, ImportManifest, SourceInfo
from mrforge.importing.organize import build_plan, load_privacy_keys, organize
from mrforge.models import File
from mrforge.workspace import Workspace

DATA = Path(__file__).parent / "data" / "siemens_session_series.json"
runner = CliRunner()

PRIVATE = {
    "DeviceSerialNumber": "176116",
    "StationName": "AWP176116",
    "InstitutionAddress": " ,,,TR,",
    "InstitutionalDepartmentName": "None",
    "StudyDescription": "some clinic name",
    "ProcedureStepDescription": "some clinic name",
    "AcquisitionTime": "10:36:08.815000",
}


@pytest.fixture(scope="module")
def rules() -> RuleSet:
    return load_rules()


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "study")


def real_series() -> list[DicomSeries]:
    return [DicomSeries(**s) for s in json.loads(DATA.read_text())["series"]]


def new_manifest(
    ws: Workspace, rules: RuleSet, manifest_id: str = "import-001", subject: str = "sub-001",
    session: str | None = None, series: list[DicomSeries] | None = None,
) -> ImportManifest:  # fmt: skip
    m = ImportManifest(
        id=manifest_id,
        source=SourceInfo(name="session", kind="folder", n_files=1, fingerprint=manifest_id),
        dicom_dir=f"sourcedata/dicom/{manifest_id}",
        subject=subject,
        session=session,
        series=series if series is not None else real_series(),
    )
    return apply_rules(m, rules)


def fabricate(
    ws: Workspace, m: ImportManifest, rules: RuleSet, only: set[int] | None = None, tag: str = ""
) -> None:
    """Write fake converted files (and their Conversion records) for the series to import."""
    plan = effective_all(m, rules)
    for s in m.series:
        if plan[s.uid].action != "import" or (only is not None and s.number not in only):
            continue
        out = converted_dir(ws, m, s)
        out.mkdir(parents=True, exist_ok=True)
        suffixes = [o.suffix for o in s.outputs] or [""]
        for suffix in suffixes:
            stem = out / f"{s.number}{'_' + suffix if suffix else ''}"
            volumes = s.volumes or 1
            shape = [8, 8, 4] + ([volumes] if volumes > 1 else [])
            seed = zlib.crc32(f"{m.id}/{tag}/{s.number}/{suffix}".encode())
            data = np.random.default_rng(seed).integers(0, 1000, size=shape, dtype="int16")
            image = nibabel.Nifti1Image(data, np.eye(4))
            image.header.set_xyzt_units("mm", "sec")  # as dcm2niix writes
            if len(shape) == 4:
                image.header.set_zooms((1.0, 1.0, 1.0, 2.0))  # time step = TR
            nibabel.save(image, str(stem) + ".nii.gz")
            te = next((o.echo_time_s for o in s.outputs if o.suffix == suffix), 0.03)
            sidecar = {
                "RepetitionTime": 2.0,
                "EchoTime": te,
                "PhaseEncodingDirection": "j-",
                **PRIVATE,
            }
            if s.number == 6:
                sidecar["SliceTiming"] = [0.0, 0.5, 1.0, 1.5]  # one value per slice (4)
            Path(str(stem) + ".json").write_text(json.dumps(sidecar))
            if plan[s.uid].kind == "dwi":
                Path(str(stem) + ".bval").write_text(" ".join(["1000"] * volumes) + "\n")
                Path(str(stem) + ".bvec").write_text(
                    "\n".join([" ".join(["0"] * volumes)] * 3) + "\n"
                )
        images = [_read_image(ws, out, p.name) for p in sorted(out.glob("*.nii.gz"))]
        m.conversions[s.uid] = Conversion(
            series_uid=s.uid, status="ok", images=images, tool_version="vTEST"
        )


@pytest.fixture
def ready(ws: Workspace, rules: RuleSet) -> ImportManifest:
    m = new_manifest(ws, rules)
    fabricate(ws, m, rules)
    save_manifest(ws, m)
    return m


def tree(ws: Workspace) -> list[str]:
    root = ws.root / "rawbids"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def sidecar(ws: Workspace, rel: str) -> dict[str, object]:
    return json.loads((ws.root / "rawbids" / rel).read_text())  # type: ignore[no-any-return]


EXPECTED_TREE = sorted(
    ["README", "dataset_description.json", "participants.tsv"]
    + [f"sub-001/anat/sub-001_{n}" for n in ("T1w.json", "T1w.nii.gz", "T2w.json", "T2w.nii.gz")]
    + [f"sub-001/dwi/sub-001_dwi.{e}" for e in ("bval", "bvec", "json", "nii.gz")]
    + [f"sub-001/func/sub-001_task-rest_bold.{e}" for e in ("json", "nii.gz")]
    + [
        f"sub-001/fmap/sub-001_acq-{acq}_{kind}.{e}"
        for acq in ("fmap", "grefieldmapping")
        for kind in ("magnitude1", "magnitude2", "phasediff")
        for e in ("json", "nii.gz")
    ]
)


# -- layout and names -----------------------------------------------------------------------


def test_real_session_layout_and_names(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    summary = organize(ws, ready, rules)
    assert tree(ws) == EXPECTED_TREE
    assert len(summary.written) == 22 and summary.in_place == []
    assert all(p.startswith("rawbids/sub-001/") for p in summary.written)


def test_dataset_files(ws: Workspace, ready: ImportManifest, rules: RuleSet) -> None:
    organize(ws, ready, rules)
    desc = sidecar(ws, "dataset_description.json")
    assert desc["DatasetType"] == "raw" and desc["BIDSVersion"] == "1.9.0"
    assert desc["Name"] == "study" and desc["GeneratedBy"][0]["Name"] == "MRForge"  # type: ignore[index]
    assert (ws.root / "rawbids" / "participants.tsv").read_text() == "participant_id\nsub-001\n"
    assert "never modified" in (ws.root / "rawbids" / "README").read_text()


def test_second_subject_is_added_to_participants_in_order(ws: Workspace, rules: RuleSet) -> None:
    for number, subject in ((1, "sub-010"), (2, "sub-002")):
        m = new_manifest(ws, rules, f"import-00{number}", subject)
        fabricate(ws, m, rules, tag=subject)
        organize(ws, m, rules)
    text = (ws.root / "rawbids" / "participants.tsv").read_text()
    assert text == "participant_id\nsub-002\nsub-010\n"


def test_session_goes_into_paths_and_names(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules, session="ses-01")
    fabricate(ws, m, rules)
    organize(ws, m, rules)
    assert "sub-001/ses-01/anat/sub-001_ses-01_T1w.nii.gz" in tree(ws)
    assert "sub-001/ses-01/func/sub-001_ses-01_task-rest_bold.json" in tree(ws)
    fmap = sidecar(ws, "sub-001/ses-01/fmap/sub-001_ses-01_acq-fmap_phasediff.json")
    assert fmap["IntendedFor"] == [  # relative to the subject folder, as BIDS writes it
        "ses-01/dwi/sub-001_ses-01_dwi.nii.gz",
        "ses-01/func/sub-001_ses-01_task-rest_bold.nii.gz",
    ]


def test_run_numbers_only_when_the_same_kind_repeats(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    set_override(m, rules, 7, kind="bold", entities={"task": "rest"})  # a second resting run
    set_override(m, rules, 19, entities={"task": "visual"})  # a single visual run
    fabricate(ws, m, rules)
    organize(ws, m, rules)
    funcs = [p for p in tree(ws) if "/func/" in p and p.endswith(".nii.gz")]
    assert funcs == [
        "sub-001/func/sub-001_task-rest_run-1_bold.nii.gz",  # series 6 (earlier)
        "sub-001/func/sub-001_task-rest_run-2_bold.nii.gz",  # series 7
        "sub-001/func/sub-001_task-visual_bold.nii.gz",  # alone: no run entity
    ]


def test_user_labels_appear_in_names(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    set_override(m, rules, 2, entities={"acq": "highres"})
    fabricate(ws, m, rules)
    organize(ws, m, rules)
    assert "sub-001/anat/sub-001_acq-highres_T1w.nii.gz" in tree(ws)


# -- sidecars -------------------------------------------------------------------------------


def test_site_and_device_details_are_removed_from_every_sidecar(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    organize(ws, ready, rules)
    for rel in (p for p in tree(ws) if p.endswith(".json") and p.startswith("sub-")):
        data = sidecar(ws, rel)
        assert not set(PRIVATE) & set(data), rel
        assert data["RepetitionTime"] == 2.0  # what analysis needs stays


def test_task_name_slice_timing_and_phase_encoding_are_kept(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    organize(ws, ready, rules)
    bold = sidecar(ws, "sub-001/func/sub-001_task-rest_bold.json")
    assert bold["TaskName"] == "rest" and bold["SliceTiming"] == [0.0, 0.5, 1.0, 1.5]
    assert bold["PhaseEncodingDirection"] == "j-"


def test_diffusion_files_are_copied(ws: Workspace, ready: ImportManifest, rules: RuleSet) -> None:
    organize(ws, ready, rules)
    bval = (ws.root / "rawbids/sub-001/dwi/sub-001_dwi.bval").read_text().split()
    assert len(bval) == 65
    assert len((ws.root / "rawbids/sub-001/dwi/sub-001_dwi.bvec").read_text().splitlines()) == 3


def test_phasediff_gets_both_echo_times(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    organize(ws, ready, rules)
    phase = sidecar(ws, "sub-001/fmap/sub-001_acq-fmap_phasediff.json")
    assert phase["EchoTime1"] == 0.00492 and phase["EchoTime2"] == 0.00738
    assert "EchoTime" not in phase


# -- IntendedFor ----------------------------------------------------------------------------


def test_fieldmaps_are_assigned_to_the_runs_that_follow_them(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    set_override(m, rules, 19, entities={"task": "visual"})
    set_override(m, rules, 25, entities={"task": "gorsel"})
    fabricate(ws, m, rules)
    organize(ws, m, rules)
    first = ["dwi/sub-001_dwi.nii.gz", "func/sub-001_task-rest_bold.nii.gz"]  # after 4/5, before 17
    second = ["func/sub-001_task-gorsel_bold.nii.gz", "func/sub-001_task-visual_bold.nii.gz"]
    for kind in ("magnitude1", "magnitude2", "phasediff"):
        assert sidecar(ws, f"sub-001/fmap/sub-001_acq-fmap_{kind}.json")["IntendedFor"] == first
        got = sidecar(ws, f"sub-001/fmap/sub-001_acq-grefieldmapping_{kind}.json")["IntendedFor"]
        assert got == second


def test_user_can_choose_the_fieldmap_or_none(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    set_override(m, rules, 19, entities={"task": "visual"})
    set_override(m, rules, 6, fieldmap="17")  # the resting run uses the later fieldmap
    set_override(m, rules, 9, fieldmap="none")  # the diffusion run uses none
    fabricate(ws, m, rules)
    uses = build_plan(ws, m, rules).uses
    assert uses == {
        "4/5": [],
        "17/18": ["func/sub-001_task-rest_bold.nii.gz", "func/sub-001_task-visual_bold.nii.gz"],
    }
    summary = organize(ws, m, rules)
    assert any("4/5 is not assigned to any run" in n for n in summary.notes)
    assert sidecar(ws, "sub-001/fmap/sub-001_acq-fmap_phasediff.json")["IntendedFor"] == []


def test_a_fieldmap_that_does_not_exist_is_refused(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    set_override(m, rules, 6, fieldmap="99")
    fabricate(ws, m, rules)
    with pytest.raises(StepError) as info:
        build_plan(ws, m, rules)
    assert info.value.code == "FIELDMAP_UNKNOWN" and "99" in info.value.message


def test_fieldmap_choices_are_validated(rules: RuleSet) -> None:
    m = new_manifest(None, rules)  # type: ignore[arg-type]
    with pytest.raises(StepError) as info:
        set_override(m, rules, 6, fieldmap="two")
    assert info.value.code == "BAD_FIELDMAP"
    with pytest.raises(StepError) as info:
        set_override(m, rules, 2, fieldmap="4")  # a T1 has no fieldmap
    assert info.value.code == "FIELDMAP_NOT_APPLICABLE"
    now = set_override(m, rules, 6, fieldmap="4")  # the type stays the rules' result
    assert (now.kind, now.source) == ("bold", "rules") and m.overrides


def test_a_run_before_every_fieldmap_is_noted_not_guessed(ws: Workspace, rules: RuleSet) -> None:
    series = [s for s in real_series() if s.number in (4, 5, 6)]
    for s in series:
        if s.number == 4:
            s.number = 14  # move the fieldmap after the resting run
        if s.number == 5:
            s.number = 15
    m = new_manifest(ws, rules, series=series)
    fabricate(ws, m, rules)
    summary = organize(ws, m, rules)
    assert any("comes before every fieldmap" in n for n in summary.notes)


def test_unpaired_fieldmap_images_are_left_out_with_a_note(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    set_override(m, rules, 18, skip=True)  # the phase image of the second set
    fabricate(ws, m, rules)
    summary = organize(ws, m, rules)
    assert any("Fieldmap series 17 has no matching phase image" in n for n in summary.notes)
    assert not [p for p in tree(ws) if "grefieldmapping" in p]
    # a single remaining fieldmap set needs no acq label
    assert "sub-001/fmap/sub-001_phasediff.nii.gz" in tree(ws)


def test_series_with_several_images_are_left_out_with_a_note(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    fabricate(ws, m, rules)
    t1 = next(s for s in m.series if s.number == 2)
    out = converted_dir(ws, m, t1)
    nibabel.save(
        nibabel.Nifti1Image(np.zeros([4, 4, 3], "int16"), np.eye(4)), str(out / "2_e2.nii.gz")
    )
    (out / "2_e2.json").write_text("{}")
    m.conversions[t1.uid].images = [_read_image(ws, out, n) for n in ("2.nii.gz", "2_e2.nii.gz")]
    summary = organize(ws, m, rules)
    assert any("Series 2 gave 2 images" in n for n in summary.notes)
    assert not [p for p in tree(ws) if "T1w" in p]


# -- raw data is never changed --------------------------------------------------------------


def test_files_are_read_only_and_share_data_with_the_converted_files(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    organize(ws, ready, rules)
    for rel in tree(ws):
        if rel.startswith("sub-"):
            assert not (ws.root / "rawbids" / rel).stat().st_mode & (stat.S_IWUSR | stat.S_IWOTH)
    t1 = next(s for s in ready.series if s.number == 2)
    source = ws.abspath(ready.conversions[t1.uid].images[0].nifti)
    assert os.path.samefile(source, ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz")


def test_copy_is_used_when_linking_is_impossible(
    ws: Workspace, ready: ImportManifest, rules: RuleSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_a: object, **_k: object) -> None:
        raise OSError("cross-device")

    monkeypatch.setattr(organize_module.os, "link", refuse)
    organize(ws, ready, rules)
    t1 = next(s for s in ready.series if s.number == 2)
    source = ws.abspath(ready.conversions[t1.uid].images[0].nifti)
    target = ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    assert not os.path.samefile(source, target) and target.read_bytes() == source.read_bytes()


def test_running_again_changes_nothing(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    organize(ws, ready, rules)
    snapshot = {p: (ws.root / "rawbids" / p).stat().st_mtime_ns for p in tree(ws)}
    again = organize(ws, ready, rules)
    assert again.written == [] and len(again.in_place) == 22
    assert snapshot == {p: (ws.root / "rawbids" / p).stat().st_mtime_ns for p in tree(ws)}
    with ws.session() as s:
        rows = list(s.scalars(select(File.relpath).where(File.relpath.like("rawbids/sub-%"))))
    assert len(rows) == len(set(rows)) == 22  # no duplicate database rows


def test_files_are_registered_in_the_database(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    organize(ws, ready, rules)
    with ws.session() as s:
        kinds = dict(s.execute(select(File.relpath, File.kind)).all())
    assert kinds["rawbids/sub-001/anat/sub-001_T1w.nii.gz"] == "T1w"
    assert kinds["rawbids/sub-001/func/sub-001_task-rest_bold.nii.gz"] == "bold"
    assert kinds["rawbids/sub-001/fmap/sub-001_acq-fmap_phasediff.nii.gz"] == "phasediff"
    assert kinds["rawbids/sub-001/dwi/sub-001_dwi.bval"] == "bval"
    assert ws.get_or_create_subject("sub-001")


def test_a_different_import_into_the_same_subject_is_refused_before_writing_anything(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    organize(ws, ready, rules)
    before = tree(ws)
    other = new_manifest(ws, rules, "import-002", "sub-001")
    fabricate(ws, other, rules, tag="different data")
    with pytest.raises(StepError) as info:
        organize(ws, other, rules)
    assert info.value.code == "ORGANIZE_COLLISION"
    assert "--session" in info.value.suggested_action
    assert tree(ws) == before  # nothing was added or changed
    # the same data in another session is fine
    third = new_manifest(ws, rules, "import-003", "sub-001", session="ses-02")
    fabricate(ws, third, rules, tag="session two")
    organize(ws, third, rules)
    assert "sub-001/ses-02/anat/sub-001_ses-02_T1w.nii.gz" in tree(ws)


def test_changes_that_would_rename_written_files_are_refused(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    fabricate(ws, m, rules)
    organize(ws, m, rules)
    before = tree(ws)
    set_override(m, rules, 7, kind="bold", entities={"task": "rest"})  # needs run-1 / run-2 now
    fabricate(ws, m, rules, only={7})
    with pytest.raises(StepError) as info:
        organize(ws, m, rules)
    assert (
        info.value.code == "ORGANIZE_WOULD_RENAME"
        and "new workspace" in info.value.suggested_action
    )
    assert tree(ws) == before


def test_new_series_that_need_no_renaming_can_be_added_later(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    fabricate(ws, m, rules)
    organize(ws, m, rules)
    set_override(m, rules, 19, entities={"task": "visual"})
    fabricate(ws, m, rules, only={19})
    summary = organize(ws, m, rules)
    assert "rawbids/sub-001/func/sub-001_task-visual_bold.nii.gz" in summary.written
    # the fieldmaps now also correct the new run: only their IntendedFor list changes
    assert len(summary.updated) == 3  # the three files of fieldmap set 17/18
    assert all("acq-grefieldmapping" in p for p in summary.updated)
    assert len(summary.in_place) == 22 - 3
    phasediff = sidecar(ws, "sub-001/fmap/sub-001_acq-grefieldmapping_phasediff.json")
    assert phasediff["IntendedFor"] == ["func/sub-001_task-visual_bold.nii.gz"]
    phase = ws.root / "rawbids/sub-001/fmap/sub-001_acq-grefieldmapping_phasediff.json"
    assert not phase.stat().st_mode & stat.S_IWUSR  # still read-only afterwards
    assert organize(ws, m, rules).updated == []  # and a further run changes nothing


def test_a_changed_sidecar_that_is_not_just_intended_for_is_a_collision(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    organize(ws, ready, rules)
    path = ws.root / "rawbids/sub-001/fmap/sub-001_acq-fmap_phasediff.json"
    data = json.loads(path.read_text())
    data["EchoTime1"] = 0.1  # someone changed real metadata
    path.chmod(0o644)
    path.write_text(json.dumps(data))
    with pytest.raises(StepError) as info:
        organize(ws, ready, rules)
    assert info.value.code == "ORGANIZE_COLLISION"


def test_unconverted_or_failed_series_stop_everything(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    fabricate(ws, m, rules, only={2, 3, 6})  # 4, 5, 9, 17, 18 are missing
    bad = next(s for s in m.series if s.number == 6)
    m.conversions[bad.uid].status = "failed"
    with pytest.raises(StepError) as info:
        organize(ws, m, rules)
    err = info.value
    assert err.code == "ORGANIZE_NEEDS_CONVERSION"
    assert "4, 5, 9, 17, 18" in err.message and "conversion failed: 6" in err.message
    assert not (ws.root / "rawbids" / "README").exists()  # not even the dataset files


# -- the privacy list -----------------------------------------------------------------------


def test_the_privacy_list_can_be_replaced_per_workspace(ws: Workspace, rules: RuleSet) -> None:
    assert "StationName" in load_privacy_keys(ws)
    (ws.root / "imports").mkdir(exist_ok=True)
    (ws.root / "imports" / "sidecar_privacy.yaml").write_text("remove: [StationName]\n")
    assert load_privacy_keys(ws) == {"StationName"}
    m = new_manifest(ws, rules)
    fabricate(ws, m, rules)
    organize(ws, m, rules)
    data = sidecar(ws, "sub-001/anat/sub-001_T1w.json")
    assert "StationName" not in data and data["DeviceSerialNumber"] == "176116"  # her choice


@pytest.mark.parametrize("text", ["remove: nope", "other: [a]", "{broken", "remove: [1, 2]"])
def test_a_broken_privacy_list_is_a_plain_error(ws: Workspace, text: str) -> None:
    (ws.root / "imports").mkdir(exist_ok=True)
    (ws.root / "imports" / "sidecar_privacy.yaml").write_text(text)
    with pytest.raises(StepError) as info:
        load_privacy_keys(ws)
    assert info.value.code == "PRIVACY_LIST_INVALID" and info.value.suggested_action


# -- CLI ------------------------------------------------------------------------------------


def test_cli_organize_prints_where_everything_went(
    ws: Workspace, ready: ImportManifest, rules: RuleSet
) -> None:
    r = runner.invoke(app, ["import", "organize", "-w", str(ws.root)])
    assert r.exit_code == 0, r.output
    assert "series 2 (t1w) -> rawbids/sub-001/anat/sub-001_T1w.nii.gz" in r.output
    assert "fieldmap series 4 + 5 is used by: dwi/sub-001_dwi.nii.gz" in r.output
    assert "22 file(s) written, 0 already in place" in r.output
    again = runner.invoke(app, ["import", "organize", "-w", str(ws.root)])
    assert "0 file(s) written, 22 already in place" in again.output


def test_cli_organize_errors_are_plain(ws: Workspace, rules: RuleSet) -> None:
    m = new_manifest(ws, rules)
    save_manifest(ws, m)  # nothing converted
    r = runner.invoke(app, ["import", "organize", "-w", str(ws.root)])
    assert r.exit_code == 1 and "ORGANIZE_NEEDS_CONVERSION" in r.output
    assert "mrforge import convert" in r.output and "Traceback" not in r.output


def test_cli_set_fieldmap(ws: Workspace, ready: ImportManifest) -> None:
    w = str(ws.root)
    r = runner.invoke(app, ["import", "set", "6", "--fieldmap", "none", "-w", w])
    assert r.exit_code == 0 and "will use fieldmap: none" in r.output
    assert "import as func/bold task-rest" in r.output  # the type is untouched
    assert (
        load_manifest(ws).overrides
        and not runner.invoke(app, ["import", "set", "2", "--fieldmap", "4", "-w", w]).exit_code
        == 0
    )
    organized = runner.invoke(app, ["import", "organize", "-w", w]).output
    assert "fieldmap series 4 + 5 is used by: dwi/sub-001_dwi.nii.gz" in organized
    assert "task-rest_bold" not in organized.split("is used by:")[1].splitlines()[0]


def test_cli_run_converts_and_organizes(
    ws: Workspace, tmp_path: Path, fake: Fake, rules: RuleSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dicomfactory import make_session

    from mrforge.importing import scan as scan_module
    from mrforge.importing.models import CommandRecord
    from mrforge.importing.scan import scan_source

    monkeypatch.setattr(
        scan_module,
        "sidecar_pass",
        lambda d, s: (CommandRecord(argv=["dcm2niix"], return_code=0), "vTEST", []),
    )
    source = tmp_path / "Zzyzx_Quentin_session"
    make_session(source)
    fake.set(2, images=[{"suffix": "", "shape": [4, 4, 3]}])
    fake.set(6, images=[{"suffix": "", "shape": [4, 4, 3, 4]}])
    scan_source(ws, source)
    r = runner.invoke(app, ["import", "run", "-w", str(ws.root)])
    assert r.exit_code == 0, r.output
    assert "sub-001_T1w.nii.gz" in r.output and "sub-001_task-rest_bold.nii.gz" in r.output
    assert "1 series still need your input" in r.output
    assert (ws.root / "rawbids/sub-001/anat/sub-001_T1w.json").is_file()
    assert "Zzyzx" not in r.output


def test_cli_run_stops_before_writing_when_a_conversion_fails(
    ws: Workspace, tmp_path: Path, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dicomfactory import make_session

    from mrforge.importing import scan as scan_module
    from mrforge.importing.models import CommandRecord
    from mrforge.importing.scan import scan_source

    monkeypatch.setattr(
        scan_module,
        "sidecar_pass",
        lambda d, s: (CommandRecord(argv=["dcm2niix"], return_code=0), "vTEST", []),
    )
    source = tmp_path / "session"
    make_session(source)
    fake.set(2, images=[{"suffix": "", "shape": [4, 4, 3]}])
    fake.set(6, mode="fail")
    scan_source(ws, source)
    r = runner.invoke(app, ["import", "run", "-w", str(ws.root)])
    assert r.exit_code == 1
    assert "Conversion failed for series 6" in r.output and "Nothing was written" in r.output
    assert not (ws.root / "rawbids" / "sub-001").exists()


# -- the real session -----------------------------------------------------------------------


@pytest.mark.realdata
def test_real_session_end_to_end(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    from mrforge.importing.scan import scan_source

    monkeypatch.undo()
    base = Path(os.environ.get("MRFORGE_TEST_DATA", "~/Documents/mri-test-data")).expanduser()
    if not (base / "test").is_dir():
        pytest.skip(f"test session not found: {base / 'test'}")
    rules = load_rules()
    manifest, _ = scan_source(ws, base / "test")
    assert convert_import(ws, manifest, rules).failed == []
    summary = organize(ws, manifest, rules)
    assert tree(ws) == EXPECTED_TREE and len(summary.written) == 22
    func = sidecar(ws, "sub-001/func/sub-001_task-rest_bold.json")
    assert func["TaskName"] == "rest" and func["RepetitionTime"] == 2.0
    assert not set(PRIVATE) & set(func)
    img = nibabel.load(ws.root / "rawbids/sub-001/func/sub-001_task-rest_bold.nii.gz")
    assert img.shape == (74, 74, 62, 360)  # type: ignore[attr-defined]
    assert organize(ws, manifest, rules).written == []


def test_cli_names_series_by_protocol_when_the_description_is_empty(
    ws: Workspace, rules: RuleSet
) -> None:
    """Philips leaves SeriesDescription empty; the protocol name is shown instead."""
    series = real_series()
    t1 = next(s for s in series if s.number == 2)
    t1.description, t1.protocol = "", "sT1W_3D_TFE_v2 SENSE"
    m = new_manifest(ws, rules, series=series)
    fabricate(ws, m, rules)
    save_manifest(ws, m)
    r = runner.invoke(app, ["import", "organize", "-w", str(ws.root)])
    assert r.exit_code == 0, r.output
    assert "series 2 (sT1W_3D_TFE_v2 SENSE) -> rawbids/sub-001/anat/sub-001_T1w.nii.gz" in r.output
