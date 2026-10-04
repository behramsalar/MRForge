"""Stage 5c: FEAT preprocessing step. Unit tests use tiny synthetic images; the real-FSL test
(marked ``fsl`` and ``realdata``) runs FEAT on a 20-volume cut of the real test session."""

import json
import shutil
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge.runner.jobs import build_context
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.base import Problem
from mrforge.steps.feat_preproc import (
    FeatPreprocStep,
    _explain_failure,
    native_folder_name,
)
from mrforge.workspace import Workspace

BOLD = "rawbids/sub-001/func/sub-001_task-rest_bold.nii.gz"
SIDECAR = {
    "RepetitionTime": 2.0,
    "EchoTime": 0.03,
    "PhaseEncodingDirection": "j-",
    "EffectiveEchoSpacing": 0.0003,
}


def make_ws(
    tmp_path: Path, volumes: int = 12, sidecar: dict[str, object] | None = None
) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    path = ws.root / BOLD
    path.parent.mkdir(parents=True)
    img = nib.Nifti1Image(np.ones((8, 8, 4, volumes), dtype="int16"), np.diag([3.0, 3.0, 3.0, 1.0]))
    img.header.set_zooms((3.0, 3.0, 3.0, 2.5))  # the header TR differs from the sidecar on purpose
    nib.save(img, path)
    (ws.root / BOLD.replace(".nii.gz", ".json")).write_text(json.dumps(sidecar or SIDECAR))
    return ws


def touch_images(ws: Workspace, *names: str) -> None:
    for name in names:
        path = ws.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype="int16"), np.eye(4)), path)


ANAT = {
    "t1_head": "derivatives/mrforge/sub-001/anat/sub-001_desc-biascorr_T1w.nii.gz",
    "t1_brain": "derivatives/mrforge/sub-001/anat/sub-001_desc-brain_T1w.nii.gz",
    "t1_seg": "derivatives/mrforge/sub-001/anat/sub-001_dseg.nii.gz",
}
FMAP = {
    "fieldmap": "derivatives/mrforge/sub-001/fmap/sub-001_desc-prepared_fieldmap.nii.gz",
    "fieldmap_magnitude_brain": "derivatives/mrforge/sub-001/fmap/sub-001_desc-brain_magnitude1.nii.gz",
    "fieldmap_magnitude": "rawbids/sub-001/fmap/sub-001_magnitude1.nii.gz",
}


def problems(
    ws: Workspace, inputs: dict[str, str], params: dict[str, object] | None = None
) -> list[Problem]:
    step, ctx = build_context(
        ws, "feat_preproc", "sub-001", None, {"bold": BOLD, **inputs}, params or {}
    )
    return step.validate_inputs(ctx)


def test_native_folder_is_named_after_the_input() -> None:
    assert native_folder_name(BOLD) == "sub-001_task-rest_bold.feat"


def test_bold_alone_is_valid(tmp_path: Path) -> None:
    assert problems(make_ws(tmp_path), {}) == []


