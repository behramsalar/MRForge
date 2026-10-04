"""Tiny NIfTI sanity check (no imaging library needed)."""

from __future__ import annotations

import gzip
import struct
from pathlib import Path


def is_readable_nifti(path: Path) -> bool:
    """True if the file starts with a valid NIfTI-1 header (size field 348) or a NIfTI-2
    header (size field 540). Handles .nii and .nii.gz in either byte order."""
    try:
        opener = gzip.open if path.name.endswith(".gz") else open
        with opener(path, "rb") as fh:
            head = fh.read(4)
    except (OSError, EOFError):
        return False
    if len(head) < 4:
        return False
    sizes = {struct.unpack("<i", head)[0], struct.unpack(">i", head)[0]}
    return bool(sizes & {348, 540})


def image_info(path: Path) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """(shape, voxel sizes) from the NIfTI header; the fourth voxel size of a time series is
    its repetition time in seconds."""
    import nibabel as nib

    header = nib.load(path).header  # type: ignore[attr-defined]
    return (
        tuple(int(n) for n in header.get_data_shape()),  # type: ignore[attr-defined]
        tuple(float(z) for z in header.get_zooms()),  # type: ignore[attr-defined]
    )
