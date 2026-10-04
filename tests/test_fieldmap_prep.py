"""Stage 5b: fieldmap preparation (unit tests, plus real-FSL tests marked ``fsl``)."""

import json
import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge.engine import Action, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import FslInstall, find_fsl
from mrforge.runner.jobs import build_context
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.base import Problem
from mrforge.steps.fieldmap_prep import echo_time_difference_ms
from mrforge.workspace import Workspace

MAG = "rawbids/sub-001/fmap/sub-001_magnitude1.nii.gz"
PHASE = "rawbids/sub-001/fmap/sub-001_phasediff.nii.gz"
INPUTS = {"magnitude1": MAG, "phasediff": PHASE}


def phantom(ws: Workspace, sidecar: dict[str, object] | None) -> None:
    """A small head-like blob (magnitude) and a smooth phase difference in Siemens units
    (about -4096..4094), like the real data."""
    shape = (32, 32, 20)
    x, y, z = np.meshgrid(*(np.linspace(-1, 1, n) for n in shape), indexing="ij")
    brain = (x**2 + y**2 + (z * 1.2) ** 2) < 0.55
    mag = np.where(brain, 800 + 100 * np.cos(3 * x), 5).astype("float32")
    phase = np.clip(2500 * x + 1500 * np.sin(2 * y), -4096, 4094).astype("int16")
    phase[0, 0, 0], phase[-1, -1, -1] = -4096, 4094  # use the full range, as the scanner does
    affine = np.diag([3.0, 3.0, 3.0, 1.0])
    for rel, data in ((MAG, mag), (PHASE, phase)):
        path = ws.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(data, affine), path)
    if sidecar is not None:
        (ws.root / PHASE.replace(".nii.gz", ".json")).write_text(json.dumps(sidecar))


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def problems(ws: Workspace, params: dict[str, object] | None = None) -> list[Problem]:
    step, ctx = build_context(ws, "fieldmap_prep", "sub-001", None, INPUTS, params or {})
    return step.validate_inputs(ctx)


def test_echo_time_difference_in_ms() -> None:
    assert echo_time_difference_ms({"EchoTime1": 0.00492, "EchoTime2": 0.00738}) == pytest.approx(
        2.46
    )
    assert echo_time_difference_ms({"EchoTime1": 0.005}) is None
    assert echo_time_difference_ms({}) is None
    assert echo_time_difference_ms({"EchoTime1": 0.007, "EchoTime2": 0.005}) is None  # reversed


def test_missing_echo_times_are_explained(ws: Workspace) -> None:
    phantom(ws, {"Manufacturer": "Siemens"})
    found = problems(ws)
    assert [p.code for p in found] == ["FIELDMAP_TE_MISSING"]
    assert "milliseconds" in found[0].suggested_action


def test_echo_times_from_sidecar_or_parameter(ws: Workspace) -> None:
    phantom(ws, {"EchoTime1": 0.00492, "EchoTime2": 0.00738})
    assert problems(ws) == []
    (ws.root / PHASE.replace(".nii.gz", ".json")).unlink()  # no sidecar, but the user knows it
    assert problems(ws) != []
    assert problems(ws, {"delta_te_ms": 2.46}) == []


def test_unreadable_image_is_explained(ws: Workspace) -> None:
    phantom(ws, {"EchoTime1": 0.00492, "EchoTime2": 0.00738})
    (ws.root / PHASE).write_bytes(b"not an image")
    assert [p.code for p in problems(ws)] == ["INPUT_NOT_NIFTI"]


def test_output_names_are_bids_derivatives(ws: Workspace) -> None:
    phantom(ws, {"EchoTime1": 0.00492, "EchoTime2": 0.00738})
    step, ctx = build_context(ws, "fieldmap_prep", "sub-001", None, INPUTS, {})
    out = step.expected_outputs(ctx)
    assert out.fieldmap == "sub-001_desc-prepared_fieldmap.nii.gz"
    assert out.magnitude_brain == "sub-001_desc-brain_magnitude1.nii.gz"
    assert ctx.output_dir.name == "fmap"


# -- real FSL ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fsl() -> FslInstall:
    try:
        return find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")


@pytest.mark.fsl
def test_matches_manual_fsl_commands(ws: Workspace, fsl: FslInstall, tmp_path: Path) -> None:
    phantom(ws, {"EchoTime1": 0.00492, "EchoTime2": 0.00738})
    outcome = run_step(ws, LocalJobQueue(ws), "fieldmap_prep", "sub-001", INPUTS, {})
    assert outcome.action == Action.RAN, outcome.reason

    def sh(*argv: str) -> str:
        done = subprocess.run(argv, capture_output=True, text=True, env=fsl.env, check=True)
        return done.stdout.strip()

    manual = tmp_path / "manual"
    manual.mkdir()
    sh("bet", str(ws.root / MAG), str(manual / "mag_brain"), "-f", "0.5")
    sh(
        "fsl_prepare_fieldmap", "SIEMENS", str(ws.root / PHASE), str(manual / "mag_brain.nii.gz"),
        str(manual / "fmap_rads"), "2.46",
    )  # fmt: skip
    out = ws.derivatives_dir / "sub-001" / "fmap"
    diff = tmp_path / "diff.nii.gz"
    sh("fslmaths", str(out / "sub-001_desc-prepared_fieldmap.nii.gz"), "-sub",
       str(manual / "fmap_rads.nii.gz"), "-abs", str(diff))  # fmt: skip
    assert float(sh("fslstats", str(diff), "-R").split()[1]) == 0.0
    info = json.loads((out / "sub-001_desc-prepared_fieldmap.json").read_text())
    assert info["Units"] == "rad/s" and info["DeltaTE_ms"] == pytest.approx(2.46)

    # the same inputs and settings again: nothing runs
    again = run_step(ws, LocalJobQueue(ws), "fieldmap_prep", "sub-001", INPUTS, {})
    assert again.action == Action.REUSED
