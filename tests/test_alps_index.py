"""AlpsIndexStep tests. Unit tests need no tools. The ``fsl`` test runs the real data through the
script itself (alps.sh -s 1, ROI statistics only; set MRFORGE_ALPS_SCRIPT, default
~/Documents/alps-main/alps.sh) and compares the numbers."""

import csv
import json
import os
import shutil
import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from test_dwi_prep import copy_real, fsl_or_skip, real_data

from mrforge.engine import Action, run_step
from mrforge.runner.jobs import build_context
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401  (registers the steps)
from mrforge.steps.alps_index import alps_from_means, roi_mean
from mrforge.workspace import Workspace

OUT = "derivatives/mrforge/sub-001/dwi"
SCRIPT = Path(os.environ.get("MRFORGE_ALPS_SCRIPT", "~/Documents/alps-main/alps.sh")).expanduser()


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def save(ws: Workspace, name: str, data: np.ndarray) -> str:
    path = ws.root / OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data.astype(np.float32), np.eye(4)), path)  # type: ignore[attr-defined]
    return ws.relpath(path)


def synthetic(ws: Workspace) -> dict[str, str]:
    """A 10x10x10 image with four 2x2x2 ROIs and known tensor values."""
    shape = (10, 10, 10)
    tensor = np.zeros(shape + (6,), np.float32)
    rois = {}
    for name, corner in {"proj_l": 0, "proj_r": 2, "assoc_l": 4, "assoc_r": 6}.items():
        mask = np.zeros(shape, np.float32)
        mask[corner : corner + 2, 0:2, 0:2] = 1
        rois[name] = save(ws, f"sub-001_desc-{name}_mask.nii.gz", mask)
    tensor[..., 0] = 0.0008  # Dxx
    tensor[..., 3] = 0.0004  # Dyy
    tensor[..., 5] = 0.0006  # Dzz
    fa = np.full(shape, 0.5)
    md = np.full(shape, 0.0007)
    return {
        "tensor": save(ws, "sub-001_desc-dti_tensor.nii.gz", tensor),
        "fa": save(ws, "sub-001_desc-dti_FA.nii.gz", fa),
        "md": save(ws, "sub-001_desc-dti_MD.nii.gz", md),
        **rois,
    }


def test_the_formula() -> None:
    assert alps_from_means(0.0008, 0.0008, 0.0004, 0.0006) == pytest.approx(1.6)


def test_roi_mean_uses_the_voxels_where_the_roi_is_not_zero() -> None:
    vol = np.arange(8, dtype=np.float32).reshape(2, 2, 2)
    roi = np.zeros((2, 2, 2), np.float32)
    roi[0, 0, 0] = 1
    roi[1, 1, 1] = 0.5  # not zero: counts, as in fslstats -k
    assert roi_mean(vol, roi) == pytest.approx(3.5)


def test_result_names(ws: Workspace) -> None:
    step, ctx = build_context(ws, "alps_index", "sub-001", None, synthetic(ws), {})
    out = step.expected_outputs(ctx)
    assert out.result == "sub-001_desc-alps_alps.json"
    assert out.alps_csv == "sub-001_desc-alps_alps.csv"
    assert out.fa_md_csv == "sub-001_desc-alps_famd.csv"


def test_grids_must_match_the_tensor(ws: Workspace) -> None:
    inputs = synthetic(ws)
    inputs["proj_l"] = save(ws, "other.nii.gz", np.ones((5, 5, 5)))
    step, ctx = build_context(ws, "alps_index", "sub-001", None, inputs, {})
    assert [p.code for p in step.validate_inputs(ctx)] == ["ROI_GRID_MISMATCH"]


def test_a_tensor_without_six_volumes_is_refused(ws: Workspace) -> None:
    inputs = synthetic(ws)
    inputs["tensor"] = save(ws, "t.nii.gz", np.ones((10, 10, 10, 3)))
    step, ctx = build_context(ws, "alps_index", "sub-001", None, inputs, {})
    assert [p.code for p in step.validate_inputs(ctx)] == ["TENSOR_NOT_SIX_VOLUMES"]


@pytest.mark.fsl
def test_known_values_and_script_compatible_files(ws: Workspace) -> None:
    fsl_or_skip()
    inputs = synthetic(ws)
    outcome = run_step(
        ws, LocalJobQueue(ws), "alps_index", "sub-001", inputs,
        {"settings": {"registration": "linear"}, "notes": ["no distortion correction"]},
    )  # fmt: skip
    assert outcome.action == Action.RAN, outcome.reason
    rec = json.loads((ws.root / OUT / "sub-001_desc-alps_alps.json").read_text())
    assert rec["alps"] == pytest.approx(1.6, rel=1e-5)
    assert rec["voxels"] == {"proj_L": 8, "proj_R": 8, "assoc_L": 8, "assoc_R": 8}
    assert rec["notes"] == ["no distortion correction"]
    assert rec["fa"]["mean_proj"] == pytest.approx(0.5)
    with (ws.root / OUT / "sub-001_desc-alps_alps.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == [
        "id", "scanner", "x_proj_L", "x_assoc_L", "y_proj_L", "z_assoc_L", "x_proj_R",
        "x_assoc_R", "y_proj_R", "z_assoc_R", "alps_L", "alps_R", "alps",
    ]  # fmt: skip
    assert float(rows[0]["alps"]) == pytest.approx(1.6, rel=1e-5)
    assert (ws.root / OUT / "sub-001_desc-alps_famd.csv").read_text().startswith("id,scanner,diff")


