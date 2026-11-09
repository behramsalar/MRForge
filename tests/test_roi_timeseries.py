"""Stage 10c: mean time series per atlas region.

The pure functions and the input checks need no FSL. The ``fsl`` tests run the real step on a
synthetic image built on the atlas grid (known signal in every region), and compare with the
lab's own method: the mean over every voxel of the region (nibabel, as in its second script)."""

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge import atlases
from mrforge.engine import Action, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import FslInstall, find_fsl
from mrforge.runner.jobs import build_context
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.roi_timeseries import region_table, spread_columns, write_timeseries
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001/func"
BOLD = f"{D}/sub-001_task-rest_space-MNI152NLin6Asym_desc-denoised_bold.nii.gz"
T = 8


def save_bold(ws: Workspace, data: np.ndarray, affine: np.ndarray | None = None) -> None:
    path = ws.root / BOLD
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data.astype("float32"), np.eye(4) if affine is None else affine), path)


def synthetic_bold(atlas_id: str, empty: int | None = None, half: int | None = None):
    """Signal of region L at time t: 100 + L + (t % 5) * (L % 7 + 1), the same in all its voxels.
    Everything outside the atlas and the region ``empty`` has no signal; region ``half`` has
    signal in every second voxel only."""
    img = nib.load(atlases.volume_path(atlas_id))
    atlas = np.rint(img.get_fdata()).astype(int)
    data = np.zeros((*atlas.shape, T), dtype="float32")
    truth = {}
    for r in atlases.regions(atlas_id):
        series = np.array([100 + r.label + (t % 5) * (r.label % 7 + 1) for t in range(T)], float)
        truth[r.label] = series
        if r.label == empty:
            continue
        idx = np.argwhere(atlas == r.label)
        if r.label == half:
            idx = idx[::2]
        for i, j, k in idx:
            data[i, j, k, :] = series
    return data, atlas, img.affine, truth


MASK = f"{D}/sub-001_task-rest_space-MNI152NLin6Asym_desc-brain_mask.nii.gz"


def run_it(ws: Workspace, mask: bool = False, **params: object):
    inputs = {"bold": BOLD, **({"brain_mask": MASK} if mask else {})}
    return run_step(ws, LocalJobQueue(ws), "roi_timeseries", "sub-001", inputs, params)


# -- no FSL ---------------------------------------------------------------------------------


def test_region_table_counts_coverage_and_flags():
    regions = atlases.regions("schaefer100n7")[:3]
    atlas = np.zeros((4, 4, 4), int)
    atlas[0, 0, :] = 1  # 4 voxels
    atlas[1, 0, :] = 2  # 4 voxels
    atlas[2, 0, :] = 3  # 4 voxels
    used = atlas.copy()
    used[1, 0, :2] = 0  # region 2: half the voxels
    used[2, 0, :] = 0  # region 3: none
    rows = region_table(atlas, used, regions, 0.6)
    assert [r["coverage"] for r in rows] == [1.0, 0.5, 0.0]
    assert [r["low_coverage"] for r in rows] == [False, True, False]  # empty is not "low"
    assert [r["empty"] for r in rows] == [False, False, True]


def test_columns_are_found_by_label_value_not_by_position():
    regions = tuple(
        atlases.Region(label=lab, name=f"r{lab}", clean_name=f"r{lab}", hemisphere="L")
        for lab in (1, 2, 4, 7)  # gaps, like AAL3
    )
    # fslmeants writes one column per integer 1..7; labels 1, 4 and 7 have voxels with signal
    meants = np.arange(14, dtype=float).reshape(2, 7)
    out = spread_columns(meants, [7, 1, 4], regions)
    assert out[0, 0] == 0.0 and out[0, 2] == 3.0 and out[0, 3] == 6.0  # labels 1, 4, 7
    assert np.isnan(out[:, 1]).all()  # label 2 has no voxel with signal


def test_wrong_number_of_columns_is_an_error():
    regions = atlases.regions("schaefer100n7")[:3]
    with pytest.raises(ValueError, match="columns"):
        spread_columns(np.zeros((5, 2)), [1, 2, 3], regions)


def test_timeseries_file_layout(tmp_path: Path):
    path = tmp_path / "ts.tsv"
    write_timeseries(path, np.array([[1.0, np.nan], [2.5, 3.0]]), ["a", "b"])
    assert path.read_text() == "a\tb\n1.000000\tnan\n2.500000\t3.000000\n"


