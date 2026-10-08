"""Stage 5d: motion metrics, plots and registration pictures (QC reports; it never decides)."""

import json
import math
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge.engine import Action, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import FslInstall, find_fsl
from mrforge.provenance import read_provenance
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.func_qc import (
    draw_motion_plot,
    framewise_displacement,
    motion_metrics,
    read_motion,
)
from mrforge.workspace import Workspace

HEADER = "rot_x\trot_y\trot_z\ttrans_x\ttrans_y\ttrans_z"


def test_fd_of_a_one_millimetre_shift_is_one() -> None:
    rows = [[0, 0, 0, 0, 0, 0], [0, 0, 0, 1, 0, 0], [0, 0, 0, 1, 0, 0]]
    assert framewise_displacement([[float(v) for v in r] for r in rows]) == [0.0, 1.0, 0.0]


def test_fd_of_a_small_rotation_is_arc_length_on_the_head() -> None:
    rows = [[0.0] * 6, [0.01, 0, 0, 0, 0, 0]]  # 0.01 rad on a 50 mm sphere is 0.5 mm
    assert framewise_displacement(rows, 50.0)[1] == pytest.approx(0.5)
    assert framewise_displacement(rows, 80.0)[1] == pytest.approx(0.8)  # radius is a setting


def test_fd_sums_all_six_parameters() -> None:
    rows = [[0.0] * 6, [0.002, -0.004, 0.001, 0.1, -0.2, 0.3]]
    expected = 0.1 + 0.2 + 0.3 + 50 * (0.002 + 0.004 + 0.001)
    assert framewise_displacement(rows)[1] == pytest.approx(expected)


def test_metrics_report_but_do_not_judge() -> None:
    rows = [[0.0] * 6, [0, 0, 0, 0.2, 0, 0], [0, 0, 0, 1.0, 0, 0], [0, 0, 0, 1.1, 0, 0]]
    fd = framewise_displacement(rows)
    m = motion_metrics(rows, fd, 0.5, 50.0)
    assert m["n_volumes"] == 4 and m["fd_max_mm"] == pytest.approx(0.8)
    assert m["fd_above_threshold"] == 1
    assert m["fd_median_mm"] == pytest.approx(0.15) and m["fd_mean_mm"] == pytest.approx(0.275)
    assert m["max_abs_translation_mm"] == pytest.approx(1.1)
    assert m["max_abs_rotation_deg"] == 0.0
    assert not any("exclude" in str(k).lower() for k in m)  # no verdicts, only numbers


def test_motion_table_with_wrong_columns_is_explained(tmp_path: Path) -> None:
    path = tmp_path / "m.tsv"
    path.write_text("a\tb\n1\t2\n")
    with pytest.raises(StepError) as err:
        read_motion(path)
    assert err.value.code == "MOTION_TABLE_INVALID" and err.value.suggested_action


def test_motion_table_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "m.tsv"
    path.write_text(HEADER + "\n0.1\t0.2\t0.3\t1\t2\t3\n")
    assert read_motion(path) == [[0.1, 0.2, 0.3, 1.0, 2.0, 3.0]]


def test_motion_plot_is_a_png(tmp_path: Path) -> None:
    rows = [[0.0, 0, 0, 0, 0, 0], [0.001, 0, 0, 0.1, 0, 0], [0.0, 0.002, 0, 0.2, 0.1, 0]]
    out = tmp_path / "plot.png"
    draw_motion_plot(rows, framewise_displacement(rows), 0.5, out)
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# -- real FSL (slicer, pngappend, fslmaths) with a synthetic phantom -----------------------------


@pytest.fixture(scope="module")
def fsl() -> FslInstall:
    try:
        return find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")


