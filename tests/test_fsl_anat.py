"""FslAnatStep tests.

Unit tests (no FSL) check the guards and the command line. Real-FSL tests are marked
``fsl``; the ones that run fsl_anat for many minutes are also marked ``slow``:

    pytest -m "fsl and not slow"     # quick FSL checks
    pytest -m "fsl and slow"         # full fsl_anat runs (about 25 minutes each)
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import psutil
import pytest

from mrforge.engine import Action, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import FslInstall, find_fsl
from mrforge.models import JobStatus
from mrforge.provenance import read_provenance
from mrforge.runner.jobs import build_context, create_job, get_job
from mrforge.runner.local import LocalJobQueue
from mrforge.steps.base import execute_step
from mrforge.steps.fsl_anat import ANAT_DIR, FslAnatOutput
from mrforge.workspace import Workspace

T1_REL = "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
OUT = "derivatives/mrforge/sub-001"


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def put_nifti(ws: Workspace, rel: str) -> None:
    import gzip
    import struct

    path = ws.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(struct.pack("<i", 348) + b"\0" * 400)


# -- unit tests: no FSL needed ----------------------------------------------------


def test_refuses_bet_output_as_input(ws: Workspace) -> None:
    put_nifti(ws, T1_REL)
    bet_dir = ws.derivatives_dir / "sub-001" / "bet"
    bet_dir.mkdir(parents=True)
    brain = bet_dir / "brain.nii.gz"
    shutil.copy(ws.root / T1_REL, brain)
    # a real bet run leaves provenance next to its outputs
    from mrforge.provenance import Provenance, StepRef, write_provenance

    write_provenance(
        bet_dir,
        Provenance(
            step=StepRef(name="bet", version="1"), job_id=1, subject="sub-001", parameters={},
            parameter_hash="x", inputs=[], outputs=[], commands=[], tool_versions={},
            started=None, finished=None, status="Completed",
        ),
    )  # fmt: skip
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": ws.relpath(brain)}, {})
    with pytest.raises(StepError) as info:
        execute_step(step, ctx)
    assert info.value.code == "ANAT_NEEDS_ORIGINAL_T1"
    assert "original T1" in info.value.suggested_action
    assert not (ctx.output_dir / ANAT_DIR).exists()  # nothing was started


def test_warns_when_name_suggests_brain_extraction(ws: Workspace) -> None:
    put_nifti(ws, "rawbids/sub-001/anat/sub-001_T1w_brain.nii.gz")
    step, ctx = build_context(
        ws, "fsl_anat", "sub-001", None, {"t1": "rawbids/sub-001/anat/sub-001_T1w_brain.nii.gz"}, {}
    )
    problems = step.validate_inputs(ctx)
    assert [p.code for p in problems] == ["ANAT_INPUT_MAY_BE_BRAIN_EXTRACTED"]
    assert problems[0].severity == "warning"


def test_not_a_nifti_is_refused(ws: Workspace) -> None:
    bad = ws.root / T1_REL
    bad.parent.mkdir(parents=True)
    bad.write_text("not an image")
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    assert [p.code for p in step.validate_inputs(ctx)] == ["INPUT_NOT_NIFTI"]


def test_outputs_follow_the_subcortical_option(ws: Workspace) -> None:
    put_nifti(ws, T1_REL)
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    out = step.output_relpaths(ctx)  # default: subcortical segmentation is off
    assert not any("subcort" in p for p in out) and len(out) == 12
    step, ctx = build_context(
        ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {"subcortical_segmentation": True}
    )
    assert any("T1_subcort_seg" in p for p in step.output_relpaths(ctx))
    assert all(p.startswith(f"{OUT}/fsl_anat/{ANAT_DIR}/") for p in out)


def test_command_line_is_built_from_the_settings(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_nifti(ws, T1_REL)
    step, ctx = build_context(
        ws,
        "fsl_anat",
        "sub-001",
        None,
        {"t1": T1_REL},
        {"image_type": "T2", "strong_bias": True},
    )
    seen: list[list[str]] = []
    monkeypatch.setattr(type(ctx), "run_command", lambda self, argv, check=True: seen.append(argv))
    step.run(ctx)
    assert seen[0][:2] == ["fsl_anat", "-i"]
    assert seen[0][3] == "-o" and seen[0][4].endswith("fsl_anat/anat")
    assert seen[0][5:] == ["-t", "T2", "--strongbias", "--nosubcortseg"]
    default_step, default_ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    seen.clear()
    default_step.run(default_ctx)
    assert seen[0][5:] == ["--nosubcortseg"]  # the default; and --nobet is never used
    seen.clear()
    with_first, with_first_ctx = build_context(
        ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {"subcortical_segmentation": True}
    )
    with_first.run(with_first_ctx)
    assert len(seen[0]) == 5  # opting in adds no flag (fsl_anat runs FIRST by itself)


def test_prepare_removes_only_the_leftover_anat_folder(ws: Workspace) -> None:
    put_nifti(ws, T1_REL)
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    (ctx.output_dir / ANAT_DIR).mkdir(parents=True)
    (ctx.output_dir / ANAT_DIR / "partial.nii.gz").write_text("half done")
    (ctx.output_dir / "keep.txt").write_text("keep")
    step.prepare(ctx)
    assert not (ctx.output_dir / ANAT_DIR).exists()
    assert (ctx.output_dir / "keep.txt").exists() and (ws.root / T1_REL).exists()


def test_output_spec_field_names_are_stable() -> None:
    assert {"brain", "brain_mask", "to_mni_warp", "from_mni_warp", "segmentation"} <= set(
        FslAnatOutput.model_fields
    )


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
    anat = ws.derivatives_dir / "sub-001" / "fsl_anat" / ANAT_DIR
    while not (anat / "T1_orig.nii.gz").exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    time.sleep(15)  # let it get into the real work
    worker_pid = get_job(ws, job_id).pid
    assert worker_pid
    victim.kill()  # kill -9 the fsl_anat script
    assert queue.wait(timeout=120)
    job = get_job(ws, job_id)
    assert job.status == JobStatus.INTERRUPTED.value and job.error_code == "COMMAND_KILLED"
    assert anat.is_dir()  # a partial result exists...
    time.sleep(1)
    leftovers = [p for p in psutil.process_iter() if _in_group(p, worker_pid)]
    assert leftovers == []  # ...but no stray FSL processes keep running
    prov = read_provenance(anat.parent)
    assert prov and prov.status == "Interrupted"

    # Running again must start from a clean folder (decision: restart from the beginning).
    step, ctx = build_context(ws, "fsl_anat", "sub-001", None, {"t1": T1_REL}, {})
    assert not any(step.validate_inputs(ctx))
    step.prepare(ctx)
    assert not (ctx.output_dir / ANAT_DIR).exists()


def _in_group(proc: psutil.Process, pgid: int) -> bool:
    try:
        return proc.pid != 0 and os.getpgid(proc.pid) == pgid
    except (ProcessLookupError, PermissionError, psutil.Error):
        return False


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

    out = ws.derivatives_dir / "sub-001" / "fsl_anat" / ANAT_DIR
    expected = FslAnatOutput(subcortical_segmentation=None)  # the default run skips FIRST
    for _field, rel in expected:
        if rel is None or rel.endswith(".mat"):
            continue
        name = Path(rel).name
        assert max_abs_difference(fsl, out / name, manual / name, tmp_path) == 0.0, name
    for rel_mat in (r for _, r in expected if r and r.endswith(".mat")):
        assert (out / Path(rel_mat).name).read_text() == (manual / Path(rel_mat).name).read_text()

    prov = read_provenance(out.parent)
    assert prov and prov.status == "Completed" and prov.tool_versions["fsl"] == fsl.version
    assert len(prov.outputs) == 12
    assert not (out / "T1_subcort_seg.nii.gz").exists()  # opt-in extra was not run
    assert "--nosubcortseg" in prov.commands[0].argv
    again = run_step(ws, queue, "fsl_anat", "sub-001", {"t1": T1_REL})
    assert again.action == Action.REUSED