def test_output_names(tmp_path: Path):
    ws = Workspace.create(tmp_path / "ws")
    step, ctx = build_context(ws, "roi_timeseries", "sub-001", None, {"bold": BOLD}, {})
    out = step.expected_outputs(ctx)
    assert out.timeseries == (
        "sub-001_task-rest_space-MNI152NLin6Asym_seg-schaefer100n7_timeseries.tsv"
    )
    assert out.roi_info.endswith("seg-schaefer100n7_roi.json")
    assert out.atlas_used.endswith("seg-schaefer100n7_dseg.nii.gz")


def problems(ws: Workspace, **params: object):
    step, ctx = build_context(ws, "roi_timeseries", "sub-001", None, {"bold": BOLD}, params)
    return [p.code for p in step.validate_inputs(ctx)]


def test_an_image_not_on_the_2mm_grid_is_explained(tmp_path: Path):
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, np.ones((10, 10, 10, 4)))
    assert problems(ws) == ["NOT_ON_MNI_2MM_GRID"]


def test_one_millimetre_standard_space_is_explained(tmp_path: Path):
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, np.ones((182, 218, 182, 2), "float32"), np.diag([-1.0, 1, 1, 1]))
    assert problems(ws) == ["NOT_ON_MNI_2MM_GRID"]


def test_a_single_volume_is_not_a_time_series(tmp_path: Path):
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, np.ones(atlases.GRID_SHAPE))
    assert problems(ws) == ["BOLD_NOT_4D"]


def test_unknown_atlas_is_explained(tmp_path: Path):
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, np.ones((*atlases.GRID_SHAPE, 2)))
    assert problems(ws, atlas="brainnetome") == ["ATLAS_UNKNOWN"]


# -- real FSL -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fsl() -> FslInstall:
    try:
        return find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")


@pytest.mark.fsl
def test_signal_only_means_equal_the_true_series_and_the_report_is_honest(
    fsl: FslInstall, tmp_path: Path
):
    empty, half = 5, 7
    data, atlas, affine, truth = synthetic_bold("schaefer100n7", empty=empty, half=half)
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, data, affine)

    outcome = run_it(ws)
    assert outcome.action == Action.RAN, outcome.reason
    func = ws.derivatives_dir / "sub-001" / "func"
    stem = "sub-001_task-rest_space-MNI152NLin6Asym_seg-schaefer100n7"
    lines = (func / f"{stem}_timeseries.tsv").read_text().splitlines()
    header = lines[0].split("\t")
    values = np.array([[float(x) for x in ln.split("\t")] for ln in lines[1:]])
    regions = atlases.regions("schaefer100n7")
    assert header == [r.clean_name for r in regions] and values.shape == (T, 100)
    for j, r in enumerate(regions):
        if r.label == empty:
            assert np.isnan(values[:, j]).all()  # no voxel with signal: missing, not zero
        else:
            np.testing.assert_allclose(values[:, j], truth[r.label], atol=1e-3)  # incl. half

    info = json.loads((func / f"{stem}_roi.json").read_text())
    rows = {r["label"]: r for r in info["regions"]}
    assert rows[empty]["empty"] and rows[empty]["coverage"] == 0.0
    assert rows[half]["low_coverage"] is False or rows[half]["coverage"] >= 0.5  # about half
    assert 0.45 < rows[half]["coverage"] < 0.55
    assert rows[1]["coverage"] == 1.0 and info["n_empty"] == 1
    assert info["only_voxels_with_signal"] is True and info["volumes"] == T
    assert (func / f"{stem}_desc-roi_qc.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    again = run_it(ws)
    assert again.action == Action.REUSED


@pytest.mark.fsl
def test_averaging_every_voxel_matches_the_lab_script_exactly(fsl: FslInstall, tmp_path: Path):
    """With only_voxels_with_signal off, the result is the plain mean over all voxels of each
    region: what the lab's nibabel script computes (mask > 0.5, mean over voxels)."""
    half = 9
    data, atlas, affine, truth = synthetic_bold("schaefer100n7", half=half)
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, data, affine)
    assert run_it(ws, only_voxels_with_signal=False).action == Action.RAN
    func = ws.derivatives_dir / "sub-001" / "func"
    tsv = func / "sub-001_task-rest_space-MNI152NLin6Asym_seg-schaefer100n7_timeseries.tsv"
    got = np.loadtxt(tsv, skiprows=1)
    for j, r in enumerate(atlases.regions("schaefer100n7")):
        mask = atlas == r.label
        reference = data[mask, :].mean(axis=0)  # the script's computation
        np.testing.assert_allclose(got[:, j], reference, rtol=1e-5, atol=1e-3)
    assert got[:, 8].mean() < truth[9].mean() * 0.6  # region 9 really is diluted (about half)


