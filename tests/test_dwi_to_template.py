"""Tests of DwiToTemplateStep. Unit tests need no tools. The ``fsl`` tests run the real
registration on the real diffusion data (see test_dwi_prep.py) and compare with the script's own
commands (alps.sh lines 572-675); the fnirt routes also carry the mark ``slow``."""

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from test_dwi_prep import copy_real, fsl_or_skip, load, put_image, real_data

from mrforge.engine import Action, run_step
from mrforge.fsl_env import find_fsl
from mrforge.runner.jobs import build_context
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401  (registers the steps)
from mrforge.steps.dwi_to_template import DwiToTemplateParams, resolve_template
from mrforge.workspace import Workspace

OUT = "derivatives/mrforge/sub-001/dwi"


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def test_template_follows_the_structural_image_as_in_the_script() -> None:
    p = DwiToTemplateParams()
    assert resolve_template(p, False) == "jhu_fa"
    assert resolve_template(p, True) == "mni_t1"
    assert resolve_template(DwiToTemplateParams(struct_weight="t2"), True) == "jhu_t2"
    assert resolve_template(DwiToTemplateParams(template="mni_t1"), False) == "mni_t1"


def maps(ws: Workspace) -> dict[str, str]:
    return {
        "fa": put_image(ws, f"{OUT}/sub-001_desc-dti_FA.nii.gz", (4, 4, 4)),
        "md": put_image(ws, f"{OUT}/sub-001_desc-dti_MD.nii.gz", (4, 4, 4)),
        "tensor": put_image(ws, f"{OUT}/sub-001_desc-dti_tensor.nii.gz", (4, 4, 4, 6)),
    }


def test_result_names(ws: Workspace) -> None:
    step, ctx = build_context(ws, "dwi_to_template", "sub-001", None, maps(ws), {})
    out = step.expected_outputs(ctx)
    assert out.fa == "sub-001_space-JHUFA1mm_desc-dti_FA.nii.gz"
    assert out.tensor == "sub-001_space-JHUFA1mm_desc-dti_tensor.nii.gz"
    assert out.warp is None  # linear: a matrix only
    assert out.affine.endswith("_xfm.mat")
    step, ctx = build_context(
        ws, "dwi_to_template", "sub-001", None, maps(ws), {"registration": "fnirt"}
    )
    assert step.expected_outputs(ctx).warp is not None
    inputs = maps(ws) | {
        "struct": put_image(ws, "rawbids/sub-001/anat/sub-001_T1w.nii.gz", (4, 4, 4))
    }
    step, ctx = build_context(ws, "dwi_to_template", "sub-001", None, inputs, {})
    out = step.expected_outputs(ctx)
    assert out.fa.startswith("sub-001_space-MNI152T1_") and out.warp is not None


def test_a_missing_custom_template_is_explained(ws: Workspace) -> None:
    step, ctx = build_context(
        ws, "dwi_to_template", "sub-001", None, maps(ws), {"template": "custom"}
    )
    assert [p.code for p in step.validate_inputs(ctx)] == ["TEMPLATE_MISSING"]


def test_a_tensor_without_six_volumes_is_explained(ws: Workspace) -> None:
    inputs = maps(ws) | {"tensor": put_image(ws, f"{OUT}/t.nii.gz", (4, 4, 4, 3))}
    tpl = ws.root / "tpl.nii.gz"
    put_image(ws, "tpl.nii.gz", (4, 4, 4))
    step, ctx = build_context(
        ws, "dwi_to_template", "sub-001", None, inputs,
        {"template": "custom", "template_file": str(tpl)},
    )  # fmt: skip
    assert [p.code for p in step.validate_inputs(ctx)] == ["TENSOR_NOT_SIX_VOLUMES"]


# -- with FSL -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fitted(tmp_path_factory: pytest.TempPathFactory) -> tuple[Workspace, dict[str, str], Path]:
    """A workspace with the real diffusion data fitted (dtifit on the raw series)."""
    fsl_or_skip()
    src = real_data()
    ws = Workspace.create(tmp_path_factory.mktemp("dwi") / "ws")
    inputs = copy_real(ws, src)
    bvec = ws.root / "rawbids/sub-001/dwi/sub-001_dwi.bvec"
    shutil.copyfile(src / "dwi/sub-001_dwi.bvec", bvec)
    outcome = run_step(
        ws, LocalJobQueue(ws), "dwi_dtifit", "sub-001",
        {"dwi": inputs["dwi"], "bval": inputs["dwi_bval"], "bvec": ws.relpath(bvec)},
    )  # fmt: skip
    assert outcome.action == Action.RAN, outcome.reason
    maps = {
        "fa": f"{OUT}/sub-001_desc-dti_FA.nii.gz",
        "md": f"{OUT}/sub-001_desc-dti_MD.nii.gz",
        "tensor": f"{OUT}/sub-001_desc-dti_tensor.nii.gz",
        "mask": f"{OUT}/sub-001_desc-dtimask_mask.nii.gz",
    }
    return ws, maps, src


