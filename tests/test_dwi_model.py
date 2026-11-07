"""Tests of eddy, dtifit and the diffusion QC step. Unit tests need no tools; ``fsl`` tests run on
real diffusion data (see test_dwi_prep.py) and compare with the script's own commands
(alps.sh lines 418-522). The eddy comparison also has the mark ``slow``."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from test_dwi_prep import (
    SIEMENS_AP,
    copy_real,
    fsl_or_skip,
    load,
    put_image,
    put_text,
    real_data,
)

from mrforge.engine import Action, run_step
from mrforge.fsl_env import find_fsl
from mrforge.runner.jobs import build_context
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import (
    builtin,  # noqa: F401  (registers the steps)
    dwi_dti,
)
from mrforge.workspace import Workspace

OUT = "derivatives/mrforge/sub-001/dwi"


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def eddy_inputs(ws: Workspace, json_text: str | None = None) -> dict[str, str]:
    d = "rawbids/sub-001/dwi"
    inputs = {
        "dwi": put_image(ws, f"{d}/sub-001_dwi.nii.gz", (4, 4, 4, 3)),
        "bval": put_text(ws, f"{d}/sub-001_dwi.bval", "0 1000 1000"),
        "bvec": put_text(ws, f"{d}/sub-001_dwi.bvec", "0 1 0\n0 0 1\n0 0 0"),
    }
    if json_text is not None:
        inputs["dwi_json"] = put_text(ws, f"{d}/sub-001_dwi.json", json_text)
    return inputs


def fake_fsl(ws: Workspace, monkeypatch: pytest.MonkeyPatch, programs: tuple[str, ...]) -> None:
    folder = ws.root / "fsl" / "bin"
    folder.mkdir(parents=True)
    for p in programs:
        (folder / p).write_text("")
    monkeypatch.setattr(
        "mrforge.steps.dwi_eddy.DwiEddyStep._fsldir", lambda self, ctx: str(ws.root / "fsl")
    )


def test_eddy_result_names(ws: Workspace) -> None:
    step, ctx = build_context(ws, "dwi_eddy", "sub-001", None, eddy_inputs(ws, "{}"), {})
    out = step.expected_outputs(ctx)
    assert out.dwi == "sub-001_desc-eddy_dwi.nii.gz"
    assert out.bvec == "sub-001_desc-eddy_dwi.bvec"
    assert out.parameters == "sub-001_desc-eddy_parameters.txt"
    plain_step, plain = build_context(
        ws, "dwi_eddy", "sub-001", None, eddy_inputs(ws, "{}"), {"program": "eddy_correct"}
    )
    assert plain_step.expected_outputs(plain).parameters is None


def test_eddy_without_topup_needs_the_sidecar(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_fsl(ws, monkeypatch, ("eddy_cpu", "eddy_correct"))
    step, ctx = build_context(ws, "dwi_eddy", "sub-001", None, eddy_inputs(ws), {})
    assert [p.code for p in step.validate_inputs(ctx)] == ["DWI_ENCODING_UNKNOWN"]
    # eddy_correct does not need to know how the image was acquired
    step, ctx = build_context(
        ws, "dwi_eddy", "sub-001", None, eddy_inputs(ws), {"program": "eddy_correct"}
    )
    assert step.validate_inputs(ctx) == []


def test_eddy_with_a_good_sidecar_is_fine(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_fsl(ws, monkeypatch, ("eddy_cpu",))
    step, ctx = build_context(
        ws, "dwi_eddy", "sub-001", None, eddy_inputs(ws, json.dumps(SIEMENS_AP)), {}
    )
    assert step.validate_inputs(ctx) == []


def test_a_missing_eddy_program_is_explained(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_fsl(ws, monkeypatch, ("eddy_cpu",))
    step, ctx = build_context(
        ws, "dwi_eddy", "sub-001", None, eddy_inputs(ws, json.dumps(SIEMENS_AP)),
        {"program": "eddy_cuda10.2"},
    )  # fmt: skip
    assert [p.code for p in step.validate_inputs(ctx)] == ["EDDY_PROGRAM_MISSING"]


def test_only_programs_of_fsl_can_be_chosen(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_fsl(ws, monkeypatch, ("eddy_cpu",))
    step, ctx = build_context(
        ws, "dwi_eddy", "sub-001", None, eddy_inputs(ws, json.dumps(SIEMENS_AP)),
        {"program": "../../bin/sh"},
    )  # fmt: skip
    assert [p.code for p in step.validate_inputs(ctx)] == ["EDDY_PROGRAM_UNKNOWN"]


def test_incomplete_topup_results_are_explained(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_fsl(ws, monkeypatch, ("eddy_cpu",))
    inputs = eddy_inputs(ws)
    inputs["topup_acqparams"] = put_text(ws, "x/acq.txt", "0 1 0 0.05\n0 -1 0 0.05\n")
    step, ctx = build_context(ws, "dwi_eddy", "sub-001", None, inputs, {})
    assert [p.code for p in step.validate_inputs(ctx)] == ["EDDY_TOPUP_INCOMPLETE"]


def test_dtifit_and_qc_result_names(ws: Workspace) -> None:
    inputs = eddy_inputs(ws)
    step, ctx = build_context(ws, "dwi_dtifit", "sub-001", None, inputs, {})
    out = step.expected_outputs(ctx)
    assert (out.fa, out.md, out.tensor) == (
        "sub-001_desc-dti_FA.nii.gz",
        "sub-001_desc-dti_MD.nii.gz",
        "sub-001_desc-dti_tensor.nii.gz",
    )


def test_eddy_motion_files_are_read(tmp_path: Path) -> None:
    f = tmp_path / "rms.txt"
    f.write_text("0 0\n0.4 0.4\n0.6 0.3\n")
    assert dwi_dti.read_rms(f) == [(0.0, 0.0), (0.4, 0.4), (0.6, 0.3)]
    o = tmp_path / "out.txt"
    o.write_text("Slice 3 in scan 5 is an outlier\n\nSlice 4 in scan 5 is an outlier\n")
    assert dwi_dti.count_outlier_slices(o) == 2


# -- with FSL -------------------------------------------------------------------------------


def manual_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fsl = find_fsl()
    env = {**os.environ, "FSLDIR": fsl.fsldir, "FSLOUTPUTTYPE": "NIFTI_GZ"}
    env["PATH"] = f"{fsl.fsldir}/bin:{env['PATH']}"
    folder = tmp_path / "manual"
    folder.mkdir()
    return env, folder


@pytest.mark.fsl
def test_dtifit_matches_the_script_and_qc_draws_the_fa_map(ws: Workspace, tmp_path: Path) -> None:
    fsl_or_skip()
    src = real_data()
    inputs = copy_real(ws, src)
    bvec = ws.root / "rawbids/sub-001/dwi/sub-001_dwi.bvec"
    shutil.copyfile(src / "dwi/sub-001_dwi.bvec", bvec)
    q = LocalJobQueue(ws)
    fit = {"dwi": inputs["dwi"], "bval": inputs["dwi_bval"], "bvec": ws.relpath(bvec)}
    outcome = run_step(ws, q, "dwi_dtifit", "sub-001", fit)
    assert outcome.action == Action.RAN, outcome.reason

    env, by = manual_env(tmp_path)

    def sh(*argv: str) -> None:
        subprocess.run(argv, cwd=by, env=env, check=True, capture_output=True)

    ap = src / "dwi/sub-001_dwi.nii.gz"
    sh("fslroi", str(ap), "b0", "0", "1")
    sh("bet2", "b0", "b0_brain", "-m")
    sh("dtifit", f"--data={ap}", "--out=dti", "--mask=b0_brain_mask.nii.gz",
       f"--bvecs={src / 'dwi/sub-001_dwi.bvec'}", f"--bvals={src / 'dwi/sub-001_dwi.bval'}",
       "--save_tensor")  # fmt: skip
    out = ws.root / OUT
    for ours, theirs in (("FA", "dti_FA"), ("MD", "dti_MD"), ("tensor", "dti_tensor")):
        assert np.array_equal(
            load(out / f"sub-001_desc-dti_{ours}.nii.gz"), load(by / f"{theirs}.nii.gz")
        ), ours

    qc = run_step(
        ws, q, "dwi_qc", "sub-001",
        {"fa": f"{OUT}/sub-001_desc-dti_FA.nii.gz", "mask": f"{OUT}/sub-001_desc-dtimask_mask.nii.gz"},
    )  # fmt: skip
    assert qc.action == Action.RAN, qc.reason
    assert (out / "sub-001_desc-dtifa_qc.png").stat().st_size > 1000


@pytest.mark.fsl
def test_qc_reports_eddys_motion_without_deciding(ws: Workspace) -> None:
    fsl_or_skip()
    img = ws.root / OUT / "sub-001_desc-dti_FA.nii.gz"
    img.parent.mkdir(parents=True, exist_ok=True)
    data = np.zeros((20, 20, 20), np.float32)
    data[5:15, 5:15, 5:15] = 0.5
    nib.save(nib.Nifti1Image(data, np.eye(4)), img)  # type: ignore[attr-defined]
    mask = ws.root / OUT / "sub-001_desc-dtimask_mask.nii.gz"
    nib.save(nib.Nifti1Image((data > 0).astype(np.float32), np.eye(4)), mask)  # type: ignore[attr-defined]
    rms = put_text(ws, f"{OUT}/rms.txt", "0 0\n1.5 1.5\n2.0 1.4\n")
    outliers = put_text(ws, f"{OUT}/out.txt", "Slice 3 in scan 5 is an outlier\n")
    step, ctx = build_context(
        ws, "dwi_qc", "sub-001", None,
        {"fa": ws.relpath(img), "mask": ws.relpath(mask), "movement_rms": rms,
         "outlier_report": outliers}, {},
    )  # fmt: skip
    outcome = run_step(
        ws, LocalJobQueue(ws), "dwi_qc", "sub-001",
        {"fa": ws.relpath(img), "mask": ws.relpath(mask), "movement_rms": rms,
         "outlier_report": outliers},
    )  # fmt: skip
    assert outcome.action == Action.RAN, outcome.reason
    items = {q.name: q for q in step.generate_qc(ctx)}
    mean = items["Mean movement relative to the previous volume (mm)"]
    assert mean.value == pytest.approx(0.967, abs=1e-3)
    assert mean.warning is None  # 0.967 mm is below the 1 mm proposal
    assert items["Slices eddy reports as outliers"].value == 1


@pytest.mark.fsl
@pytest.mark.slow
def test_eddy_matches_a_manual_eddy_cpu_run(ws: Workspace, tmp_path: Path) -> None:
    fsl = fsl_or_skip()
    src = real_data()
    copy_real(ws, src)
    bvec = ws.root / "rawbids/sub-001/dwi/sub-001_dwi.bvec"
    shutil.copyfile(src / "dwi/sub-001_dwi.bvec", bvec)
    dwi = "rawbids/sub-001/dwi/sub-001_dwi.nii.gz"
    outcome = run_step(
        ws, LocalJobQueue(ws), "dwi_eddy", "sub-001",
        {"dwi": dwi, "bval": "rawbids/sub-001/dwi/sub-001_dwi.bval", "bvec": ws.relpath(bvec),
         "dwi_json": "rawbids/sub-001/dwi/sub-001_dwi.json"},
        {"threads": 6},
    )  # fmt: skip
    assert outcome.action == Action.RAN, outcome.reason

    env, by = manual_env(tmp_path)

    def sh(*argv: str) -> None:
        subprocess.run(argv, cwd=by, env=env, check=True, capture_output=True)

    ap = src / "dwi/sub-001_dwi.nii.gz"
    n_vol = nib.load(str(ap)).shape[3]  # type: ignore[attr-defined]
    (by / "index.txt").write_text(" ".join(["1"] * n_vol) + "\n")
    sidecar = json.loads((src / "dwi/sub-001_dwi.json").read_text())
    from mrforge.steps.dwi_common import read_encoding

    (by / "acqparams.txt").write_text(read_encoding(sidecar).line + "\n")
    sh("fslroi", str(ap), "b0", "0", "1")
    sh("bet2", "b0", "b0_brain", "-m")
    sh(f"{fsl.fsldir}/bin/eddy_cpu", f"--imain={ap}", "--mask=b0_brain_mask",
       "--acqp=acqparams.txt", "--index=index.txt", f"--bvecs={src / 'dwi/sub-001_dwi.bvec'}",
       f"--bvals={src / 'dwi/sub-001_dwi.bval'}", "--nthr=6", "--out=eddy_corrected_data")  # fmt: skip
    ours = load(ws.root / OUT / "sub-001_desc-eddy_dwi.nii.gz")
    theirs = load(by / "eddy_corrected_data.nii.gz")
    assert ours.shape == theirs.shape
    # eddy is iterative and multi-threaded: the two runs agree closely, not necessarily bit by bit
    assert np.corrcoef(ours.ravel(), theirs.ravel())[0, 1] > 0.999
    assert np.allclose(
        np.loadtxt(ws.root / OUT / "sub-001_desc-eddy_dwi.bvec"),
        np.loadtxt(by / "eddy_corrected_data.eddy_rotated_bvecs"),
        atol=1e-2,
    )