@pytest.mark.fsl
def test_aal3_label_gaps_keep_columns_aligned(fsl: FslInstall, tmp_path: Path):
    data, atlas, affine, truth = synthetic_bold("aal3v2")
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, data, affine)
    assert run_it(ws, atlas="aal3v2").action == Action.RAN
    tsv = (
        ws.derivatives_dir
        / "sub-001/func/sub-001_task-rest_space-MNI152NLin6Asym_seg-aal3v2_timeseries.tsv"
    )
    got = np.loadtxt(tsv, skiprows=1)
    regions = atlases.regions("aal3v2")
    assert got.shape == (T, len(regions))
    for j in (0, 40, 100, len(regions) - 1):  # across the gap at labels 35 and 36
        np.testing.assert_allclose(got[:, j], truth[regions[j].label], atol=1e-3)


@pytest.mark.fsl
def test_changing_the_atlas_reruns_only_that_run(fsl: FslInstall, tmp_path: Path):
    data, _, affine, _ = synthetic_bold("schaefer100n7")
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, data, affine)
    first = run_step(ws, LocalJobQueue(ws), "roi_timeseries", "sub-001", {"bold": BOLD}, {},
                     label="roi_timeseries_schaefer100n7")  # fmt: skip
    other = run_step(ws, LocalJobQueue(ws), "roi_timeseries", "sub-001", {"bold": BOLD},
                     {"atlas": "schaefer100n17"}, label="roi_timeseries_schaefer100n17")  # fmt: skip
    assert first.action == Action.RAN and other.action == Action.RAN
    again = run_step(ws, LocalJobQueue(ws), "roi_timeseries", "sub-001", {"bold": BOLD}, {},
                     label="roi_timeseries_schaefer100n7")  # fmt: skip
    assert again.action == Action.REUSED
    func = ws.derivatives_dir / "sub-001" / "func"
    assert len(list(func.glob("*_timeseries.tsv"))) == 2  # both atlases kept side by side


@pytest.mark.fsl
def test_the_brain_mask_tells_brain_from_noise_where_every_voxel_varies(
    fsl: FslInstall, tmp_path: Path
):
    """Cleaned data is not masked: out-of-brain voxels vary too (real data: sub-ali). Only the
    recording's brain mask excludes them."""
    region = 7
    data, atlas, affine, truth = synthetic_bold("schaefer100n7")
    idx = np.argwhere(atlas == region)
    outside = idx[::2]  # half of the region lies outside the brain mask, with other values
    for i, j, k in outside:
        data[i, j, k, :] = truth[region] * 3 + 50
    brain = (atlas > 0).astype("float32")
    for i, j, k in outside:
        brain[i, j, k] = 0
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, data, affine)
    path = ws.root / MASK
    nib.save(nib.Nifti1Image(brain, affine), path)

    assert run_it(ws, mask=True).action == Action.RAN
    func = ws.derivatives_dir / "sub-001" / "func"
    stem = "sub-001_task-rest_space-MNI152NLin6Asym_seg-schaefer100n7"
    got = np.loadtxt(func / f"{stem}_timeseries.tsv", skiprows=1)
    j = [r.label for r in atlases.regions("schaefer100n7")].index(region)
    np.testing.assert_allclose(got[:, j], truth[region], atol=1e-3)  # outside voxels left out
    info = json.loads((func / f"{stem}_roi.json").read_text())
    assert 0.45 < info["regions"][j]["coverage"] < 0.55
    assert "brain mask" in info["signal_definition"] and info["brain_mask"] == MASK

    # without the mask, the same data cannot tell: the noise voxels are counted
    assert run_it(ws, mask=False).action == Action.RAN
    plain = np.loadtxt(func / f"{stem}_timeseries.tsv", skiprows=1)
    assert not np.allclose(plain[:, j], truth[region], atol=1.0)
    assert (
        "no brain mask" in json.loads((func / f"{stem}_roi.json").read_text())["signal_definition"]
    )


def test_a_brain_mask_on_another_grid_is_explained(tmp_path: Path):
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, np.ones((*atlases.GRID_SHAPE, 3)), np.diag([2.0, 2.0, 2.0, 1.0]))
    nib.save(nib.Nifti1Image(np.ones((10, 10, 10), "float32"), np.eye(4)), ws.root / MASK)
    step, ctx = build_context(
        ws, "roi_timeseries", "sub-001", None, {"bold": BOLD, "brain_mask": MASK}, {}
    )
    assert [p.code for p in step.validate_inputs(ctx)] == ["MASK_GRID_DIFFERS"]