class Manual:
    """The script's commands, run by hand in a folder, with the script's file names."""

    def __init__(self, tmp: Path, ws: Workspace, maps: dict[str, str]) -> None:
        fsl = find_fsl()
        self.fsldir = Path(fsl.fsldir)
        self.env = {**os.environ, "FSLDIR": fsl.fsldir, "FSLOUTPUTTYPE": "NIFTI_GZ"}
        self.env["PATH"] = f"{fsl.fsldir}/bin:{self.env['PATH']}"
        self.dir = tmp / "manual"
        self.dir.mkdir()
        for key, name in (("fa", "dti_FA"), ("md", "dti_MD"), ("tensor", "dti_tensor"),
                          ("mask", "b0_brain_mask")):  # fmt: skip
            shutil.copyfile(ws.root / maps[key], self.dir / f"{name}.nii.gz")

    def sh(self, *argv: str) -> None:
        subprocess.run(argv, cwd=self.dir, env=self.env, check=True, capture_output=True)


def run_to_template(
    fitted: tuple[Workspace, dict[str, str], Path], params: dict, extra: dict | None = None
) -> Workspace:
    """Run the step (one result at a time: the next test overwrites it, which is fine)."""
    ws, maps, _ = fitted
    inputs = {k: maps[k] for k in ("fa", "md", "tensor", "mask")} | (extra or {})
    outcome = run_step(ws, LocalJobQueue(ws), "dwi_to_template", "sub-001", inputs, params)
    assert outcome.action == Action.RAN, outcome.reason
    return ws


def same(ws: Workspace, space: str, manual: Manual, pairs: dict[str, str]) -> None:
    for ours, theirs in pairs.items():
        got = load(ws.root / OUT / f"sub-001_space-{space}_desc-dti_{ours}.nii.gz")
        want = load(manual.dir / f"{theirs}.nii.gz")
        assert got.shape == want.shape, ours
        assert np.allclose(got, want, atol=1e-6), ours


JHU = "data/atlases/JHU/JHU-ICBM-FA-1mm.nii.gz"
FNIRT_FA = [
    "--imprefm=1", "--impinm=1", "--imprefval=0", "--impinval=0", "--subsamp=8,4,2,2",
    "--miter=5,5,5,5", "--infwhm=12,6,2,2", "--reffwhm=12,6,2,2", "--lambda=300,75,30,30",
    "--estint=1,1,1,0", "--warpres=10,10,10", "--ssqlambda=1", "--regmod=bending_energy",
    "--intmod=global_linear", "--refderiv=0",
]  # fmt: skip
FLIRT_FA = ["-bins", "256", "-cost", "corratio", "-searchrx", "-90", "90", "-searchry", "-90",
            "90", "-searchrz", "-90", "90", "-dof", "12"]  # fmt: skip


@pytest.mark.fsl
@pytest.mark.parametrize("method", ["flirt", "vecreg"])
def test_linear_route_matches_the_script(
    fitted: tuple[Workspace, dict[str, str], Path], tmp_path: Path, method: str
) -> None:
    ws = run_to_template(fitted, {"tensor_method": method})
    m = Manual(tmp_path, *fitted[:2])
    t = str(m.fsldir / JHU)
    m.sh("flirt", "-in", "dti_FA.nii.gz", "-ref", t, "-out", "fa_t", "-omat", "fa.mat", *FLIRT_FA)
    m.sh("flirt", "-in", "dti_MD.nii.gz", "-ref", t, "-out", "md_t", "-init", "fa.mat", "-applyxfm")
    if method == "flirt":
        m.sh("flirt", "-in", "dti_tensor.nii.gz", "-ref", t, "-out", "tensor_t",
             "-init", "fa.mat", "-applyxfm")  # fmt: skip
    else:
        m.sh("vecreg", "-i", "dti_tensor.nii.gz", "-r", t, "-o", "tensor_t", "-t", "fa.mat")
    same(ws, "JHUFA1mm", m, {"FA": "fa_t", "MD": "md_t", "tensor": "tensor_t"})