@pytest.mark.fsl
def test_matches_the_script_on_real_data(tmp_path: Path) -> None:
    fsl_or_skip()
    if not SCRIPT.is_file():
        pytest.skip(f"alps.sh not found at {SCRIPT}")
    src = real_data()
    ws = Workspace.create(tmp_path / "ws")
    inputs = copy_real(ws, src)
    bvec = ws.root / "rawbids/sub-001/dwi/sub-001_dwi.bvec"
    shutil.copyfile(src / "dwi/sub-001_dwi.bvec", bvec)
    q = LocalJobQueue(ws)
    d = f"{OUT}/"
    fit = {"dwi": inputs["dwi"], "bval": inputs["dwi_bval"], "bvec": ws.relpath(bvec)}
    assert run_step(ws, q, "dwi_dtifit", "sub-001", fit).action == Action.RAN
    maps = {
        "fa": d + "sub-001_desc-dti_FA.nii.gz", "md": d + "sub-001_desc-dti_MD.nii.gz",
        "tensor": d + "sub-001_desc-dti_tensor.nii.gz", "mask": d + "sub-001_desc-dtimask_mask.nii.gz",
    }  # fmt: skip
    assert run_step(ws, q, "dwi_to_template", "sub-001", maps).action == Action.RAN
    t = d + "sub-001_space-JHUFA1mm_desc-dti_"
    assert run_step(ws, q, "alps_rois", "sub-001", {"fa": t + "FA.nii.gz"}).action == Action.RAN
    names = {"proj_l": "LSCR", "proj_r": "RSCR", "assoc_l": "LSLF", "assoc_r": "RSLF"}
    idx = {
        "tensor": t + "tensor.nii.gz", "fa": t + "FA.nii.gz", "md": t + "MD.nii.gz",
        **{k: f"{d}sub-001_space-JHUFA1mm_desc-{v}_mask.nii.gz" for k, v in names.items()},
        "dwi_json": inputs["dwi_json"],
    }  # fmt: skip
    assert (
        run_step(ws, q, "alps_index", "sub-001", idx, {"round_like_script": True}).action
        == Action.RAN
    )
    ours = json.loads((ws.root / OUT / "sub-001_desc-alps_alps.json").read_text())

    # the script itself, ROI statistics only (-s 1), on the same fitted maps
    by = tmp_path / "script"
    by.mkdir()
    for ours_name, theirs in (("FA", "dti_FA"), ("MD", "dti_MD"), ("tensor", "dti_tensor")):
        shutil.copyfile(
            ws.root / maps[ours_name.lower() if ours_name != "tensor" else "tensor"],
            by / f"{theirs}.nii.gz",
        )
    dwi_dir = src / "dwi"
    subprocess.run(
        ["bash", str(SCRIPT), "-a", str(dwi_dir / "sub-001_dwi.nii.gz"), "-b", str(dwi_dir / "sub-001_dwi.bval"),
         "-c", str(dwi_dir / "sub-001_dwi.bvec"), "-m", str(dwi_dir / "sub-001_dwi.json"), "-s", "1", "-o", str(by)],
        cwd=by, check=True, capture_output=True,
        env={**os.environ, "PATH": f"{os.environ['FSLDIR']}/bin:{os.environ['PATH']}"} if "FSLDIR" in os.environ else None,
    )  # fmt: skip
    with (by / "alps.stat/alps.csv").open() as fh:
        theirs_row = next(csv.DictReader(fh))
    for key in (
        "x_proj_L",
        "x_assoc_L",
        "y_proj_L",
        "z_assoc_L",
        "x_proj_R",
        "x_assoc_R",
        "y_proj_R",
        "z_assoc_R",
    ):
        assert ours["components"][key] == pytest.approx(float(theirs_row[key]), abs=1e-9), key
    for key, mine in (
        ("alps_L", ours["alps_L"]),
        ("alps_R", ours["alps_R"]),
        ("alps", ours["alps"]),
    ):
        assert mine == pytest.approx(float(theirs_row[key]), rel=1e-9), key
    with (by / "alps.stat/fa+md_alps.csv").open() as fh:
        for row in csv.DictReader(fh):
            mine = ours["fa" if row["diffusion_metric"] == "FA" else "md"]
            assert mine["proj_L"] == pytest.approx(float(row["proj_L"]), abs=1e-9)
            assert mine["mean_assoc"] == pytest.approx(float(row["mean_assoc"]), abs=1e-9)

    # full precision (the default) differs from the script only by its rounding
    assert run_step(ws, q, "alps_index", "sub-001", idx, {}).action == Action.RAN
    full = json.loads((ws.root / OUT / "sub-001_desc-alps_alps.json").read_text())
    assert full["alps"] == pytest.approx(float(theirs_row["alps"]), rel=5e-3)
