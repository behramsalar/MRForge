"""BIDS naming for derivative files, and the derivatives dataset's own metadata files.

Names look like ``sub-001_ses-01_space-MNI152NLin6Asym_desc-nonlinear_T1w.nii.gz``:
``key-value`` entities in a fixed order, then a suffix, then the extension.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# BIDS entity order (from the BIDS specification's entity table; from/to/mode are the
# transform entities). Unknown entities are appended alphabetically.
ENTITY_ORDER = (
    "sub", "ses", "sample", "task", "acq", "ce", "trc", "rec", "dir", "run", "mod", "echo",
    "flip", "inv", "mt", "part", "proc", "hemi", "space", "split", "recording", "chunk",
    "atlas", "res", "den", "from", "to", "mode", "label", "desc",
)  # fmt: skip

# Entities describing what was done to an image; they are not inherited from an input name.
NOT_INHERITED = {
    "space", "split", "recording", "chunk", "atlas", "res", "den", "from", "to", "mode",
    "label", "desc",
}  # fmt: skip

EXTENSIONS = (".nii.gz", ".nii", ".json", ".tsv", ".mat", ".txt", ".h5")

BIDS_VERSION = "1.9.0"  # REVIEW(domain): BIDS specification version written to the dataset
# MRForge-only folders and QC files that are not part of BIDS
BIDSIGNORE = "_runs/\n*.anat/\n*.feat/\n*_qc.png\n*_qc.json\n"
TOOL_DISPLAY_NAMES = {"mrforge": "MRForge", "fsl": "FSL"}


def split_extension(filename: str) -> tuple[str, str]:
    for ext in EXTENSIONS:
        if filename.endswith(ext):
            return filename[: -len(ext)], ext
    stem, dot, tail = filename.rpartition(".")
    return (stem, dot + tail) if dot else (filename, "")


def parse_bids_name(filename: str) -> tuple[dict[str, str], str | None, str]:
    """Split ``sub-001_ses-01_T1w.nii.gz`` into ({'sub': '001', 'ses': '01'}, 'T1w', '.nii.gz').
    Names that are not BIDS-like give ({}, None, extension)."""
    stem, ext = split_extension(Path(filename).name)
    entities: dict[str, str] = {}
    suffix: str | None = None
    for token in stem.split("_"):
        match = re.fullmatch(r"([A-Za-z0-9]+)-([A-Za-z0-9]+)", token)
        if match:
            entities[match.group(1)] = match.group(2)
        elif re.fullmatch(r"[A-Za-z0-9]+", token):
            suffix = token
        else:
            return {}, None, ext
    return entities, suffix, ext


def bids_name(entities: dict[str, str], suffix: str, ext: str = ".nii.gz") -> str:
    known = [k for k in ENTITY_ORDER if k in entities]
    unknown = sorted(k for k in entities if k not in ENTITY_ORDER)
    # BIDS entity values are alphanumeric only; drop anything else (e.g. '_' in a step id).
    clean = {k: re.sub(r"[^A-Za-z0-9]", "", entities[k]) for k in entities}
    parts = [f"{k}-{clean[k]}" for k in known + unknown]
    return "_".join([*parts, suffix]) + ext


def label_of(value: str, prefix: str) -> str:
    """'sub-001' -> '001' (and '001' -> '001')."""
    return value[len(prefix) + 1 :] if value.startswith(prefix + "-") else value


def inherited_entities(
    subject: str, session: str | None, input_relpath: str | None
) -> dict[str, str]:
    """Entities for derived files: sub/ses from the workspace, plus acq/run/... carried over
    from a BIDS-named input (never desc/space/label, which describe processing)."""
    entities: dict[str, str] = {}
    if input_relpath:
        found, _, _ = parse_bids_name(input_relpath)
        entities.update({k: v for k, v in found.items() if k not in NOT_INHERITED})
    entities["sub"] = label_of(subject, "sub")
    if session:
        entities["ses"] = label_of(session, "ses")
    else:
        entities.pop("ses", None)
    return entities


# -- the derivatives dataset's own files -----------------------------------------------


def init_derivatives(derivatives_dir: Path, mrforge_version: str) -> None:
    """Create dataset_description.json and .bidsignore (idempotent)."""
    derivatives_dir.mkdir(parents=True, exist_ok=True)
    description = derivatives_dir / "dataset_description.json"
    if not description.exists():
        description.write_text(
            json.dumps(
                {
                    "Name": "MRForge derivatives",
                    "BIDSVersion": BIDS_VERSION,
                    "DatasetType": "derivative",
                    "GeneratedBy": [{"Name": "MRForge", "Version": mrforge_version}],
                },
                indent=2,
            )
            + "\n"
        )
    ignore = derivatives_dir / ".bidsignore"
    if not ignore.exists():
        ignore.write_text(BIDSIGNORE)


def record_tool_versions(derivatives_dir: Path, tool_versions: dict[str, str]) -> None:
    """Add tools used (for example FSL) to ``GeneratedBy`` in dataset_description.json."""
    path = derivatives_dir / "dataset_description.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    generated = data.setdefault("GeneratedBy", [])
    known = {(g.get("Name"), g.get("Version")) for g in generated}
    changed = False
    for key, version in tool_versions.items():
        name = TOOL_DISPLAY_NAMES.get(key, key)
        if (name, version) not in known and not (name == "MRForge"):
            generated.append({"Name": name, "Version": version})
            changed = True
    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n")