@pytest.mark.fsl
@pytest.mark.slow
@pytest.mark.parametrize("registration", ["fnirt", "linear_fnirt"])
def test_fnirt_routes_match_the_script(
    fitted: tuple[Workspace, dict[str, str], Path], tmp_path: Path, registration: str
) -> None:
    ws = run_to_template(fitted, {"registration": registration})
    m = Manual(tmp_path, *fitted[:2])
    t = str(m.fsldir / JHU)
    mask = f"--refmask={m.fsldir}/data/standard/MNI152_T1_1mm_brain_mask_dil.nii.gz"
    start: list[str] = []
    if registration == "linear_fnirt":
        m.sh("flirt", "-in", "dti_FA.nii.gz", "-ref", t, "-omat", "aff.mat", *FLIRT_FA)
        start = ["--aff=aff.mat"]
    m.sh("fnirt", "--in=dti_FA.nii.gz", f"--ref={t}", mask, *start, "--cout=warps", *FNIRT_FA)
    for src, dst in (("dti_FA", "fa_t"), ("dti_MD", "md_t"), ("dti_tensor", "tensor_t")):
        m.sh("applywarp", f"--in={src}.nii.gz", f"--ref={t}", "--warp=warps", f"--out={dst}")
    same(ws, "JHUFA1mm", m, {"FA": "fa_t", "MD": "md_t", "tensor": "tensor_t"})


@pytest.mark.fsl
@pytest.mark.slow
def test_structural_route_matches_the_script(
    fitted: tuple[Workspace, dict[str, str], Path], tmp_path: Path
) -> None:
    ws, maps, src = fitted
    t1 = ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    t1.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src / "anat/sub-001_T1w.nii.gz", t1)
    run_to_template(fitted, {}, {"struct": ws.relpath(t1)})
    m = Manual(tmp_path, ws, maps)
    shutil.copyfile(t1, m.dir / "t1w.nii.gz")
    t = str(m.fsldir / "data/standard/MNI152_T1_1mm_brain.nii.gz")
    mask = f"--refmask={m.fsldir}/data/standard/MNI152_T1_1mm_brain_mask_dil.nii.gz"
    m.sh("flirt", "-ref", "t1w.nii.gz", "-in", "dti_FA.nii.gz", "-dof", "6",
         "-out", "dti_FA_2_t1w.nii.gz", "-omat", "dti2struct.mat")  # fmt: skip
    m.sh("flirt", "-in", "b0_brain_mask.nii.gz", "-ref", "t1w.nii.gz", "-interp",
         "nearestneighbour", "-out", "mask_2_struct.nii.gz", "-init", "dti2struct.mat",
         "-applyxfm")  # fmt: skip
    m.sh("fslmaths", "t1w.nii.gz", "-mul", "mask_2_struct.nii.gz", "t1w_brain.nii.gz")
    m.sh("flirt", "-ref", t, "-in", "t1w_brain.nii.gz", "-omat", "struct2template_aff.mat")
    m.sh("fnirt", "--in=t1w.nii.gz", "--aff=struct2template_aff.mat", "--cout=warps",
         f"--ref={t}", mask, "--imprefm=1", "--impinm=1", "--imprefval=0", "--impinval=0",
         "--subsamp=4,4,2,2,1,1", "--miter=5,5,5,5,5,10", "--infwhm=8,6,5,4.5,3,2",
         "--reffwhm=8,6,5,4,2,0", "--lambda=300,150,100,50,40,30", "--estint=1,1,1,1,1,0",
         "--applyrefmask=1,1,1,1,1,1", "--applyinmask=1", "--warpres=10,10,10",
         "--ssqlambda=1", "--regmod=bending_energy", "--intmod=global_non_linear_with_bias",
         "--intorder=5", "--biasres=50,50,50", "--biaslambda=10000", "--refderiv=0")  # fmt: skip
    for s, d in (("dti_FA", "fa_t"), ("dti_MD", "md_t"), ("dti_tensor", "tensor_t")):
        m.sh("applywarp", f"--in={s}.nii.gz", f"--ref={t}", "--warp=warps",
             "--premat=dti2struct.mat", f"--out={d}")  # fmt: skip
    same(ws, "MNI152T1", m, {"FA": "fa_t", "MD": "md_t", "tensor": "tensor_t"})
