"""Stage 6c: removing the noise components (fsl_regfilt).

Unit tests need no FSL. The ``fsl`` tests run the real tool on a time series made of known
sources and compare the step with ``fsl_regfilt`` run by hand with the same list."""

import json
import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge.engine import Action, run_step
from mrforge.fsl_env import find_fsl
from mrforge.runner.jobs import build_context
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001/func"
BOLD = f"{D}/sub-001_task-rest_desc-preproc_bold.nii.gz"
MASK = f"{D}/sub-001_task-rest_desc-brain_mask.nii.gz"
MIX = f"{D}/sub-001_task-rest_desc-melodic_mixing.txt"
LABELS = f"{D}/sub-001_task-rest_desc-icalabels_labels.json"
INPUTS = {"bold": BOLD, "mixing": MIX, "labels": LABELS, "brain_mask": MASK}
VOLUMES = 60


def make(
    tmp_path: Path, noise: list[int], volumes: int = VOLUMES, mix_volumes: int | None = None
) -> Workspace:
    """Three sources in three blobs; component 2 (a fast wave) is the one to remove."""
    rng = np.random.default_rng(3)
    ws = Workspace.create(tmp_path / "ws")
    t = np.arange(volumes)
    courses = np.stack([np.sin(t / 5.0), np.sin(t * 1.9), np.cos(t / 9.0)], axis=1)
    data = rng.standard_normal((12, 12, 6, volumes)) * 0.05 + 100
    for k, x in enumerate((2, 6, 10)):
        data[x - 1 : x + 2, 5:8, 2:4, :] += 3 * courses[:, k]
    folder = ws.root / D
    folder.mkdir(parents=True)
    img = nib.Nifti1Image(data.astype("float32"), np.eye(4))
    img.header.set_zooms((1, 1, 1, 2.0))
    nib.save(img, ws.root / BOLD)
    nib.save(nib.Nifti1Image(np.ones((12, 12, 6), "float32"), np.eye(4)), ws.root / MASK)
    mix = courses if mix_volumes is None else courses[:mix_volumes]
    np.savetxt(ws.root / MIX, mix)
    (ws.root / LABELS).write_text(json.dumps({"noise_components": noise, "n_components": 3}))
    ws.get_or_create_subject("sub-001")
    return ws


def validate(ws: Workspace):  # type: ignore[no-untyped-def]
    step, ctx = build_context(ws, "regfilt", "sub-001", None, INPUTS, {})
    return step.validate_inputs(ctx)


def test_matching_inputs_are_accepted(tmp_path: Path) -> None:
    assert validate(make(tmp_path, [2])) == []


def test_time_courses_of_another_image_are_refused(tmp_path: Path) -> None:
    found = validate(make(tmp_path, [2], mix_volumes=40))
    assert found and found[0].code == "MIXING_MISMATCH" and found[0].suggested_action


def test_labels_for_components_that_do_not_exist_are_refused(tmp_path: Path) -> None:
    found = validate(make(tmp_path, [7]))
    assert found and found[0].code == "LABELS_MISMATCH"


def test_without_noise_components_the_input_is_passed_on_unchanged(tmp_path: Path) -> None:
    ws = make(tmp_path, [])
    result = run_step(ws, LocalJobQueue(ws), "regfilt", "sub-001", INPUTS, {})
    assert result.action == Action.RAN, result.reason
    step, ctx = build_context(ws, "regfilt", "sub-001", None, INPUTS, {})
    out = step.expected_outputs(ctx)
    assert (ctx.output_dir / out.cleaned_bold).read_bytes() == (ws.root / BOLD).read_bytes()
    metrics = json.loads((ctx.output_dir / out.metrics).read_text())
    assert metrics["n_removed"] == 0 and metrics["variance_removed_pct"] == 0.0


@pytest.mark.fsl
def test_the_step_matches_fsl_regfilt_run_by_hand(tmp_path: Path) -> None:
    ws = make(tmp_path, [2])
    result = run_step(ws, LocalJobQueue(ws), "regfilt", "sub-001", INPUTS, {})
    assert result.action == Action.RAN, result.reason
    step, ctx = build_context(ws, "regfilt", "sub-001", None, INPUTS, {})
    out = step.expected_outputs(ctx)
    ours = np.asarray(nib.load(ctx.output_dir / out.cleaned_bold).dataobj)

    manual = tmp_path / "manual.nii.gz"
    subprocess.run(
        ["fsl_regfilt", "-i", str(ws.root / BOLD), "-d", str(ws.root / MIX), "-f", "2",
         "-m", str(ws.root / MASK), "-o", str(manual)],
        check=True, capture_output=True, env=find_fsl().env,
    )  # fmt: skip
    theirs = np.asarray(nib.load(manual).dataobj)
    assert np.array_equal(ours, theirs)  # identical, not just close

    metrics = json.loads((ctx.output_dir / out.metrics).read_text())
    assert metrics["noise_components"] == [2] and metrics["variance_removed_pct"] > 5
    assert (ctx.output_dir / out.picture).stat().st_size > 5000
    # The removed component's wave is gone from its blob, the others are kept.
    blob = lambda arr, x: arr[x, 6, 3, :]  # noqa: E731
    original = np.asarray(nib.load(ws.root / BOLD).dataobj)
    assert np.std(blob(ours, 6)) < 0.2 * np.std(blob(original, 6))
    assert np.std(blob(ours, 2)) > 0.8 * np.std(blob(original, 2))


@pytest.mark.fsl
def test_aggressive_mode_removes_at_least_as_much_as_the_default(tmp_path: Path) -> None:
    ws = make(tmp_path, [2])
    removed = {}
    for mode in (False, True):
        params = {"aggressive": mode}
        result = run_step(ws, LocalJobQueue(ws), "regfilt", "sub-001", INPUTS, params)
        assert result.action == Action.RAN, result.reason
        step, ctx = build_context(ws, "regfilt", "sub-001", None, INPUTS, params)
        path = ctx.output_dir / step.expected_outputs(ctx).metrics
        removed[mode] = json.loads(path.read_text())
    assert removed[True]["mode"] == "aggressive"
    assert removed[True]["variance_removed_pct"] >= removed[False]["variance_removed_pct"]
