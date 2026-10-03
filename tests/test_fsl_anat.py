"""FslAnatStep tests.

Unit tests (no FSL) check the guards, names and command line. Real-FSL tests are marked
``fsl``; the ones that run fsl_anat for many minutes are also marked ``slow``:

    pytest -m "fsl and not slow"     # quick FSL checks
    pytest -m "fsl and slow"         # full fsl_anat runs (about 20 minutes each)
"""

import gzip
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path

import psutil
import pytest

from mrforge.engine import Action, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import FslInstall, find_fsl
from mrforge.models import File, JobStatus
from mrforge.provenance import read_provenance
from mrforge.runner.jobs import build_context, create_job, get_job
from mrforge.runner.local import LocalJobQueue
from mrforge.steps.base import execute_step
from mrforge.steps.fsl_anat import NATIVE_FILES, native_folder_name
from mrforge.workspace import Workspace

T1_REL = "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
ANAT = "derivatives/mrforge/sub-001/anat"  # results folder (BIDS)
NATIVE = "sub-001_T1w.anat"  # native fsl_anat folder, named after the input


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def put_nifti(ws: Workspace, rel: str) -> None:
    path = ws.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(struct.pack("<i", 348) + b"\0" * 400)


# -- unit tests: no FSL needed ----------------------------------------------------


def test_native_folder_is_named_after_the_input() -> None:
    assert native_folder_name("rawbids/sub-001/anat/sub-001_T1w.nii.gz") == "sub-001_T1w.anat"
    assert native_folder_name("data/t1w.nii.gz") == "t1w.anat"
    assert native_folder_name("x/sub-02_ses-01_run-2_T1w.nii") == "sub-02_ses-01_run-2_T1w.anat"


def test_result_names_follow_bids(ws: Workspace) -> None:
    put_nifti(ws, T1_REL)
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    out = step.expected_outputs(ctx)
    assert out.biascorr == "sub-001_desc-biascorr_T1w.nii.gz"
    assert out.brain == "sub-001_desc-brain_T1w.nii.gz"
    assert out.brain_mask == "sub-001_desc-brain_mask.nii.gz"
    assert out.segmentation == "sub-001_dseg.nii.gz"
    assert out.segmentation_labels == "sub-001_dseg.tsv"
    assert out.gm_pve == "sub-001_label-GM_probseg.nii.gz"
    assert out.to_mni_nonlinear == "sub-001_space-MNI152NLin6Asym_desc-nonlinear_T1w.nii.gz"
    assert out.to_mni_warp == (
        "sub-001_from-T1w_to-MNI152NLin6Asym_mode-image_desc-fnirtcoeff_xfm.nii.gz"
    )
    assert out.from_mni_warp == (
        "sub-001_from-MNI152NLin6Asym_to-T1w_mode-image_desc-field_xfm.nii.gz"
    )
    assert out.to_mni_linear_mat.endswith("_desc-linear_xfm.mat")
    assert out.subcortical_segmentation is None
    assert ctx.output_dir == ws.root / ANAT
    assert ctx.run_dir == ws.root / ANAT / "_runs" / "fsl_anat"


def test_session_and_run_entities_are_carried_over(ws: Workspace) -> None:
    rel = "rawbids/sub-001/ses-01/anat/sub-001_ses-01_run-2_T1w.nii.gz"
    put_nifti(ws, rel)
    step, ctx = build_context(ws, "fsl_anat", "sub-001", "ses-01", {"t1": rel}, {})
    assert step.expected_outputs(ctx).brain_mask == "sub-001_ses-01_run-2_desc-brain_mask.nii.gz"
    assert ctx.output_dir == ws.root / "derivatives/mrforge/sub-001/ses-01/anat"


def test_outputs_follow_the_subcortical_option(ws: Workspace) -> None:
    put_nifti(ws, T1_REL)
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    out = step.output_relpaths(ctx)  # default: subcortical segmentation is off
    assert len(out) == 13 and not any("subcortical" in p for p in out)
    assert all(p.startswith(f"{ANAT}/sub-001_") for p in out)
    step, ctx = build_context(
        ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {"subcortical_segmentation": True}
    )
    assert any("desc-subcortical_dseg" in p for p in step.output_relpaths(ctx))


def test_refuses_bet_output_as_input(ws: Workspace) -> None:
    put_nifti(ws, T1_REL)
    brain_rel = f"{ANAT}/sub-001_desc-bet_T1w.nii.gz"
    put_nifti(ws, brain_rel)
    with ws.session() as s:  # what a finished bet run registers
        s.add(File(relpath=brain_rel, kind="bet"))
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": brain_rel}, {})
    with pytest.raises(StepError) as info:
        execute_step(step, ctx)
    assert info.value.code == "ANAT_NEEDS_ORIGINAL_T1"
    assert "original T1" in info.value.suggested_action
    assert not any(ctx.output_dir.glob("*.anat"))  # nothing was started


