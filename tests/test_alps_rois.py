"""AlpsRoisStep tests. Unit tests need no FSL; the ``fsl`` tests compare with the script's own
fslmaths/flirt commands (alps.sh) and with the ROI files packaged from the same script."""

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
from mrforge.steps.alps_rois import DATA, ROI_FILES, SETS
from mrforge.workspace import Workspace

FA = "derivatives/mrforge/sub-001/dwi/sub-001_space-JHUFA1mm_desc-dti_FA.nii.gz"
OUT = "derivatives/mrforge/sub-001/dwi"


def load(path: Path) -> np.ndarray:
    return np.asarray(nib.load(str(path)).dataobj)  # type: ignore[attr-defined]


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def put_fa(ws: Workspace, like: Path) -> None:
    """An FA map on the same grid as the ROIs (the values do not matter here)."""
    ref = nib.load(str(like))  # type: ignore[attr-defined]
    data = np.full(ref.shape, 0.5, dtype=np.float32)
    path = ws.root / FA
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, ref.affine), path)  # type: ignore[attr-defined]


def test_the_packaged_rois_are_the_ones_of_the_script() -> None:
    for name in ROI_FILES:
        assert int(load(SETS["default"] / f"{name}.nii.gz").sum()) == 81
        assert int(load(SETS["legacy5"] / f"{name}.nii.gz").sum()) == 515
    assert (DATA / "LICENSE").read_text().startswith("MIT License")


def test_result_names(ws: Workspace) -> None:
    put_fa(ws, SETS["default"] / "L_SCR.nii.gz")
    step, ctx = build_context(ws, "alps_rois", "sub-001", None, {"fa": FA}, {})
    out = step.expected_outputs(ctx)
    assert out.proj_l == "sub-001_space-JHUFA1mm_desc-LSCR_mask.nii.gz"  # type: ignore[attr-defined]
    assert out.matrix is None  # type: ignore[attr-defined]
    step, ctx = build_context(ws, "alps_rois", "sub-001", None, {"fa": FA}, {"space": "native"})
    out = step.expected_outputs(ctx)
    assert out.assoc_r == "sub-001_space-native_desc-RSLF_mask.nii.gz"  # type: ignore[attr-defined]
    assert out.matrix == "sub-001_from-JHUFA1mm_to-native_mode-image_xfm.mat"  # type: ignore[attr-defined]


def test_custom_rois_need_four_files(ws: Workspace) -> None:
    put_fa(ws, SETS["default"] / "L_SCR.nii.gz")
    step, ctx = build_context(
        ws, "alps_rois", "sub-001", None, {"fa": FA, "custom_rois": [FA]}, {"source": "custom"}
    )
    assert [p.code for p in step.validate_inputs(ctx)] == ["ROI_NEED_FOUR"]


def test_a_missing_custom_template_is_explained(ws: Workspace) -> None:
    put_fa(ws, SETS["default"] / "L_SCR.nii.gz")
    step, ctx = build_context(ws, "alps_rois", "sub-001", None, {"fa": FA}, {"template": "custom"})
    assert [p.code for p in step.validate_inputs(ctx)] == ["ROI_TEMPLATE_MISSING"]


def fsl_or_skip() -> FslInstall:
    try:
        return find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")


@pytest.mark.fsl
def test_template_space_uses_the_packaged_rois_unchanged(ws: Workspace) -> None:
    fsl_or_skip()
    put_fa(ws, SETS["default"] / "L_SCR.nii.gz")
    outcome = run_step(ws, LocalJobQueue(ws), "alps_rois", "sub-001", {"fa": FA})
    assert outcome.action == Action.RAN, outcome.reason
    for name, got in (("L_SCR", "LSCR"), ("R_SCR", "RSCR"), ("L_SLF", "LSLF"), ("R_SLF", "RSLF")):
        written = ws.root / OUT / f"sub-001_space-JHUFA1mm_desc-{got}_mask.nii.gz"
        assert np.array_equal(load(written), load(SETS["default"] / f"{name}.nii.gz"))
    labelled = load(ws.root / OUT / "sub-001_space-JHUFA1mm_desc-ALPSrois_dseg.nii.gz")
    assert sorted(np.unique(labelled).tolist()) == [0, 1, 2, 3, 4]


