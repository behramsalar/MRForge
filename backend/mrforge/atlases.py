"""The atlases bundled with the app (ROI time series and connectivity, Stage 10).

All volumes are on the FSL MNI152 2 mm grid. The loader never guesses: an unknown id or a
volume whose label values differ from its labels.csv is an error, not a silent fallback.
"""

import csv
import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any, cast

import numpy as np
from nibabel.loadsave import load as load_image
from nibabel.nifti1 import Nifti1Image
from pydantic import BaseModel

DATA = Path(__file__).resolve().parent / "data" / "atlases"
GRID_SHAPE = (91, 109, 91)  # FSL MNI152 2 mm
VOXEL_MM = 2.0


class AtlasInfo(BaseModel):
    id: str
    family: str
    name: str
    regions: int
    licence: str
    citation: str = ""
    caveat: str = ""  # text, empty when none


class AtlasFamily(BaseModel):
    id: str
    name: str
    kind: str


class AtlasCatalog(BaseModel):
    """What the dialog shows: the atlases, grouped by family."""

    families: list[AtlasFamily]
    atlases: list[AtlasInfo]


class Region(BaseModel):
    label: int  # value in the volume
    name: str  # the authors' name
    clean_name: str  # <hemisphere>_<region>, letters, digits and underscores only, unique
    hemisphere: str  # L, R or M
    network: str = ""  # Schaefer and combined atlases only


class AtlasError(Exception):
    """An atlas is missing or inconsistent. The message is plain language."""


@lru_cache(maxsize=1)
def _manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((DATA / "atlases.json").read_text()))


def catalog() -> AtlasCatalog:
    return AtlasCatalog(
        families=[AtlasFamily(**f) for f in _manifest()["families"]], atlases=list_atlases()
    )


def list_atlases() -> list[AtlasInfo]:
    caveats = _manifest()["caveats"]
    out = []
    for a in _manifest()["atlases"]:
        out.append(
            AtlasInfo(
                id=a["id"],
                family=a["family"],
                name=a["name"],
                regions=a["regions"],
                licence=a["licence"],
                citation=a.get("citation", ""),
                caveat=caveats.get(a.get("caveat", ""), ""),
            )
        )
    return out


def get_atlas(atlas_id: str) -> AtlasInfo:
    for a in list_atlases():
        if a.id == atlas_id:
            return a
    known = ", ".join(a.id for a in list_atlases())
    raise AtlasError(f"The atlas '{atlas_id}' is not one of the bundled atlases ({known}).")


def volume_path(atlas_id: str) -> Path:
    get_atlas(atlas_id)
    path = DATA / atlas_id / "volume.nii.gz"
    if not path.exists():
        raise AtlasError(
            f"The file of the atlas '{atlas_id}' is missing from the installation: {path}."
        )
    return path


@cache
def regions(atlas_id: str) -> tuple[Region, ...]:
    """The regions of an atlas, in ascending label order (fslmeants --label column order)."""
    get_atlas(atlas_id)
    path = DATA / atlas_id / "labels.csv"
    if not path.exists():
        raise AtlasError(f"The label list of the atlas '{atlas_id}' is missing: {path}.")
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    out = [
        Region(
            label=int(r["label"]),
            name=r["name"],
            clean_name=r["clean_name"],
            hemisphere=r["hemisphere"],
            network=r.get("network", ""),
        )
        for r in rows
    ]
    out.sort(key=lambda r: r.label)
    return tuple(out)


def volume_labels(atlas_id: str) -> np.ndarray[Any, Any]:
    """The distinct non-zero label values found in the volume, ascending."""
    img = cast(Nifti1Image, load_image(str(volume_path(atlas_id))))
    data = np.asarray(img.get_fdata())
    return np.unique(data[data > 0]).astype(int)
