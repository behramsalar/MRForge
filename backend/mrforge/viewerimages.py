"""The images of a subject the viewer can show, with plain-language names and groups.

Raw images come from ``rawbids/``; results from the datatype folders of the derivatives
dataset (the native ``.anat`` / ``.feat`` folders are not listed: their key files appear with
BIDS names next to them).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrforge.bids import parse_bids_name
from mrforge.niftiutil import image_info
from mrforge.workspace import Workspace

RAW, ANAT, FUNC, FMAP = "Raw data", "Anatomical results", "Functional results", "Fieldmap results"
GROUP_ORDER = {RAW: 0, ANAT: 1, FUNC: 2, FMAP: 3}
STANDARD = "MNI152NLin6Asym"
PROBABILITY = {
    "GM": ("Grey matter probability", "green"),
    "WM": ("White matter probability", "blue"),
    "CSF": ("CSF probability", "cool"),
}
SKIP_ENTITIES = {"sub", "ses", "space", "desc", "label", "from", "to", "mode"}


@dataclass(frozen=True)
class Described:
    group: str
    name: str
    role: str  # "underlay" or "overlay": what the image is usually shown as
    colormap: str | None = None
    rank: int = 50  # order inside the group


def _recording(entities: dict[str, str]) -> str:
    text = " ".join(f"{k}-{v}" for k, v in entities.items() if k not in SKIP_ENTITIES)
    return f" ({text})" if text else ""


def describe(path: Path, raw: bool) -> Described | None:
    """What to call this image and where to list it; ``None`` for files that are not images
    to look at (transforms)."""
    e, suffix, _ = parse_bids_name(path.name)
    suffix = suffix or ""
    desc, space, label = e.get("desc"), e.get("space"), e.get("label")
    rec = _recording(e)
    if suffix == "xfm":
        return None
    if raw:
        names = {
            "T1w": ("T1 (original)", 0),
            "T2w": ("T2 (original)", 1),
            "FLAIR": ("FLAIR (original)", 2),
            "bold": (f"Functional{rec}", 10),
            "dwi": (f"Diffusion{rec}", 20),
            "magnitude1": (f"Fieldmap magnitude 1{rec}", 30),
            "magnitude2": (f"Fieldmap magnitude 2{rec}", 31),
            "phasediff": (f"Fieldmap phase difference{rec}", 32),
        }
        name, rank = names.get(suffix, (path.name.removesuffix(".nii.gz"), 90))
        return Described(RAW, name, "underlay", None, rank)

    # -- results ----------------------------------------------------------------------
    anat = ANAT if _is_anat(path) else FUNC

    def result(
        group: str, name: str, role: str = "underlay", cmap: str | None = None, rank: int = 50
    ) -> Described:
        return Described(group, name, role, cmap, rank)

    if suffix in ("T1w", "T2w") and space == STANDARD:
        return result(ANAT, f"{suffix[:2]} in standard space ({desc or 'resampled'})", rank=30)
    if suffix == "T1w":
        t1_names = {
            "biascorr": ("T1, bias-corrected", 0),
            "brain": ("T1, brain only", 1),
            "bet": ("T1, brain only (bet)", 2),
            "1mm": ("T1, resampled to 1 mm", 3),
        }
        if desc in t1_names:
            return result(ANAT, t1_names[desc][0], rank=t1_names[desc][1])
    if suffix == "mask" and not space:
        name = "Brain mask (bet)" if desc == "bet" else "Brain mask"
        return result(anat, name + (rec if anat == FUNC else ""), "overlay", "red", 10)
    if suffix == "dseg":
        name = (
            "Deep brain structures"
            if desc == "subcortical"
            else "Tissue segmentation (CSF, GM, WM)"
        )
        return result(ANAT, name, "overlay", "winter", 11)
    if suffix == "probseg" and label in PROBABILITY:
        name, cmap = PROBABILITY[label]
        return result(ANAT, name, "overlay", cmap, 12)
    if suffix == "bold":
        if space == STANDARD:
            return result(FUNC, f"Functional in standard space{rec}", rank=40)
        return result(FUNC, f"Functional, preprocessed{rec}", rank=10)
    if suffix == "boldref":
        if space == "T1w":
            tail = ", aligned to the T1"
            if desc == "distorted":
                tail = ", before distortion correction"
            return result(FUNC, f"Functional example volume{rec}{tail}", "overlay", "gray", 20)
        return result(FUNC, f"Functional example volume{rec}", rank=21)
    if suffix == "mask" and space == STANDARD:
        return result(FUNC, f"Brain mask in standard space{rec}", "overlay", "red", 41)
    if suffix == "fieldmap":
        return result(FMAP, "Fieldmap, prepared (rad/s)", "overlay", "hot", 0)
    if suffix == "magnitude1" and desc == "brain":
        return result(FMAP, "Fieldmap magnitude, brain only", rank=1)
    return result(anat, path.name.removesuffix(".nii.gz"), rank=99)


def _is_anat(path: Path) -> bool:
    return path.parent.name == "anat"


@dataclass(frozen=True)
class FoundImage:
    path: Path
    described: Described
    volumes: int | None
    size_bytes: int


def find_images(ws: Workspace, subject: str) -> list[FoundImage]:
    """Every viewable image of ``subject``, raw first, then results by group."""
    candidates: list[tuple[Path, bool]] = [
        (p, True) for p in sorted((ws.root / "rawbids" / subject).glob("**/*.nii.gz"))
    ]
    base = ws.derivatives_dir / subject
    for datatype in ("anat", "func", "fmap"):
        candidates += [(p, False) for p in sorted(base.glob(f"**/{datatype}/*.nii.gz"))]
    found: list[FoundImage] = []
    for path, raw in candidates:
        described = describe(path, raw)
        if described is None:
            continue
        volumes: int | None = None
        try:
            shape = image_info(path)[0]
            volumes = shape[3] if len(shape) == 4 else None
        except Exception:  # still listed; the viewer reports it if it cannot open it
            pass
        found.append(FoundImage(path, described, volumes, path.stat().st_size))
    found.sort(key=lambda f: (GROUP_ORDER[f.described.group], f.described.rank, f.path.name))
    return found