@pytest.mark.fsl
@pytest.mark.parametrize("radius, packaged", [(2.5, "default"), (5.0, "legacy5")])
def test_a_sphere_made_by_the_step_equals_the_packaged_one(
    ws: Workspace, radius: float, packaged: str
) -> None:
    fsl_or_skip()
    put_fa(ws, SETS["default"] / "L_SCR.nii.gz")
    outcome = run_step(
        ws, LocalJobQueue(ws), "alps_rois", "sub-001", {"fa": FA},
        {"source": "sphere", "radius_mm": radius},
    )  # fmt: skip
    assert outcome.action == Action.RAN, outcome.reason
    for name, got in (("L_SCR", "LSCR"), ("R_SCR", "RSCR"), ("L_SLF", "LSLF"), ("R_SLF", "RSLF")):
        written = ws.root / OUT / f"sub-001_space-JHUFA1mm_desc-{got}_mask.nii.gz"
        assert np.array_equal(load(written) > 0, load(SETS[packaged] / f"{name}.nii.gz") > 0)


@pytest.mark.fsl
def test_a_grid_mismatch_is_explained(ws: Workspace) -> None:
    fsl_or_skip()
    path = ws.root / FA
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.ones((10, 10, 10), np.float32), np.eye(4) * 2), path)  # type: ignore[attr-defined]
    outcome = run_step(ws, LocalJobQueue(ws), "alps_rois", "sub-001", {"fa": FA})
    assert outcome.action == Action.FAILED


@pytest.mark.fsl
def test_native_space_matches_the_scripts_flirt_commands(ws: Workspace, tmp_path: Path) -> None:
    fsl = fsl_or_skip()
    jhu = Path(fsl.fsldir) / "data/atlases/JHU/JHU-ICBM-FA-1mm.nii.gz"
    jhu2 = Path(fsl.fsldir) / "data/atlases/JHU/JHU-ICBM-FA-2mm.nii.gz"
    native = ws.root / "derivatives/mrforge/sub-001/dwi/sub-001_desc-dti_FA.nii.gz"
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_bytes(jhu2.read_bytes())  # a "native" FA map on a coarser grid
    rel = ws.relpath(native)
    outcome = run_step(
        ws, LocalJobQueue(ws), "alps_rois", "sub-001", {"fa": rel}, {"space": "native"}
    )
    assert outcome.action == Action.RAN, outcome.reason

    # the same thing by hand, command for command as in alps.sh (lines 697-699)
    mat = tmp_path / "manual.mat"
    common = {"env": fsl.env, "check": True, "capture_output": True}
    subprocess.run(
        ["flirt", "-ref", str(native), "-in", str(jhu), "-out", str(tmp_path / "t"),
         "-omat", str(mat), "-bins", "256", "-cost", "corratio",
         "-searchrx", "-90", "90", "-searchry", "-90", "90", "-searchrz", "-90", "90",
         "-dof", "12"], **common,
    )  # fmt: skip
    for name, got in (("L_SCR", "LSCR"), ("R_SCR", "RSCR"), ("L_SLF", "LSLF"), ("R_SLF", "RSLF")):
        manual = tmp_path / f"{name}.nii.gz"
        subprocess.run(
            ["flirt", "-in", str(SETS["default"] / f"{name}.nii.gz"), "-ref", str(native),
             "-out", str(manual), "-init", str(mat), "-applyxfm", "-interp", "nearestneighbour"],
            **common,
        )  # fmt: skip
        written = ws.root / OUT / f"sub-001_space-native_desc-{got}_mask.nii.gz"
        assert np.array_equal(load(written), load(manual))
        assert 5 <= int(load(written).sum()) <= 20  # 81 voxels of 1 mm become about 10 of 2 mm
