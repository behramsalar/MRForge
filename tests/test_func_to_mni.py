"""Stage 5e: resampling functional data into MNI space with the fsl_anat warp.

Unit tests need no FSL. The real-FSL test (marked ``fsl`` and ``realdata``) uses the prepared
example workspaces (see docs/TEST_DATA.md): ``func-test`` (fsl_anat result) and ``func-quick``
(a 20-volume FEAT result of the same subject); it is skipped, with the reason reported, if they
are missing."""

import os
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
from mrforge.steps.func_to_mni import standard_brain
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001"
INPUTS = {
    "bold": f"{D}/func/sub-001_task-rest_desc-preproc_bold.nii.gz",
    "to_t1_affine": f"{D}/func/sub-001_task-rest_from-boldref_to-T1w_mode-image_desc-affine_xfm.mat",
    "t1_to_mni_warp": f"{D}/anat/sub-001_from-T1w_to-MNI152NLin6Asym_mode-image_desc-fnirtcoeff_xfm.nii.gz",
    "brain_mask": f"{D}/func/sub-001_task-rest_desc-brain_mask.nii.gz",
}
WORKSPACES = Path("~/Documents/mrforge-workspaces").expanduser()


def synthetic(tmp_path: Path, shape: tuple[int, ...]) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    for key, rel in INPUTS.items():
        path = ws.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if key == "to_t1_affine":
            path.write_text("1 0 0 0\n0 1 0 0\n0 0 1 0\n0 0 0 1\n")
        else:
            data = np.ones(shape if key == "bold" else shape[:3], dtype="float32")
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)
    return ws


def problems(
    ws: Workspace, params: dict[str, object] | None = None, env: dict[str, str] | None = None
):  # type: ignore[no-untyped-def]
    step, ctx = build_context(ws, "func_to_mni", "sub-001", None, INPUTS, params or {})
    ctx.env = env
    return step.validate_inputs(ctx)


@pytest.fixture
def fake_fsl(tmp_path: Path) -> dict[str, str]:
    std = tmp_path / "fsl" / "data" / "standard"
    std.mkdir(parents=True)
    nib.save(
        nib.Nifti1Image(np.ones((4, 4, 4), dtype="float32"), np.eye(4)),
        std / "MNI152_T1_2mm_brain.nii.gz",
    )
    return {"FSLDIR": str(tmp_path / "fsl")}


def test_template_comes_from_the_fsl_in_use_not_a_fixed_path(tmp_path: Path) -> None:
    std = tmp_path / "fsl" / "data" / "standard"
    std.mkdir(parents=True)
    (std / "MNI152_T1_2mm_brain.nii.gz").write_bytes(b"x")
    env = {"FSLDIR": str(tmp_path / "fsl")}
    assert standard_brain(env, 2) == std / "MNI152_T1_2mm_brain.nii.gz"
    assert standard_brain(env, 1) is None  # no such resolution in this install


def test_valid_inputs(tmp_path: Path, fake_fsl: dict[str, str]) -> None:
    assert problems(synthetic(tmp_path, (4, 4, 4, 5)), env=fake_fsl) == []


def test_a_single_volume_is_not_a_time_series(tmp_path: Path, fake_fsl: dict[str, str]) -> None:
    ws = synthetic(tmp_path, (4, 4, 4, 5))
    nib.save(
        nib.Nifti1Image(np.ones((4, 4, 4), dtype="float32"), np.eye(4)), ws.root / INPUTS["bold"]
    )
    assert [p.code for p in problems(ws, env=fake_fsl)] == ["BOLD_NOT_4D"]


def test_missing_template_is_explained(tmp_path: Path) -> None:
    found = problems(synthetic(tmp_path, (4, 4, 4, 5)), env={"FSLDIR": str(tmp_path / "nowhere")})
    assert [p.code for p in found] == ["MNI_TEMPLATE_MISSING"]


