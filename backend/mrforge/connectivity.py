"""ROI time series and correlation matrices (Stage 10): the choices the user can make.

The stage itself (``ConnectivityStage`` in ``processing.py``) turns these into separate steps,
one pair (``roi_timeseries``, ``roi_correlation``) per recording and atlas.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectivityOptions(BaseModel):
    # Which atlases to extract from; each one keeps its own results (several can be chosen).
    atlases: list[str] = Field(default_factory=lambda: ["schaefer100n7"])
    # REVIEW(domain): average only voxels with signal (inside the recording's brain mask).
    # False averages every voxel of each region, as the lab's own scripts do.
    only_voxels_with_signal: bool = True
