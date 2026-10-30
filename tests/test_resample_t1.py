"""ResampleT1Step tests. Unit tests need no FSL; the ``fsl`` test compares with a manual flirt run."""

import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge.engine import Action, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import FslInstall, find_fsl
from mrforge.niftiutil import image_info
from mrforge.runner.jobs import build_context
from mrforge.runner.local import LocalJobQueue
from mrforge.steps.resample_t1 import needs_resampling
from mrforge.workspace import Workspace

T1_REL = "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
RESULT = "derivatives/mrforge/sub-001/anat/sub-001_desc-1mm_T1w.nii.gz"


def put_image(ws: Workspace, zooms: tuple[float, ...], shape: tuple[int, ...]) -> Path:
    rng = np.random.default_rng(1)
    data = rng.random(shape).astype(np.float32) * 100
    affine = np.diag([*zooms[:3], 1.0])
    path = ws.root / T1_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, affine), path)  # type: ignore[attr-defined]
    return path


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def test_needs_resampling_only_when_a_side_is_finer() -> None:
    assert needs_resampling((0.3, 0.3, 1.0))
    assert needs_resampling((1.0, 1.0, 0.8))
    assert not needs_resampling((1.0, 1.0, 1.0))
    assert not needs_resampling((0.9999999, 1.0, 1.0))
    assert not needs_resampling((1.2, 1.2, 1.2))
    assert not needs_resampling((2.0, 2.0, 2.0, 2.0))  # fourth value is not spatial


def test_result_name_is_bids_with_desc(ws: Workspace) -> None:
    put_image(ws, (0.5, 0.5, 0.5), (8, 8, 8))
    step, ctx = build_context(ws, "resample_t1", "sub-001", None, {"t1": T1_REL}, {})
    assert step.expected_outputs(ctx).result == "sub-001_desc-1mm_T1w.nii.gz"  # type: ignore[attr-defined]


def test_rejects_a_time_series(ws: Workspace) -> None:
    put_image(ws, (0.5, 0.5, 0.5, 2.0), (8, 8, 8, 5))
    step, ctx = build_context(ws, "resample_t1", "sub-001", None, {"t1": T1_REL}, {})
    assert [p.code for p in step.validate_inputs(ctx)] == ["INPUT_NOT_3D"]


@pytest.mark.fsl
def test_resample_matches_manual_flirt(ws: Workspace, tmp_path: Path) -> None:
    try:
        fsl = find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")
    assert isinstance(fsl, FslInstall)
    src = put_image(ws, (0.5, 0.5, 0.75), (40, 40, 30))
    outcome = run_step(ws, LocalJobQueue(ws), "resample_t1", "sub-001", {"t1": T1_REL})
    assert outcome.action == Action.RAN, outcome.reason

    manual = tmp_path / "manual.nii.gz"
    subprocess.run(
        ["flirt", "-in", str(src), "-ref", str(src), "-out", str(manual),
         "-applyisoxfm", "1", "-interp", "spline"],
        env=fsl.env, check=True, capture_output=True,
    )  # fmt: skip
    got = nib.load(ws.root / RESULT)  # type: ignore[attr-defined]
    want = nib.load(manual)  # type: ignore[attr-defined]
    assert got.shape == want.shape
    assert np.array_equal(np.asanyarray(got.dataobj), np.asanyarray(want.dataobj))
    assert image_info(ws.root / RESULT)[1][:3] == pytest.approx((1.0, 1.0, 1.0))

    again = run_step(ws, LocalJobQueue(ws), "resample_t1", "sub-001", {"t1": T1_REL})
    assert again.action == Action.REUSED