def test_output_names(tmp_path: Path) -> None:
    ws = synthetic(tmp_path, (4, 4, 4, 5))
    step, ctx = build_context(ws, "func_to_mni", "sub-001", None, INPUTS, {})
    out = step.expected_outputs(ctx)
    assert out.bold_mni == "sub-001_task-rest_space-MNI152NLin6Asym_desc-preproc_bold.nii.gz"
    assert out.warp.endswith(
        "from-boldref_to-MNI152NLin6Asym_mode-image_desc-fnirtcoeff_xfm.nii.gz"
    )
    assert out.brain_mask_mni == "sub-001_task-rest_space-MNI152NLin6Asym_desc-brain_mask.nii.gz"


# -- real FSL -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fsl() -> FslInstall:
    try:
        return find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")


@pytest.mark.fsl
@pytest.mark.realdata
def test_matches_manual_fsl_and_lands_on_the_mni_brain(fsl: FslInstall, tmp_path: Path) -> None:
    anat_src = Path(os.environ.get("MRFORGE_FUNC_WORKSPACE", WORKSPACES / "func-test")).expanduser()
    func_src = WORKSPACES / "func-quick"
    needed = [(anat_src, INPUTS["t1_to_mni_warp"])] + [
        (func_src, INPUTS[k]) for k in ("bold", "to_t1_affine", "brain_mask")
    ]
    missing = [str(src / rel) for src, rel in needed if not (src / rel).is_file()]
    if missing:
        pytest.skip(f"prepared test data missing: {missing[0]}")
    ws = Workspace.create(tmp_path / "ws")
    for src, rel in needed:
        (ws.root / rel).parent.mkdir(parents=True, exist_ok=True)
        os.link(src / rel, ws.root / rel)

    outcome = run_step(ws, LocalJobQueue(ws), "func_to_mni", "sub-001", INPUTS, {})
    assert outcome.action == Action.RAN, outcome.reason
    func = ws.derivatives_dir / "sub-001" / "func"
    result = func / "sub-001_task-rest_space-MNI152NLin6Asym_desc-preproc_bold.nii.gz"

    def sh(*argv: str) -> str:
        done = subprocess.run(argv, capture_output=True, text=True, env=fsl.env, check=True)
        return done.stdout.strip()

    # the same operation by hand
    std = standard_brain(fsl.env, 2)
    assert std is not None
    sh("convertwarp", f"--ref={std}", f"--premat={ws.root / INPUTS['to_t1_affine']}",
       f"--warp1={ws.root / INPUTS['t1_to_mni_warp']}", f"--out={tmp_path / 'w.nii.gz'}")  # fmt: skip
    sh("applywarp", "-i", str(ws.root / INPUTS["bold"]), "-r", str(std), "-w", str(tmp_path / "w.nii.gz"),
       "-o", str(tmp_path / "manual.nii.gz"), "--interp=spline")  # fmt: skip
    sh(
        "fslmaths",
        str(result),
        "-sub",
        str(tmp_path / "manual.nii.gz"),
        "-abs",
        str(tmp_path / "d.nii.gz"),
    )
    assert float(sh("fslstats", str(tmp_path / "d.nii.gz"), "-R").split()[1]) == 0.0

    # and it lands where it should: the MNI brain lies inside the warped functional brain mask
    mask = func / "sub-001_task-rest_space-MNI152NLin6Asym_desc-brain_mask.nii.gz"
    template_mask = fsl.fsldir / "data" / "standard" / "MNI152_T1_2mm_brain_mask.nii.gz"
    total = float(sh("fslstats", str(template_mask), "-V").split()[0])
    inside = float(sh("fslstats", str(mask), "-k", str(template_mask), "-V").split()[0])
    assert inside / total > 0.97
    assert (func / "sub-001_task-rest_desc-mni_qc.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    again = run_step(ws, LocalJobQueue(ws), "func_to_mni", "sub-001", INPUTS, {})
    assert again.action == Action.REUSED
