"""One picture per ICA component for the review screen: where the component is in the brain,
how it behaves over time, and which frequencies it contains.

Drawn with matplotlib from MELODIC's own output (spatial z-map, mixing matrix and power
spectrum), so a component can be judged at a glance, as in MELODIC's own report. The picture
only shows; it never labels anything (CLAUDE.md principle 6).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

Arr = NDArray[np.float64]

# REVIEW(domain): the z threshold of the overlay (MELODIC's report uses a mixture-model
# threshold; 2.3 is the common display threshold for its z-maps).
Z_THRESHOLD = 2.3
SLICE_SPACING_MM = 5.0  # distance between the slices of the summary picture
Z_MAX = 8.0  # z at which the colour is at its brightest


def peak_voxel(ic_map: Arr, mask: NDArray[np.bool_]) -> tuple[int, int, int]:
    """Where the component is strongest inside the brain (largest absolute z)."""
    strength = np.where(mask, np.abs(ic_map), 0)
    x, y, z = (int(v) for v in np.unravel_index(int(np.argmax(strength)), strength.shape))
    return x, y, z


def _overlay(ax: Any, background: Arr, zmap: Arr, lo: float, hi: float) -> None:
    """One plane: the mean image in grey, positive z in red-yellow, negative z in blue-cyan."""
    ax.imshow(np.rot90(background), cmap="gray", vmin=lo, vmax=hi, interpolation="nearest")
    z = np.rot90(zmap)
    for sign, cmap in ((1, "autumn"), (-1, "winter")):
        shown = np.where(sign * z < Z_THRESHOLD, np.nan, np.abs(z))  # NaN is drawn clear
        ax.imshow(shown, cmap=cmap, vmin=Z_THRESHOLD, vmax=Z_MAX, interpolation="nearest")
    ax.set_axis_off()


def _plane(
    bg: Arr, bg_affine: Arr, axis: int, index: int, values: Arr, values_affine: Arr
) -> tuple[Arr, Arr]:
    """One slice of the background and the same slice of ``values`` (a map that may sit on
    another grid, for example 2 mm on a 1 mm background), nearest-neighbour."""
    shape = list(bg.shape)
    ranges: list[Any] = [np.arange(n) for n in shape]
    ranges[axis] = np.array([index])
    grid = np.stack(np.meshgrid(*ranges, indexing="ij"), axis=-1).reshape(-1, 3)
    homogeneous = np.c_[grid, np.ones(len(grid))]
    mapped = np.rint((np.linalg.inv(values_affine) @ bg_affine @ homogeneous.T).T[:, :3]).astype(
        int
    )
    inside = np.all((mapped >= 0) & (mapped < np.array(values.shape)), axis=1)
    sampled = np.zeros(len(grid))
    sampled[inside] = values[tuple(mapped[inside].T)]
    flat_shape = [n for k, n in enumerate(shape) if k != axis]
    plane_bg = np.take(bg, index, axis=axis)
    return plane_bg, sampled.reshape(flat_shape)


def draw_planes(
    background: Arr,  # 3D background (RAS orientation)
    background_affine: Arr,
    values: Arr,  # 3D z-map (RAS orientation), possibly on a coarser grid
    values_affine: Arr,
    number: int,
    total: int,
    out: Path,
    columns: int = 12,
    spacing_mm: float = SLICE_SPACING_MM,
) -> None:
    """A summary of the component: slices every few millimetres through the whole brain in
    the axial, coronal and sagittal planes, cropped to the brain, with the map in red-yellow
    (positive) and blue (negative). Close spacing so that a small area is not missed."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    inside = background > 0.05 * float(background.max())
    hi = float(np.percentile(background[inside], 99.5)) if inside.any() else 1.0
    box = [
        np.flatnonzero(inside.any(axis=tuple(k for k in range(3) if k != ax))) for ax in range(3)
    ]
    if any(b.size == 0 for b in box):
        box = [np.arange(n) for n in background.shape]
    voxel = np.sqrt((background_affine[:3, :3] ** 2).sum(axis=0))
    groups = []
    for axis, name in ((2, "Axial"), (1, "Coronal"), (0, "Sagittal")):
        step = max(1, int(round(spacing_mm / float(voxel[axis]))))
        picks = list(range(int(box[axis][0]), int(box[axis][-1]) + 1, step))
        others = [ax for ax in range(3) if ax != axis]
        groups.append(
            (axis, name, picks, [slice(int(box[ax][0]), int(box[ax][-1]) + 1) for ax in others])
        )
    tile_ratio = max(
        (g[3][1].stop - g[3][1].start) / max(1, g[3][0].stop - g[3][0].start) for g in groups
    )  # height / width of a cropped tile (images are shown rotated)
    rows = [(len(g[2]) + columns - 1) // columns for g in groups]
    fig = plt.figure(figsize=(14, 14 * tile_ratio * sum(rows) / columns + 0.5), dpi=80)
    grid = fig.add_gridspec(
        sum(rows), columns, wspace=0.02, hspace=0.02, left=0, right=1, top=0.97, bottom=0
    )
    row0 = 0
    for (axis, name, picks, crop), n_rows in zip(groups, rows, strict=True):
        for k in range(n_rows * columns):
            ax = fig.add_subplot(grid[row0 + k // columns, k % columns])
            ax.set_axis_off()
            if k >= len(picks):
                continue
            bg_slice, z_slice = _plane(
                background, background_affine, axis, picks[k], values, values_affine
            )
            bg_slice, z_slice = bg_slice[crop[0], crop[1]], z_slice[crop[0], crop[1]]
            ax.imshow(np.rot90(bg_slice), cmap="gray", vmin=0, vmax=hi, interpolation="nearest")
            z = np.rot90(z_slice)
            for sign, cmap in ((1, "autumn"), (-1, "winter")):
                shown = np.where(sign * z < Z_THRESHOLD, np.nan, np.abs(z))
                ax.imshow(shown, cmap=cmap, vmin=Z_THRESHOLD, vmax=Z_MAX, interpolation="nearest")
            if k == 0:
                ax.text(
                    0.03, 0.97, name, transform=ax.transAxes, color="white", fontsize=9, va="top"
                )
        row0 += n_rows
    fig.patch.set_facecolor("black")
    fig.suptitle(
        f"Component {number} of {total} · a slice every {spacing_mm:g} mm",
        fontsize=10,
        y=0.995,
        color="white",
    )
    fig.savefig(out, facecolor="black")
    plt.close(fig)


def draw_plots(
    time_course: Arr, power: Arr, tr_s: float, number: int, total: int, out: Path,
    variance_pct: float | None = None,
) -> None:  # fmt: skip
    """Only the time course and the power spectrum (the review screen shows the brain maps
    in its interactive viewer)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax_t, ax_f) = plt.subplots(
        1, 2, figsize=(11, 2.6), dpi=90, gridspec_kw={"width_ratios": [2, 1]}
    )
    t = np.arange(len(time_course)) * tr_s
    ax_t.plot(t, time_course, color="black", linewidth=0.8)
    ax_t.set_xlabel("Time (s)")
    ax_t.set_ylabel("Component strength")
    ax_t.set_title("Time course", fontsize=10)
    freqs = np.linspace(0, 0.5 / tr_s, len(power))
    ax_f.plot(freqs, power, color="tab:blue", linewidth=0.9)
    ax_f.set_xlabel("Frequency (Hz)")
    ax_f.set_ylabel("Power")
    ax_f.set_title("Frequencies", fontsize=10)
    for ax in (ax_t, ax_f):
        ax.margins(x=0)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def draw_component(
    ic_map: Arr,  # 3D z-map of this component
    background: Arr,  # 3D mean functional image
    mask: NDArray[np.bool_],  # 3D brain mask
    time_course: Arr,  # one value per volume
    power: Arr,  # power spectrum, from 0 Hz to the Nyquist frequency
    tr_s: float,
    number: int,
    total: int,
    out: Path,
    variance_pct: float | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    px, py, pz = peak_voxel(ic_map, mask)
    lo, hi = (0.0, float(np.percentile(background[mask], 99.5))) if mask.any() else (0.0, 1.0)
    fig = plt.figure(figsize=(11, 7.2), dpi=90)
    grid = fig.add_gridspec(2, 3, height_ratios=[1.6, 1], hspace=0.12, wspace=0.05)
    planes = (
        ("Axial", background[:, :, pz], ic_map[:, :, pz]),
        ("Coronal", background[:, py, :], ic_map[:, py, :]),
        ("Sagittal", background[px, :, :], ic_map[px, :, :]),
    )
    for k, (title, bg, zmap) in enumerate(planes):
        ax = fig.add_subplot(grid[0, k])
        _overlay(ax, bg, zmap, float(lo), float(hi))
        ax.set_title(title, fontsize=10)
    t = np.arange(len(time_course)) * tr_s
    ax_t = fig.add_subplot(grid[1, :2])
    ax_t.plot(t, time_course, color="black", linewidth=0.8)
    ax_t.set_xlabel("Time (s)")
    ax_t.set_ylabel("Component\nstrength")
    ax_t.margins(x=0)
    ax_t.grid(alpha=0.3)
    ax_f = fig.add_subplot(grid[1, 2])
    freqs = np.linspace(0, 0.5 / tr_s, len(power))
    ax_f.plot(freqs, power, color="tab:blue", linewidth=0.9)
    ax_f.set_xlabel("Frequency (Hz)")
    ax_f.set_ylabel("Power")
    ax_f.margins(x=0)
    ax_f.grid(alpha=0.3)
    extra = f" · explains {variance_pct:.1f}% of the variance" if variance_pct is not None else ""
    fig.suptitle(
        f"Component {number} of {total}{extra} · red/yellow = positive, blue = negative "
        f"(slices through the strongest point)",
        fontsize=11,
    )
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
