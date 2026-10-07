"""Stage 6.5: one folder with the final file of every recording, and a settings check."""

import json
from datetime import UTC, datetime
from pathlib import Path

from mrforge.analysis_ready import FOLDER, refresh
from mrforge.provenance import FileRecord, Provenance, StepRef, write_provenance
from mrforge.workspace import Workspace

STD = "MNI152NLin6Asym"


def step_record(ws: Workspace, subject: str, step: str, rec: str, params: dict[str, object],
                inputs: list[str], outputs: list[str]) -> None:  # fmt: skip
    run = ws.derivatives_dir / subject / "func" / "_runs" / f"{step}_{rec}"
    write_provenance(
        run,
        Provenance(
            step=StepRef(name=step, version="2"), job_id=1, subject=subject, parameters=params,
            parameter_hash="p", inputs=[FileRecord(path=p, sha256="a" * 64) for p in inputs],
            outputs=[FileRecord(path=p, sha256="b" * 64) for p in outputs], commands=[],
            tool_versions={}, started=datetime.now(UTC), finished=datetime.now(UTC), status="Completed",
        ),
    )  # fmt: skip


def processed(ws: Workspace, subject: str, smoothing: float = 5.0, denoised: bool = False,
              aroma: bool = True) -> None:  # fmt: skip
    f = f"derivatives/mrforge/{subject}/func"
    rec = "task-rest"
    data = "denoised" if denoised else "preproc"
    image = f"{f}/{subject}_{rec}_space-{STD}_desc-{data}_bold.nii.gz"
    mask = f"{f}/{subject}_{rec}_space-{STD}_desc-brain_mask.nii.gz"
    for rel in (image, mask):
        (ws.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws.root / rel).write_text("x")
    step_record(ws, subject, "feat_preproc", rec,
                {"delete_volumes": 5, "smoothing_fwhm_mm": smoothing, "highpass_cutoff_s": 150.0,
                 "slice_timing": False, "registration_dof": "BBR"},
                [f"rawbids/{subject}/func/{subject}_{rec}_bold.nii.gz", f"{f}/{subject}_desc-prepared_fieldmap.nii.gz"],
                [f"{f}/{subject}_{rec}_desc-preproc_bold.nii.gz"])  # fmt: skip
    bold_in = f"{f}/{subject}_{rec}_desc-{data}_bold.nii.gz"
    if denoised:
        step_record(ws, subject, "regfilt", rec, {"aggressive": False}, [], [bold_in])
        labels = ws.root / f"{f}/{subject}_{rec}_desc-icalabels_labels.json"
        labels.write_text(json.dumps({"source": "aroma" if aroma else "manual", "decided_by": "ICA-AROMA (automatic)" if aroma else "Jane",
                                      "uncertain_treated_as": "signal"}))  # fmt: skip
    step_record(ws, subject, "func_to_mni", rec, {"resolution_mm": 2, "interpolation": "spline"},
                [bold_in], [image, mask])  # fmt: skip


def make(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def test_every_finished_recording_gets_a_link_with_the_same_name_pattern(tmp_path: Path) -> None:
    ws = make(tmp_path)
    processed(ws, "sub-001")
    processed(ws, "sub-002", denoised=True)
    report = refresh(ws)
    names = sorted(Path(r.file).name for r in report.rows)
    assert names == [
        f"sub-001_task-rest_space-{STD}_desc-final_bold.nii.gz",
        f"sub-002_task-rest_space-{STD}_desc-final_bold.nii.gz",
    ]
    link = ws.abspath(report.rows[0].file)
    assert link.is_symlink() and link.read_text() == "x"  # follows the real file
    assert (ws.root / FOLDER.join(["derivatives/mrforge/", ""])).parent  # folder exists
    assert all(r.mask and ws.abspath(r.mask).exists() for r in report.rows)


def test_the_manifest_says_how_each_file_was_made(tmp_path: Path) -> None:
    ws = make(tmp_path)
    processed(ws, "sub-001")
    processed(ws, "sub-002", denoised=True, aroma=False)
    refresh(ws)
    text = (ws.derivatives_dir / FOLDER / "analysis-ready.tsv").read_text()
    header, *lines = text.splitlines()
    assert "Smoothing (mm)" in header and "Noise removal" in header
    assert any("labelled by hand" in ln and "Jane" in ln for ln in lines)
    assert any("none" in ln for ln in lines)


def test_files_made_with_different_settings_are_flagged(tmp_path: Path) -> None:
    ws = make(tmp_path)
    processed(ws, "sub-001", smoothing=5.0)
    processed(ws, "sub-002", smoothing=6.0)
    differences = {d.setting: d.groups for d in refresh(ws).differences}
    assert set(differences) == {"Smoothing (mm)"}
    assert differences["Smoothing (mm)"]["5.0"] == ["sub-001 task-rest"]


def test_the_same_settings_everywhere_give_no_warning(tmp_path: Path) -> None:
    ws = make(tmp_path)
    processed(ws, "sub-001")
    processed(ws, "sub-002")
    assert refresh(ws).differences == []


def test_a_denoised_subject_differs_from_a_non_denoised_one(tmp_path: Path) -> None:
    ws = make(tmp_path)
    processed(ws, "sub-001")
    processed(ws, "sub-002", denoised=True)
    assert "Noise removal" in {d.setting for d in refresh(ws).differences}


def test_links_follow_the_final_file_and_stale_ones_are_removed(tmp_path: Path) -> None:
    ws = make(tmp_path)
    processed(ws, "sub-001")
    first = refresh(ws).rows[0].file
    # Later the subject is denoised: the final file is now the denoised standard-space image.
    processed(ws, "sub-001", denoised=True)
    (
        ws.root
        / f"derivatives/mrforge/sub-001/func/sub-001_task-rest_space-{STD}_desc-preproc_bold.nii.gz"
    ).unlink()
    report = refresh(ws)
    assert report.rows[0].file == first  # the pointer keeps its name
    assert (
        "desc-denoised" in report.rows[0].source
        and report.rows[0].settings["Noise removal"] != "none"
    )


def test_nothing_is_listed_before_anything_is_finished(tmp_path: Path) -> None:
    report = refresh(make(tmp_path))
    assert report.rows == [] and report.differences == []


def test_settings_that_only_exist_with_noise_removal_are_not_reported_as_differences(
    tmp_path: Path,
) -> None:
    ws = make(tmp_path)
    processed(ws, "sub-001")
    processed(ws, "sub-002", denoised=True)
    assert {d.setting for d in refresh(ws).differences} == {"Noise removal"}
