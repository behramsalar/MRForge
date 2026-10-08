"""The slice summary of a component respects the real voxel size (not cubic voxels)."""

from pathlib import Path

import numpy as np

from mrforge.steps.icapics import draw_planes


def picture_height(tmp_path: Path, voxel: tuple[float, float, float], name: str) -> int:
    from matplotlib.image import imread

    rng = np.random.default_rng(0)
    shape = (40, 40, 40)
    background = rng.random(shape) + 1.0
    values = rng.normal(size=shape) * 4
    affine = np.diag([*voxel, 1.0])
    out = tmp_path / name
    draw_planes(background, affine, values, affine, 1, 1, out, columns=6)
    return int(imread(out).shape[0])


def test_thick_slices_make_coronal_and_sagittal_tiles_proportionally_taller(tmp_path: Path) -> None:
    cubic = picture_height(tmp_path, (1.0, 1.0, 1.0), "cubic.png")
    thick = picture_height(tmp_path, (0.5, 0.5, 2.0), "thick.png")
    # In millimetres the thick-slice brain is four times taller than wide in every
    # coronal and sagittal tile; counting voxels would have drawn it as square.
    assert thick > cubic * 1.5
