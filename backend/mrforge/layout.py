"""Where a result goes inside a subject's datatype folder (Stage 10 follow-up).

The ``func`` folder of a processed subject held ~33 files per recording. Results people open
(``*_bold.nii.gz``, masks, reference images) stay in the folder itself; the rest is sorted by
kind into subfolders. One pure function decides, from the file name alone, so new steps get
the layout for free and the migration of old workspaces uses exactly the same rule.

Only ``func`` is sorted for now; ``anat`` and ``dwi`` keep their flat layout (decision pending).
"""

from __future__ import annotations

from mrforge.bids import parse_bids_name

LAYOUT_VERSION = 2  # workspace.json "layout_version"; 1 (or missing) = flat folders

SORTED_DATATYPES = ("func",)

QC = "qc"
ICA = "ica"
TRANSFORMS = "transforms"
FEAT = "feat"
CONNECTIVITY = "connectivity"

# suffixes (the last token of a BIDS-like name) that belong to the component analysis
_ICA_SUFFIXES = frozenset(
    {
        "components",
        "mixing",
        "spectra",
        "classification",
        "features",
        "labels",
        "decision",
        "cleaning",
    }
)


def subfolder_for(name: str, datatype: str) -> str:
    """The subfolder (relative to the datatype folder, '' for none) for a result named ``name``.

    ``name`` is a file or folder name; any leading directories are ignored. ``_slices`` folders
    follow the picture they belong to; native tool folders (``.feat``, ``.ica``) have their own.
    """
    if datatype not in SORTED_DATATYPES:
        return ""
    base = name.rstrip("/").rsplit("/", 1)[-1]
    if base.endswith(".feat"):
        return FEAT
    if base.endswith(".ica"):
        return ICA
    if base.endswith("_slices"):
        base = base[: -len("_slices")]
    entities, suffix, _ext = parse_bids_name(base)
    if not suffix or not entities:  # a bare word, such as a subfolder's own name
        return ""
    desc = entities.get("desc", "")
    if "seg" in entities:
        return f"{CONNECTIVITY}/{entities['seg']}"
    if suffix == "xfm":
        return TRANSFORMS
    if suffix == "qc" or (suffix == "timeseries" and desc == "motion"):
        return QC
    if suffix in _ICA_SUFFIXES or desc in ("melodic", "aroma", "icalabels"):
        return ICA
    return ""


def placed(name: str, datatype: str) -> str:
    """``name`` with its subfolder in front (``qc/sub-1_..._qc.png``), or ``name`` itself."""
    folder = subfolder_for(name, datatype)
    return f"{folder}/{name}" if folder else name
