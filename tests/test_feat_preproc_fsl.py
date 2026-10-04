"""Real-FSL tests for the FEAT preprocessing step (``pytest -m fsl``). They use a 20-volume cut
of the real test session; they are skipped, and the skip is reported, when the prepared
workspace ``func-test`` (see docs/TEST_DATA.md) or FSL is not available."""

import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import psutil
import pytest

from mrforge.engine import Action, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import FslInstall, find_fsl
from mrforge.runner.jobs import create_job, get_job
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.workspace import Workspace

pytestmark = [pytest.mark.fsl, pytest.mark.realdata, pytest.mark.slow]

SOURCE = Path(
    os.environ.get("MRFORGE_FUNC_WORKSPACE", "~/Documents/mrforge-workspaces/func-test")
).expanduser()
D = "derivatives/mrforge/sub-001"
BOLD = "rawbids/sub-001/func/sub-001_task-rest_bold.nii.gz"
INPUTS = {
    "bold": BOLD,
    "t1_head": f"{D}/anat/sub-001_desc-biascorr_T1w.nii.gz",
    "t1_brain": f"{D}/anat/sub-001_desc-brain_T1w.nii.gz",
    "t1_seg": f"{D}/anat/sub-001_dseg.nii.gz",
    "fieldmap": f"{D}/fmap/sub-001_desc-prepared_fieldmap.nii.gz",
    "fieldmap_magnitude_brain": f"{D}/fmap/sub-001_desc-brain_magnitude1.nii.gz",
    "fieldmap_magnitude": "rawbids/sub-001/fmap/sub-001_magnitude1.nii.gz",
}


@pytest.fixture(scope="module")
def fsl() -> FslInstall:
    try:
        return find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")


@pytest.fixture
def ws(tmp_path: Path, fsl: FslInstall) -> Workspace:
    if not (SOURCE / BOLD).is_file() or not (SOURCE / INPUTS["fieldmap"]).is_file():
        pytest.skip(f"prepared test workspace not found: {SOURCE}")
    w = Workspace.create(tmp_path / "ws")
    for rel in set(INPUTS.values()) - {BOLD}:
        (w.root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / rel, w.root / rel)
    (w.root / BOLD).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["fslroi", str(SOURCE / BOLD), str(w.root / BOLD), "0", "20"], env=fsl.env, check=True
    )
    shutil.copy2(
        SOURCE / BOLD.replace(".nii.gz", ".json"), w.root / BOLD.replace(".nii.gz", ".json")
    )
    return w


def feat_dir(ws: Workspace) -> Path:
    return ws.derivatives_dir / "sub-001" / "func" / "sub-001_task-rest_bold.feat"


def test_matches_a_manual_feat_run_of_the_same_design(
    ws: Workspace, fsl: FslInstall, tmp_path: Path
) -> None:
    outcome = run_step(ws, LocalJobQueue(ws), "feat_preproc", "sub-001", INPUTS, {})
    assert outcome.action == Action.RAN, outcome.reason
    func = ws.derivatives_dir / "sub-001" / "func"
    # key results have BIDS names; the 4D result is a hard link into the FEAT folder
    preproc = func / "sub-001_task-rest_desc-preproc_bold.nii.gz"
    assert preproc.stat().st_ino == (feat_dir(ws) / "filtered_func_data.nii.gz").stat().st_ino
    assert (
        len(list((func / "sub-001_task-rest_desc-motion_timeseries.tsv").read_text().split("\n")))
        == 17
    )
    assert (
        func / "sub-001_task-rest_from-boldref_to-T1w_mode-image_desc-warp_xfm.nii.gz"
    ).is_file()
    assert not list(func.glob("*+.feat"))  # FEAT never wrote a second folder

    # "the same operation by hand": run FEAT on MRForge's own design file, elsewhere
    design = func / "_runs" / "feat_preproc" / "design.fsf"
    assert design.is_file() or (feat_dir(ws) / "design_mrforge.fsf").is_file()
    text = (feat_dir(ws) / "design_mrforge.fsf").read_text()
    manual_out = tmp_path / "manual" / "result"
    manual_out.parent.mkdir()
    text = re.sub(r"(set fmri\(outputdir\) ).*", rf'\1"{manual_out}"', text)
    # the staged T1/fieldmap files are gone after the run; point the design at the originals
    stage = ws.root / "manual_stage"
    stage.mkdir()
    for name, rel in (("T1", INPUTS["t1_head"]), ("T1_brain", INPUTS["t1_brain"]),
                      ("fmap_rads", INPUTS["fieldmap"]),
                      ("fmap_mag_brain", INPUTS["fieldmap_magnitude_brain"]),
                      ("fmap_mag", INPUTS["fieldmap_magnitude"])):  # fmt: skip
        shutil.copy2(ws.root / rel, stage / f"{name}.nii.gz")
    subprocess.run(["fslmaths", str(ws.root / INPUTS["t1_seg"]), "-thr", "3", "-uthr", "3",
                    "-bin", str(stage / "T1_wmseg")], env=fsl.env, check=True)  # fmt: skip
    text = re.sub(r'"[^"]*/stage/', f'"{stage}/', text)
    (tmp_path / "manual.fsf").write_text(text)
    subprocess.run(["feat", str(tmp_path / "manual.fsf")], env=fsl.env, check=True)

    diff = tmp_path / "diff.nii.gz"
    manual = tmp_path / "manual" / "result.feat" / "filtered_func_data.nii.gz"
    subprocess.run(["fslmaths", str(preproc), "-sub", str(manual), "-abs", str(diff)],
                   env=fsl.env, check=True)  # fmt: skip
    top = subprocess.run(["fslstats", str(diff), "-R"], env=fsl.env, capture_output=True,
                         text=True, check=True).stdout.split()[1]  # fmt: skip
    assert float(top) == 0.0

    # the same inputs and settings again: nothing runs
    again = run_step(ws, LocalJobQueue(ws), "feat_preproc", "sub-001", INPUTS, {})
    assert again.action == Action.REUSED


def test_killed_feat_is_interrupted_and_resume_runs_it_cleanly(ws: Workspace) -> None:
    queue = LocalJobQueue(ws)
    job_id = create_job(ws, "feat_preproc", "sub-001", INPUTS, {})
    queue.submit(job_id)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = get_job(ws, job_id)
        if job.pid and any(
            "feat" in " ".join(c.cmdline())
            for c in psutil.Process(job.pid).children(recursive=True)
            if c.is_running()
        ):
            break
        time.sleep(0.2)
    else:
        pytest.fail("FEAT never started")
    job = get_job(ws, job_id)
    assert job.pid is not None
    os.kill(job.pid, signal.SIGKILL)
    assert queue.wait(timeout=60)
    assert get_job(ws, job_id).status == "Interrupted"

    outcome = run_step(ws, LocalJobQueue(ws), "feat_preproc", "sub-001", INPUTS, {})
    assert outcome.action == Action.RAN, outcome.reason
    func = ws.derivatives_dir / "sub-001" / "func"
    assert (feat_dir(ws) / "filtered_func_data.nii.gz").is_file()
    assert not list(func.glob("*+.feat"))
