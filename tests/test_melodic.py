"""Stage 6a: MELODIC (independent components) and the per-component pictures.

Unit tests need no FSL. The ``fsl`` test runs real MELODIC on a synthetic time series with
three known sources, and compares the step with MELODIC run by hand on the same data."""

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge.engine import Action, run_step
from mrforge.runner.jobs import build_context
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.icapics import draw_component, spaced_slices
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001/func"
BOLD = f"{D}/sub-001_task-rest_desc-preproc_bold.nii.gz"
MASK = f"{D}/sub-001_task-rest_desc-brain_mask.nii.gz"
INPUTS = {"bold": BOLD, "brain_mask": MASK}


def synthetic(
    tmp_path: Path, volumes: int = 120, shape: tuple[int, int, int] = (20, 20, 10)
) -> Workspace:
    """A time series with three blobs, each with its own time course, plus noise."""
    rng = np.random.default_rng(1)
    ws = Workspace.create(tmp_path / "ws")
    t = np.arange(volumes)
    courses = [np.sin(t / 3.0), np.sign(np.sin(t / 11.0)), rng.standard_normal(volumes)]
    data = rng.standard_normal((*shape, volumes)) * 0.3 + 100
    centres = [(5, 5, 5), (14, 5, 5), (10, 14, 5)]
    for (x, y, z), course in zip(centres, courses, strict=True):
        data[x - 2 : x + 3, y - 2 : y + 3, z - 2 : z + 3, :] += 3 * course
    for rel, array in ((BOLD, data), (MASK, np.ones(shape))):
        path = ws.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        img = nib.Nifti1Image(array.astype("float32"), np.eye(4))
        if array.ndim == 4:
            img.header.set_zooms((1, 1, 1, 2.0))
        nib.save(img, path)
    return ws


def problems(ws: Workspace):  # type: ignore[no-untyped-def]
    step, ctx = build_context(ws, "melodic", "sub-001", None, INPUTS, {})
    return step.validate_inputs(ctx)


def test_a_run_that_is_too_short_is_explained(tmp_path: Path) -> None:
    found = problems(synthetic(tmp_path, volumes=10))
    assert found and found[0].code == "BOLD_TOO_SHORT_FOR_ICA"
    assert "at least" in found[0].message and found[0].suggested_action


def test_a_long_enough_run_is_accepted(tmp_path: Path) -> None:
    assert problems(synthetic(tmp_path)) == []


def test_slices_cover_the_brain_only() -> None:
    mask = np.zeros((6, 6, 20), dtype=bool)
    mask[:, :, 5:15] = True
    picks = spaced_slices(mask, 6)
    assert picks[0] == 5 and picks[-1] == 14 and len(picks) == 6


def test_a_component_picture_is_drawn(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    out = tmp_path / "c.png"
    mask = np.ones((10, 10, 6), dtype=bool)
    draw_component(
        rng.standard_normal((10, 10, 6)) * 4, rng.random((10, 10, 6)) + 1, mask,
        rng.standard_normal(80), np.abs(rng.standard_normal(40)), 2.0, 3, 10, out, 4.2,
    )  # fmt: skip
    assert out.stat().st_size > 5000


@pytest.mark.fsl
def test_melodic_finds_the_sources_and_matches_a_manual_run(tmp_path: Path) -> None:
    import json
    import subprocess

    from mrforge.fsl_env import find_fsl

    ws = synthetic(tmp_path)
    result = run_step(ws, LocalJobQueue(ws), "melodic", "sub-001", INPUTS, {})
    assert result.action == Action.RAN, result.reason
    step, ctx = build_context(ws, "melodic", "sub-001", None, INPUTS, {})
    out = step.expected_outputs(ctx)
    summary = json.loads((ctx.output_dir / out.summary).read_text())
    assert 2 <= summary["n_components"] <= 8
    assert all(ws.abspath(c["picture"]).is_file() for c in summary["components"])
    mix = np.loadtxt(ctx.output_dir / out.mixing, ndmin=2)
    assert mix.shape == (120, summary["n_components"])

    # Manual run with the same options. ICA starts from random values, so the result is not
    # bit-identical (largest difference seen on this data: 4e-4 on a unit-variance scale),
    # but every component must be found again with a time course correlation above 0.999.
    manual = tmp_path / "manual.ica"
    subprocess.run(
        ["melodic", "-i", str(ws.abspath(BOLD)), "-o", str(manual), "-m", str(ws.abspath(MASK)),
         "--tr=2", "--nobet", "--Oall"],
        check=True, capture_output=True, env=find_fsl().env,
    )  # fmt: skip
    manual_mix = np.loadtxt(manual / "melodic_mix", ndmin=2)
    assert manual_mix.shape == mix.shape
    corr = np.abs(np.corrcoef(mix.T, manual_mix.T)[: mix.shape[1], mix.shape[1] :])
    assert (corr.max(axis=1) > 0.999).all()