def build_workspace(tmp_path: Path, unwarped: bool) -> tuple[Workspace, dict[str, str]]:
    ws = Workspace.create(tmp_path / "ws")
    d = "derivatives/mrforge/sub-001"
    shape = (24, 24, 16)
    x, y, z = np.meshgrid(*(np.linspace(-1, 1, n) for n in shape), indexing="ij")
    head = (x**2 + y**2 + (z * 1.3) ** 2 < 0.8).astype("float32") * 500
    seg = np.where(x**2 + y**2 + (z * 1.3) ** 2 < 0.3, 3, np.where(head > 0, 2, 0)).astype("int16")
    inputs = {
        "motion": f"{d}/func/sub-001_task-rest_desc-motion_timeseries.tsv",
        "boldref_t1": f"{d}/func/sub-001_task-rest_space-T1w_desc-feat_boldref.nii.gz",
        "t1_head": f"{d}/anat/sub-001_desc-biascorr_T1w.nii.gz",
        "t1_seg": f"{d}/anat/sub-001_dseg.nii.gz",
    }
    if unwarped:
        inputs["boldref_distorted_t1"] = (
            f"{d}/func/sub-001_task-rest_space-T1w_desc-distorted_boldref.nii.gz"
        )
    images = {"boldref_t1": head, "t1_head": head, "t1_seg": seg, "boldref_distorted_t1": head}
    for key, rel in inputs.items():
        path = ws.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if key == "motion":
            path.write_text(
                HEADER + "\n" + "\n".join(f"0\t0\t0\t{0.1 * i:g}\t0\t0" for i in range(6)) + "\n"
            )
        else:
            nib.save(nib.Nifti1Image(images[key], np.diag([3.0, 3.0, 3.0, 1.0])), path)
    return ws, inputs


@pytest.mark.fsl
@pytest.mark.parametrize("unwarped", [False, True], ids=["no-fieldmap", "with-fieldmap"])
def test_step_makes_pictures_numbers_and_records_qc(
    tmp_path: Path, fsl: FslInstall, unwarped: bool
) -> None:
    ws, inputs = build_workspace(tmp_path, unwarped)
    outcome = run_step(ws, LocalJobQueue(ws), "func_qc", "sub-001", inputs, {})
    assert outcome.action == Action.RAN, outcome.reason
    func = ws.derivatives_dir / "sub-001" / "func"
    names = {p.name for p in func.glob("*_qc.*")}
    expected = {
        "sub-001_task-rest_desc-motion_qc.png",
        "sub-001_task-rest_desc-registration_qc.png",
        "sub-001_task-rest_desc-metrics_qc.json",
    } | ({"sub-001_task-rest_desc-unwarping_qc.png"} if unwarped else set())
    assert names == expected
    for png in func.glob("*_qc.png"):
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and png.stat().st_size > 1000
    metrics = json.loads((func / "sub-001_task-rest_desc-metrics_qc.json").read_text())
    assert metrics["fd_max_mm"] == pytest.approx(0.1) and math.isclose(
        metrics["fd_mean_mm"], 0.5 / 6
    )

    # QC results are part of the permanent record of the run
    prov = read_provenance(func / "_runs" / "func_qc_task-rest")
    assert prov is not None
    qc = {item.name: item for item in prov.qc}
    assert qc["Largest framewise displacement (mm)"].value == pytest.approx(0.1)
    assert qc["Head motion"].path == "sub-001_task-rest_desc-motion_qc.png"
    assert ("Distortion correction (before above, after below)" in qc) == unwarped
    # the single slices of the registration picture are kept and listed (12 per row, 2 rows)
    reg = qc["Registration to the T1"]
    assert {sl.layer for sl in reg.slices} == {"functional", "t1"} and len(reg.slices) == 24
    assert {sl.plane for sl in reg.slices} == {"sagittal", "coronal", "axial"}
    assert all((func / sl.path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" for sl in reg.slices)
    assert ("Distortion correction (before above, after below)" in qc) == unwarped
    if unwarped:
        assert len(qc["Distortion correction (before above, after below)"].slices) == 24
    again = run_step(ws, LocalJobQueue(ws), "func_qc", "sub-001", inputs, {})
    assert again.action == Action.REUSED
