"""Removing the copy of the original DICOM files from ``sourcedata/dicom/``.

The copy is kept by default (the safe choice). A user who stores the originals elsewhere can
remove it to save space. Removal is allowed only when everything that was set to be imported
is already safe in ``rawbids/``; the manifest (series table, decisions, provenance) is kept.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from mrforge.errors import StepError
from mrforge.hashing import file_sha256
from mrforge.importing.classify import RuleSet, effective_all
from mrforge.importing.manifest import save_manifest
from mrforge.importing.models import ImportManifest
from mrforge.workspace import Workspace


@dataclass
class RemovalPlan:
    path: str  # workspace-relative folder that would be removed
    size_bytes: int
    not_safe: list[str] = field(default_factory=list)  # series not yet safe in rawbids/
    only_in_dicom: list[str] = field(default_factory=list)  # skipped or undecided series


def folder_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _describe(number: int | None, label: str) -> str:
    return f"series {number} ({label})"


def removal_plan(ws: Workspace, manifest: ImportManifest, rules: RuleSet) -> RemovalPlan:
    if manifest.source.kind not in ("folder", "zip"):
        raise StepError(
            code="DICOM_NOT_APPLICABLE",
            message=f"{manifest.id} was not imported from DICOM files, so there is no DICOM "
            "copy to remove.",
            suggested_action="Only DICOM imports (from a folder or a zip) have one.",
        )
    folder = ws.root / manifest.dicom_dir
    if manifest.dicom_removed is not None or not folder.is_dir():
        raise StepError(
            code="DICOM_ALREADY_REMOVED",
            message=f"The DICOM copy of {manifest.id} was already removed.",
            suggested_action="Nothing to do.",
        )
    plan = RemovalPlan(path=manifest.dicom_dir, size_bytes=folder_size(folder))
    classes = effective_all(manifest, rules)
    for s in manifest.series:
        action = classes[s.uid].action
        label = _describe(s.number, s.label)
        if action != "import":
            plan.only_in_dicom.append(label)
            continue
        conversion = manifest.conversions.get(s.uid)
        organized = manifest.organized.get(s.uid)
        if conversion is None or conversion.status != "ok" or organized is None:
            plan.not_safe.append(label)
            continue
        for rel, digest in organized.files.items():
            if not ws.abspath(rel).is_file() or file_sha256(ws, rel) != digest:
                plan.not_safe.append(label)
                break
    # a fieldmap pair or other series organized under a combined record counts too
    return plan


def remove_dicom(ws: Workspace, manifest: ImportManifest, rules: RuleSet) -> RemovalPlan:
    """Delete the DICOM copy of one import. Refuses unless every series set to be imported is
    complete in rawbids/ (files present with their recorded hashes)."""
    plan = removal_plan(ws, manifest, rules)
    if plan.not_safe:
        raise StepError(
            code="DICOM_REMOVE_NOT_SAFE",
            message="The DICOM files were not removed: some series that are set to be imported "
            "are not safely in rawbids/ yet (" + ", ".join(plan.not_safe) + ").",
            probable_cause="Removing the DICOM files now would lose data that is not stored "
            "anywhere else in this workspace.",
            suggested_action="Run 'mrforge import run' first, then try again.",
        )
    shutil.rmtree(ws.root / manifest.dicom_dir)
    manifest.dicom_removed = datetime.now(UTC)
    save_manifest(ws, manifest)
    return plan
