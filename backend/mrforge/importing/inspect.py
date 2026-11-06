"""Look at what the user chose to import, without copying or reading any image.

The answer decides where the source goes: DICOM files (a folder, or one archive), several
archives in one folder (each is handled as its own DICOM source), loose NIfTI files (a folder
is a subject), or an existing BIDS dataset. A source that mixes kinds is explained, never
guessed at.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from mrforge.errors import StepError
from mrforge.importing.scan import TAR_ENDINGS, archive_kind, is_junk

# Files next to scans that are not images (never counted as DICOM).
NOT_IMAGES = {
    ".json", ".bval", ".bvec", ".txt", ".tsv", ".csv", ".md", ".png", ".jpg", ".jpeg",
    ".pdf", ".log", ".xml", ".html", ".htm", ".py", ".sh", ".yaml", ".yml",
}  # fmt: skip
SUBJECT_IN_NAME = re.compile(r"(?:^|_)sub-([A-Za-z0-9]+)")


class NiftiFolder(BaseModel):
    """The NIfTI files of one subject (one folder, or one ``sub-XX`` in their names)."""

    label: str  # the folder name, or the sub-XX label found in the file names
    files: list[str]  # paths relative to the chosen folder


class SourcePlan(BaseModel):
    kind: Literal["dicom", "archives", "nifti", "bids"]
    name: str
    summary: str  # plain language, shown before anything is read ("Found 12 ZIP archives")
    archives: list[str] = []  # kind "archives": paths relative to the chosen folder
    nifti: list[NiftiFolder] = []  # kind "nifti"


def _is_archive_name(name: str) -> bool:
    low = name.lower()
    return low.endswith(".zip") or low.endswith(TAR_ENDINGS)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _subject_label(rel: Path) -> str:
    found = SUBJECT_IN_NAME.search(rel.name)
    if found:
        return f"sub-{found.group(1)}"
    return rel.parent.name or "subject"


def inspect_source(src: Path) -> SourcePlan:
    src = src.expanduser().resolve()
    if src.is_file():
        if archive_kind(src) is None:
            raise StepError(
                code="IMPORT_SOURCE_INVALID",
                message=f"'{src.name}' is not a folder or an archive.",
                probable_cause="The path is wrong, or the file is not a ZIP or TAR archive.",
                suggested_action="Choose a folder with your scans, or a ZIP/TAR archive of it.",
            )
        return SourcePlan(kind="dicom", name=src.name, summary="One archive with scanner files.")
    if not src.is_dir():
        raise StepError(
            code="SOURCE_NOT_FOUND",
            message="That folder or file could not be found.",
            suggested_action="Pick the folder or archive again.",
        )
    if (src / "dataset_description.json").is_file():
        return SourcePlan(kind="bids", name=src.name, summary="An existing BIDS dataset.")

    archives: list[str] = []
    nifti: list[Path] = []
    others = 0  # anything else that is not clearly not-an-image: possibly DICOM
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src)
        if is_junk(str(rel)):
            continue
        low = path.name.lower()
        if low.endswith((".nii", ".nii.gz")):
            nifti.append(rel)
        elif _is_archive_name(low) and (not low.endswith(".zip") or zipfile.is_zipfile(path)):
            archives.append(str(rel))
        elif path.suffix.lower() not in NOT_IMAGES:
            others += 1

    found: list[str] = []
    if archives:
        found.append(_plural(len(archives), "archive", "archives"))
    if nifti:
        found.append(_plural(len(nifti), "NIfTI file", "NIfTI files"))
    if others:
        found.append(_plural(others, "other file (possibly DICOM)", "other files (possibly DICOM)"))

    if archives and not nifti and not others:
        return SourcePlan(
            kind="archives",
            name=src.name,
            summary=f"Found {_plural(len(archives), 'archive', 'archives')}. "
            "Each one is read as its own scan.",
            archives=archives,
        )
    if nifti and not archives and not others:
        groups: dict[str, list[str]] = {}
        for rel in nifti:
            groups.setdefault(_subject_label(rel), []).append(str(rel))
        return SourcePlan(
            kind="nifti",
            name=src.name,
            summary=f"Found {_plural(len(nifti), 'NIfTI file', 'NIfTI files')} for "
            f"{_plural(len(groups), 'subject', 'subjects')}.",
            nifti=[NiftiFolder(label=k, files=v) for k, v in groups.items()],
        )
    if others and not archives and not nifti:
        return SourcePlan(kind="dicom", name=src.name, summary="A folder with scanner files.")
    if not found:
        raise StepError(
            code="IMPORT_SOURCE_EMPTY",
            message="That folder holds no scans.",
            probable_cause="It is empty, or only holds files MRForge does not import.",
            suggested_action="Choose the folder with the scanner files, NIfTI files, archives "
            "(ZIP, TAR) or a BIDS dataset.",
        )
    raise StepError(
        code="IMPORT_SOURCE_MIXED",
        message=f"That folder mixes different kinds of data: {', '.join(found)}.",
        probable_cause="MRForge imports one kind at a time so nothing is put in the wrong place.",
        suggested_action="Choose a folder with only one kind: scanner files, archives, "
        "NIfTI files, or a BIDS dataset.",
    )