def test_partial_structural_images_are_refused(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    touch_images(ws, *ANAT.values())
    found = problems(ws, {"t1_brain": ANAT["t1_brain"]})
    assert [p.code for p in found] == ["FEAT_INPUTS_INCOMPLETE"]


def test_fieldmap_needs_the_structural_image(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    touch_images(ws, *FMAP.values())
    assert [p.code for p in problems(ws, FMAP)] == ["FEAT_FIELDMAP_NEEDS_T1"]


def test_valid_inputs_with_everything(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    touch_images(ws, *ANAT.values(), *FMAP.values())
    assert problems(ws, {**ANAT, **FMAP}) == []


@pytest.mark.parametrize("missing", ["PhaseEncodingDirection", "EffectiveEchoSpacing", "EchoTime"])
def test_unwarping_facts_missing_from_the_scan_are_explained(tmp_path: Path, missing: str) -> None:
    ws = make_ws(tmp_path, sidecar={k: v for k, v in SIDECAR.items() if k != missing})
    touch_images(ws, *ANAT.values(), *FMAP.values())
    found = problems(ws, {**ANAT, **FMAP})
    assert [p.code for p in found] == ["UNWARP_INFO_MISSING"]
    assert "without distortion correction" in found[0].suggested_action


def test_too_short_run_is_explained(tmp_path: Path) -> None:
    found = problems(make_ws(tmp_path, volumes=5), {}, {"delete_volumes": 5})
    assert [p.code for p in found] == ["BOLD_TOO_SHORT"]


def test_design_uses_sidecar_values_and_staged_files(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    touch_images(ws, *ANAT.values(), *FMAP.values())
    step, ctx = build_context(
        ws, "feat_preproc", "sub-001", None, {"bold": BOLD, **ANAT, **FMAP}, {}
    )
    assert isinstance(step, FeatPreprocStep)
    stage = ctx.run_dir / "work" / "stage"
    design = step._design(ctx, stage)
    assert design.tr_s == 2.0  # the sidecar wins over the header
    assert design.volumes == 12 and design.voxels_per_volume == 8 * 8 * 4
    assert design.dwell_ms == pytest.approx(0.3) and design.epi_te_ms == pytest.approx(30.0)
    assert design.unwarp_direction == "y-"
    assert design.highres_brain == str(stage / "T1_brain")
    assert design.func.endswith("sub-001_task-rest_bold") and ".nii" not in design.func


def test_expected_outputs_depend_on_what_is_done(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    step, ctx = build_context(ws, "feat_preproc", "sub-001", None, {"bold": BOLD}, {})
    plain = step.expected_outputs(ctx)
    assert plain.preproc_bold == "sub-001_task-rest_desc-preproc_bold.nii.gz"
    assert plain.to_t1_affine is None and plain.to_t1_warp is None
    step, ctx = build_context(ws, "feat_preproc", "sub-001", None, {"bold": BOLD, **ANAT}, {})
    registered = step.expected_outputs(ctx)
    assert (
        registered.to_t1_affine
        == "sub-001_task-rest_from-boldref_to-T1w_mode-image_desc-affine_xfm.mat"
    )
    assert registered.to_t1_warp is None
    step, ctx = build_context(
        ws, "feat_preproc", "sub-001", None, {"bold": BOLD, **ANAT, **FMAP}, {}
    )
    assert step.expected_outputs(ctx).to_t1_warp is not None


def test_known_feat_failures_are_translated(tmp_path: Path) -> None:
    feat = tmp_path / "x.feat"
    feat.mkdir()
    (feat / "report_log.html").write_text(
        "<pre>Error: Brain-extracted fieldmap appears to still contain non-brain voxels. "
        "Aborting unwarping</pre>"
    )
    err = _explain_failure(feat, tmp_path / "stderr.log")
    assert err.code == "FEAT_FIELDMAP_NOT_BRAIN_EXTRACTED"
    assert "brain-extraction" in err.suggested_action
    unknown = _explain_failure(tmp_path / "missing.feat", tmp_path / "stderr.log")
    assert unknown.code == "FEAT_FAILED" and unknown.suggested_action


def test_leftover_feat_folder_is_removed_before_a_run(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    step, ctx = build_context(ws, "feat_preproc", "sub-001", None, {"bold": BOLD}, {})
    leftover = ctx.output_dir / "sub-001_task-rest_bold.feat"
    leftover.mkdir(parents=True)
    (leftover / "partial").write_text("x")
    step.prepare(ctx)
    assert not leftover.exists()
    shutil.rmtree(ctx.run_dir, ignore_errors=True)


# -- slice timing (5g) -----------------------------------------------------------------------


def test_slice_timing_values_are_negative_fractions_of_tr_about_mid_tr() -> None:
    from mrforge.steps.feat_preproc import slice_timing_fractions

    assert slice_timing_fractions([0.0, 1.0, 0.5, 1.5], 2.0) == [0.5, 0.0, 0.25, -0.25]


def test_slice_timing_needs_the_scans_slice_times(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)  # sidecar without SliceTiming
    found = problems(ws, {}, {"slice_timing": True})
    assert [p.code for p in found] == ["SLICE_TIMING_MISSING"]
    assert "without slice timing" in found[0].suggested_action


def test_slice_timing_must_match_the_slices(tmp_path: Path) -> None:
    ws = make_ws(tmp_path, sidecar={**SIDECAR, "SliceTiming": [0.0, 1.0, 0.5]})  # image has 4
    assert [p.code for p in problems(ws, {}, {"slice_timing": True})] == ["SLICE_TIMING_MISMATCH"]


def test_slice_timing_is_written_into_the_design(tmp_path: Path) -> None:
    ws = make_ws(tmp_path, sidecar={**SIDECAR, "SliceTiming": [0.0, 1.0, 0.5, 1.5]})
    assert problems(ws, {}, {"slice_timing": True}) == []
    step, ctx = build_context(
        ws, "feat_preproc", "sub-001", None, {"bold": BOLD}, {"slice_timing": True}
    )
    design = step._design(ctx, ctx.run_dir / "work" / "stage")  # type: ignore[attr-defined]
    assert design.slice_timing == "file" and design.slice_timing_file.endswith("slice_timing.txt")


@pytest.mark.fsl
def test_the_slice_timing_file_really_aligns_the_slices(tmp_path: Path) -> None:
    """On synthetic data with a known delay per slice, the values we write make slicetimer
    bring every slice onto the same time (the sign was found this way, not assumed)."""
    import subprocess

    from mrforge.errors import StepError
    from mrforge.fsl_env import find_fsl
    from mrforge.steps.feat_preproc import slice_timing_fractions

    try:
        fsl = find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")
    tr, nz, nv, freq = 2.0, 8, 80, 0.04
    times = [k / nz * tr for k in range(nz)]
    vols = np.arange(nv) * tr
    data = np.zeros((4, 4, nz, nv), dtype="float32")
    for k in range(nz):
        data[:, :, k, :] = 1000 + 100 * np.sin(2 * np.pi * freq * (vols + times[k]))
    img = nib.Nifti1Image(data, np.diag([3.0, 3.0, 3.0, 1.0]))
    img.header.set_zooms((3.0, 3.0, 3.0, tr))
    nib.save(img, tmp_path / "syn.nii.gz")
    (tmp_path / "tc.txt").write_text(
        "".join(f"{v:.6f}\n" for v in slice_timing_fractions(times, tr))
    )
    subprocess.run(
        ["slicetimer", "-i", str(tmp_path / "syn"), "-o", str(tmp_path / "out"), "-r", str(tr),
         f"--tcustom={tmp_path / 'tc.txt'}"],
        env=fsl.env, check=True,
    )  # fmt: skip

    def delays(path: Path) -> list[float]:
        d = nib.load(path).get_fdata()  # type: ignore[attr-defined]
        x = vols[10:70]
        design = np.c_[np.sin(2 * np.pi * freq * x), np.cos(2 * np.pi * freq * x)]
        out = []
        for k in range(nz):
            y = d[0, 0, k, 10:70] - d[0, 0, k, 10:70].mean()
            a, b = np.linalg.lstsq(design, y, rcond=None)[0]
            out.append(float(np.arctan2(b, a) / (2 * np.pi * freq)))
        return out

    before, after = delays(tmp_path / "syn.nii.gz"), delays(tmp_path / "out.nii.gz")
    assert max(before) - min(before) > 1.0  # the slices really were out of step
    assert max(after) - min(after) < 0.05  # and now they are on the same time
