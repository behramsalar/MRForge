"""The import manifest: scan results, user decisions and conversion provenance.

Kept in ``<workspace>/imports/import-NNN/manifest.json`` (not inside rawbids/, which must stay
immutable once written, while the manifest changes when the user corrects a series).
"""

from __future__ import annotations

import re
from pathlib import Path

from mrforge.errors import StepError
from mrforge.importing.models import ImportManifest
from mrforge.workspace import Workspace

MANIFEST_NAME = "manifest.json"


def imports_dir(ws: Workspace) -> Path:
    return ws.root / "imports"


def manifest_dir(ws: Workspace, manifest_id: str) -> Path:
    return imports_dir(ws) / manifest_id


def list_manifests(ws: Workspace) -> list[ImportManifest]:
    found: list[ImportManifest] = []
    for path in sorted(imports_dir(ws).glob(f"import-*/{MANIFEST_NAME}")):
        try:
            found.append(ImportManifest.model_validate_json(path.read_text()))
        except ValueError:
            continue  # an unreadable manifest is ignored rather than breaking every import
    return found


def next_manifest_id(ws: Workspace) -> str:
    numbers = [
        int(m.group(1))
        for p in imports_dir(ws).glob("import-*")
        if (m := re.fullmatch(r"import-(\d+)", p.name))
    ]
    return f"import-{max(numbers, default=0) + 1:03d}"


def save_manifest(ws: Workspace, manifest: ImportManifest) -> Path:
    directory = manifest_dir(ws, manifest.id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / MANIFEST_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(manifest.model_dump_json(indent=2) + "\n")
    tmp.replace(path)  # atomic: never leaves a half-written manifest
    return path


def load_manifest(ws: Workspace, manifest_id: str | None = None) -> ImportManifest:
    """The named manifest, or the most recent one."""
    manifests = list_manifests(ws)
    if manifest_id is not None:
        for m in manifests:
            if m.id == manifest_id:
                return m
        raise StepError(
            code="UNKNOWN_IMPORT",
            message=f"There is no import called '{manifest_id}'.",
            suggested_action="Run 'mrforge import show' to see the imports in this workspace.",
        )
    if not manifests:
        raise StepError(
            code="NO_IMPORT",
            message="Nothing has been imported into this workspace yet.",
            suggested_action="Start with 'mrforge import scan <folder or zip>'.",
        )
    return manifests[-1]
