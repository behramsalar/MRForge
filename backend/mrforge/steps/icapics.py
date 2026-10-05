"""One picture per ICA component for the review screen: where the component is in the brain,
how it behaves over time, and which frequencies it contains.

Drawn with matplotlib from MELODIC's own output (spatial z-map, mixing matrix and power
spectrum), so a component can be judged at a glance, as in MELODIC's own report. The picture
only shows; it never labels anything (CLAUDE.md principle 6).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

Arr = NDArray[np.float64]

# REVIEW(domain): the z threshold of the overlay (MELODIC's report uses a mixture-model
# threshold; 2.3 is the common display threshold for its z-maps).
Z_THRESHOLD = 2.3
N_SLICES = 12


def spaced_slices(mask: NDArray[np.bool_], count: int = N_SLICES) -> list[int]:
    """Axial slice numbers spread over the part of the volume that holds brain."""
    zs = np.flatnonzero(mask.reshape(-1, mask.shape[2]).any(axis=0))
    if zs.size == 0:
        zs = np.arange(mask.shape[2])
    picks = np.linspace(zs[0], zs[-1], min(count, zs.size))
    return sorted({int(round(p)) for p in picks})


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

    slices = spaced_slices(mask)
    cols = 6
    rows = (len(slices) + cols - 1) // cols
    fig = plt.figure(figsize=(11, 2.1 * rows + 2.3), dpi=90)
    grid = fig.add_gridspec(rows + 1, cols, height_ratios=[1] * rows + [1.15], hspace=0.15)
    lo, hi = np.percentile(background[mask > 0], [2, 98]) if mask.any() else (0, 1)
    for k, z in enumerate(slices):
        ax = fig.add_subplot(grid[k // cols, k % cols])
        ax.imshow(np.rot90(background[:, :, z]), cmap="gray", vmin=lo, vmax=hi)
        zmap = np.rot90(ic_map[:, :, z])
        shown = np.where(np.abs(zmap) < Z_THRESHOLD, np.nan, zmap)  # NaN is drawn transparent
        ax.imshow(shown, cmap="coolwarm", vmin=-8, vmax=8, alpha=0.85)
        ax.set_axis_off()
    t = np.arange(len(time_course)) * tr_s
    ax_t = fig.add_subplot(grid[rows, : cols - 2])
    ax_t.plot(t, time_course, color="black", linewidth=0.8)
    ax_t.set_xlabel("Time (s)")
    ax_t.set_ylabel("Component\nstrength")
    ax_t.margins(x=0)
    ax_t.grid(alpha=0.3)
    ax_f = fig.add_subplot(grid[rows, cols - 2 :])
    freqs = np.linspace(0, 0.5 / tr_s, len(power))
    ax_f.plot(freqs, power, color="tab:blue", linewidth=0.9)
    ax_f.set_xlabel("Frequency (Hz)")
    ax_f.set_ylabel("Power")
    ax_f.margins(x=0)
    ax_f.grid(alpha=0.3)
    extra = f" · explains {variance_pct:.1f}% of the variance" if variance_pct is not None else ""
    fig.suptitle(f"Component {number} of {total}{extra}", y=0.995)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