def test_warns_when_name_suggests_brain_extraction(ws: Workspace) -> None:
    rel = "rawbids/sub-001/anat/sub-001_T1w_brain.nii.gz"
    put_nifti(ws, rel)
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": rel}, {})
    problems = step.validate_inputs(ctx)
    assert [p.code for p in problems] == ["ANAT_INPUT_MAY_BE_BRAIN_EXTRACTED"]
    assert problems[0].severity == "warning"


def test_not_a_nifti_is_refused(ws: Workspace) -> None:
    bad = ws.root / T1_REL
    bad.parent.mkdir(parents=True)
    bad.write_text("not an image")
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    assert [p.code for p in step.validate_inputs(ctx)] == ["INPUT_NOT_NIFTI"]


def test_command_line_is_built_from_the_settings(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_nifti(ws, T1_REL)
    step, ctx = build_context(
        ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {"image_type": "T2", "strong_bias": True}
    )
    seen: list[list[str]] = []
    monkeypatch.setattr(type(ctx), "run_command", lambda self, argv, check=True: seen.append(argv))
    monkeypatch.setattr(type(step), "_publish_bids_results", lambda *a, **k: None)
    step.run(ctx)
    assert seen[0][:3] == ["fsl_anat", "-i", str(ws.root / T1_REL)]
    assert seen[0][3] == "-o" and seen[0][4] == str(ctx.output_dir / "sub-001_T1w")
    assert seen[0][5:] == ["-t", "T2", "--strongbias", "--nosubcortseg"]
    default_step, default_ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    seen.clear()
    default_step.run(default_ctx)
    assert seen[0][5:] == ["--nosubcortseg"]  # the default; and --nobet is never used
    seen.clear()
    first_step, first_ctx = build_context(
        ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {"subcortical_segmentation": True}
    )
    first_step.run(first_ctx)
    assert len(seen[0]) == 5  # opting in adds no flag (fsl_anat runs FIRST by itself)


def test_bids_results_are_linked_to_native_files_and_labels_written(ws: Workspace) -> None:
    put_nifti(ws, T1_REL)
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    native = ctx.output_dir / NATIVE
    native.mkdir(parents=True)
    for field, name in NATIVE_FILES.items():
        if field != "subcortical_segmentation":
            (native / name).write_text(f"data of {name}")
    step._publish_bids_results(ctx, native)  # type: ignore[attr-defined]
    out = step.expected_outputs(ctx)
    assert (ctx.output_dir / out.brain_mask).read_text() == "data of T1_biascorr_brain_mask.nii.gz"
    assert os.path.samefile(ctx.output_dir / out.brain, native / "T1_biascorr_brain.nii.gz")
    assert (native / "T1_biascorr_brain.nii.gz").exists()  # the native folder stays intact
    table = (ctx.output_dir / out.segmentation_labels).read_text().splitlines()
    assert table == ["index\tname", "1\tCSF", "2\tGM", "3\tWM"]
    assert step.validate_outputs(ctx) == []


def test_prepare_removes_only_the_leftover_anat_folder(ws: Workspace) -> None:
    put_nifti(ws, T1_REL)
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    (ctx.output_dir / NATIVE).mkdir(parents=True)
    (ctx.output_dir / NATIVE / "partial.nii.gz").write_text("half done")
    (ctx.output_dir / "keep.txt").write_text("keep")
    step.prepare(ctx)
    assert not (ctx.output_dir / NATIVE).exists()
    assert (ctx.output_dir / "keep.txt").exists() and (ws.root / T1_REL).exists()
    assert ctx.run_dir.is_dir() and ctx.log_dir.is_dir()


# -- real FSL ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def fsl() -> FslInstall:
    try:
        return find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")


@pytest.fixture(scope="module")
def t1_source() -> Path:
    base = Path(os.environ.get("MRFORGE_TEST_DATA", "~/Documents/mri-test-data")).expanduser()
    path = base / "nifti" / "t1w.nii.gz"
    if not path.is_file():
        pytest.skip(f"test T1 not found: {path}")
    return path


@pytest.fixture
def real_ws(tmp_path: Path, t1_source: Path, fsl: FslInstall) -> Workspace:
    w = Workspace.create(tmp_path / "ws")
    dest = w.root / T1_REL
    dest.parent.mkdir(parents=True)
    shutil.copy(t1_source, dest)
    return w


def fsl_run(fsl: FslInstall, *argv: str) -> str:
    return subprocess.run(argv, capture_output=True, text=True, env=fsl.env, check=True).stdout


def max_abs_difference(fsl: FslInstall, a: Path, b: Path, scratch: Path) -> float:
    diff = scratch / "diff.nii.gz"
    fsl_run(fsl, "fslmaths", str(a), "-sub", str(b), "-abs", str(diff))
    return float(fsl_run(fsl, "fslstats", str(diff), "-R").split()[1])


def find_fsl_anat_process(worker_pid: int) -> psutil.Process | None:
    for child in psutil.Process(worker_pid).children(recursive=True):
        if "fsl_anat" in " ".join(child.cmdline()):
            return child
    return None


def _in_group(proc: psutil.Process, pgid: int) -> bool:
    try:
        return proc.pid != 0 and os.getpgid(proc.pid) == pgid
    except (ProcessLookupError, PermissionError, psutil.Error):
        return False


@pytest.mark.fsl
@pytest.mark.slow
def test_kill_during_fsl_anat_is_interrupted_and_leaves_no_orphans(
    real_ws: Workspace, fsl: FslInstall
) -> None:
    ws = real_ws
    queue = LocalJobQueue(ws)
    job_id = create_job(ws, "fsl_anat", "sub-001", {"t1": T1_REL})
    queue.submit(job_id)
    deadline = time.monotonic() + 120
    victim: psutil.Process | None = None
    while time.monotonic() < deadline and victim is None:
        job = get_job(ws, job_id)
        if job.status == "Running" and job.pid:
            victim = find_fsl_anat_process(job.pid)
        time.sleep(0.5)
    assert victim is not None, "fsl_anat never started"
    native = ws.root / ANAT / NATIVE
    while not (native / "T1_orig.nii.gz").exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    time.sleep(15)  # let it get into the real work
    worker_pid = get_job(ws, job_id).pid
    assert worker_pid
    victim.kill()  # kill -9 the fsl_anat script
    assert queue.wait(timeout=120)
    job = get_job(ws, job_id)
    assert job.status == JobStatus.INTERRUPTED.value and job.error_code == "COMMAND_KILLED"
    assert native.is_dir()  # a partial result exists...
    time.sleep(1)
    leftovers = [p for p in psutil.process_iter() if _in_group(p, worker_pid)]
    assert leftovers == []  # ...but no stray FSL processes keep running
    prov = read_provenance(ws.root / ANAT / "_runs" / "fsl_anat")
    assert prov and prov.status == "Interrupted"

    # Running again must start from a clean folder (decision: restart from the beginning).
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    assert not any(step.validate_inputs(ctx))
    step.prepare(ctx)
    assert not (ctx.output_dir / NATIVE).exists()


@pytest.mark.fsl
@pytest.mark.slow
def test_full_run_matches_manual_fsl_anat(
    real_ws: Workspace, fsl: FslInstall, tmp_path: Path
) -> None:
    ws = real_ws
    reference = os.environ.get("MRFORGE_ANAT_REFERENCE")  # an existing manual .anat folder
    if reference:
        manual = Path(reference)
    else:
        fsl_run(fsl, "fsl_anat", "-i", str(ws.root / T1_REL), "-o", str(tmp_path / "manual"))
        manual = tmp_path / "manual.anat"

    queue = LocalJobQueue(ws)
    outcome = run_step(ws, queue, "fsl_anat", "sub-001", {"t1": T1_REL})
    assert outcome.action == Action.RAN, outcome.reason

    out = ws.root / ANAT
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    expected = step.expected_outputs(ctx)
    # every BIDS-named result is identical to the matching file of the manual run
    for field_name, native_name in NATIVE_FILES.items():
        bids_file = getattr(expected, field_name)
        if bids_file is None:
            assert not (out / NATIVE / native_name).exists()  # opt-in extra was not run
            continue
        if native_name.endswith(".mat"):
            assert (out / bids_file).read_text() == (manual / native_name).read_text()
        else:
            diff = max_abs_difference(fsl, out / bids_file, manual / native_name, tmp_path)
            assert diff == 0.0, f"{bids_file} differs from {native_name}"
            # and the native copy inside sub-001_T1w.anat/ is intact
            assert (out / NATIVE / native_name).is_file()
    assert (out / expected.segmentation_labels).is_file()

    prov = read_provenance(ws.root / ANAT / "_runs" / "fsl_anat")
    assert prov and prov.status == "Completed" and prov.tool_versions["fsl"] == fsl.version
    assert len(prov.outputs) == 13
    assert "--nosubcortseg" in prov.commands[0].argv
    assert run_step(ws, queue, "fsl_anat", "sub-001", {"t1": T1_REL}).action == Action.REUSED
