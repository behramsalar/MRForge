"""What raw data a subject has (for the Data page): the images with their kind and size."""

from __future__ import annotations

from pydantic import BaseModel

from mrforge.bids import parse_bids_name
from mrforge.niftiutil import image_info
from mrforge.workspace import Workspace


class DataFile(BaseModel):
    relpath: str
    name: str
    datatype: str  # anat, func, fmap, dwi, ...
    suffix: str  # T1w, bold, magnitude1, ...
    recording: str  # e.g. "task-rest run-1" (empty for a T1)
    size_bytes: int
    shape: list[int] | None = None
    repetition_time_s: float | None = None  # for time series


class SubjectData(BaseModel):
    label: str
    files: list[DataFile]
    bytes_total: int


def subject_data(ws: Workspace, subject: str) -> SubjectData:
    """The NIfTI images under rawbids/<subject>, grouped by BIDS datatype order."""
    root = ws.root / "rawbids" / subject
    order = {"anat": 0, "func": 1, "fmap": 2, "dwi": 3}
    files: list[DataFile] = []
    for path in sorted(root.glob("**/*.nii.gz")) if root.is_dir() else []:
        entities, suffix, _ = parse_bids_name(path.name)
        shape: list[int] | None = None
        tr: float | None = None
        try:
            dims, zooms = image_info(path)
            shape = list(dims)
            tr = zooms[3] if len(dims) == 4 and len(zooms) > 3 else None
        except Exception:  # an unreadable image is still listed, without details
            pass
        recording = " ".join(
            f"{k}-{v}" for k, v in entities.items() if k not in ("sub", "ses", "acq")
        )
        acq = entities.get("acq")
        files.append(
            DataFile(
                relpath=ws.relpath(path),
                name=path.name,
                datatype=path.parent.name,
                suffix=suffix or "",
                recording=(recording + (f" acq-{acq}" if acq else "")).strip(),
                size_bytes=path.stat().st_size,
                shape=shape,
                repetition_time_s=tr,
            )
        )
    files.sort(key=lambda f: (order.get(f.datatype, 9), f.name))
    return SubjectData(label=subject, files=files, bytes_total=sum(f.size_bytes for f in files))
