"""Real-FSL tests for BetStep (run with: pytest -m fsl). They are skipped, and the skip is
reported, when FSL or the test T1 is not available."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from mrforge.engine import Action, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import FslInstall, find_fsl
from mrforge.provenance import read_provenance
from mrforge.runner.jobs import get_job
from mrforge.runner.local import LocalJobQueue
from mrforge.workspace import Workspace

pytestmark = pytest.mark.fsl

T1_REL = "rawbids/sub-001/anat/sub-001_T1w.nii.gz"


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
def ws(tmp_path: Path, t1_source: Path, fsl: FslInstall) -> Workspace:
    w = Workspace.create(tmp_path / "ws")
    dest = w.root / T1_REL
    dest.parent.mkdir(parents=True)
    shutil.copy(t1_source, dest)
    return w


def fsl_run(fsl: FslInstall, *argv: str) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, env=fsl.env, check=True)
    return done.stdout.strip()


def max_abs_difference(fsl: FslInstall, a: Path, b: Path, tmp: Path) -> float:
    diff = tmp / "diff.nii.gz"
    fsl_run(fsl, "fslmaths", str(a), "-sub", str(b), "-abs", str(diff))
    low, high = fsl_run(fsl, "fslstats", str(diff), "-R").split()
    assert float(low) == 0.0
    return float(high)


@pytest.mark.parametrize("flags", [[], ["-R"]], ids=["default", "robust"])
def test_bet_matches_manual_run(
    ws: Workspace, fsl: FslInstall, tmp_path: Path, flags: list[str]
) -> None:
    queue = LocalJobQueue(ws)
    label = "robust" if flags else "default"
    outcome = run_step(
        ws, queue, "bet", "sub-001", {"t1": T1_REL}, {"robust": bool(flags)}, label=label
    )
    assert outcome.action == Action.RAN, outcome.reason

    manual = tmp_path / "manual"
    manual.mkdir()
    fsl_run(fsl, "bet", str(ws.root / T1_REL), str(manual / "brain"), "-f", "0.5", *flags, "-m")

    out = ws.derivatives_dir / "sub-001" / label
    assert max_abs_difference(fsl, out / "brain.nii.gz", manual / "brain.nii.gz", tmp_path) == 0.0
    assert (
        max_abs_difference(fsl, out / "brain_mask.nii.gz", manual / "brain_mask.nii.gz", tmp_path)
        == 0.0
    )


def test_bet_provenance_and_resume(ws: Workspace, fsl: FslInstall) -> None:
    queue = LocalJobQueue(ws)
    first = run_step(ws, queue, "bet", "sub-001", {"t1": T1_REL})
    prov = read_provenance(ws.derivatives_dir / "sub-001" / "bet")
    assert prov and prov.status == "Completed"
    assert prov.tool_versions["fsl"] == fsl.version
    argv = prov.commands[0].argv
    assert argv[0] == "bet" and argv[-3:] == ["-f", "0.5", "-m"]
    assert [f.path for f in prov.outputs] == [
        "derivatives/mrforge/sub-001/bet/brain.nii.gz",
        "derivatives/mrforge/sub-001/bet/brain_mask.nii.gz",
    ]
    again = run_step(ws, queue, "bet", "sub-001", {"t1": T1_REL})
    assert again.action == Action.REUSED and again.job_id == first.job_id
    changed = run_step(ws, queue, "bet", "sub-001", {"t1": T1_REL}, {"frac": 0.3})
    assert changed.action == Action.RAN and "settings changed" in changed.reason


def test_bet_without_mask_registers_only_brain(ws: Workspace) -> None:
    queue = LocalJobQueue(ws)
    outcome = run_step(ws, queue, "bet", "sub-001", {"t1": T1_REL}, {"mask": False})
    assert outcome.action == Action.RAN
    out = ws.derivatives_dir / "sub-001" / "bet"
    assert (out / "brain.nii.gz").is_file() and not (out / "brain_mask.nii.gz").exists()


def test_bad_input_gives_plain_language_failure(ws: Workspace) -> None:
    bad = ws.root / "rawbids" / "sub-001" / "anat" / "bad.nii.gz"
    bad.write_text("not an image")
    queue = LocalJobQueue(ws)
    outcome = run_step(ws, queue, "bet", "sub-001", {"t1": "rawbids/sub-001/anat/bad.nii.gz"})
    assert outcome.action == Action.FAILED
    job = get_job(ws, outcome.job_id or 0)
    assert job.error_code == "INPUT_NOT_NIFTI"
    assert job.error_message and "What to do:" in job.error_message


def test_missing_input_gives_plain_language_failure(ws: Workspace) -> None:
    queue = LocalJobQueue(ws)
    outcome = run_step(ws, queue, "bet", "sub-001", {"t1": "rawbids/sub-001/anat/nope.nii.gz"})
    assert outcome.action == Action.FAILED
    assert get_job(ws, outcome.job_id or 0).error_code == "INPUT_MISSING"
