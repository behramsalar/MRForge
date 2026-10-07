"""Rename results made before Stage 6.5 to the current names, without recomputing anything.

Two changes: the image with the noise components removed is now ``desc-denoised`` (was
``desc-cleaned``), and the standard-space image is named for the data it came from
(``desc-denoised`` after noise removal, else ``desc-preproc``). Because the steps ``regfilt``
and ``func_to_mni`` were bumped to version 2 for this, their records are updated too: the
content of the files is identical, only names and the recorded paths change, so the resume rule
still finds them valid. Safe to run twice.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from mrforge.models import File, Job
from mrforge.provenance import PROVENANCE_FILENAME, Provenance
from mrforge.workspace import Workspace

NAMES_VERSION = 2
CLEANED = "_desc-cleaned_bold.nii.gz"
DENOISED = "_desc-denoised_bold.nii.gz"
PREPROC = "_desc-preproc_bold.nii.gz"
BUMPED = ("regfilt", "func_to_mni")  # steps whose version changed from 1 to 2


@dataclass
class Migration:
    renames: dict[str, str] = field(default_factory=dict)  # old relpath -> new relpath
    records: list[Path] = field(default_factory=list)  # provenance files to bring to version 2
    backup: Path | None = None
    applied: bool = False


def _records(ws: Workspace) -> list[tuple[Path, Provenance]]:
    found: list[tuple[Path, Provenance]] = []
    for path in sorted(ws.derivatives_dir.rglob(PROVENANCE_FILENAME)):
        try:
            found.append((path, Provenance.model_validate_json(path.read_text())))
        except ValueError:
            continue
    return found


def plan_migration(ws: Workspace) -> Migration:
    """What would change. Nothing is touched."""
    plan = Migration()
    for path, prov in _records(ws):
        if prov.step.name not in BUMPED:
            continue
        if prov.step.version != "1":
            continue
        plan.records.append(path)
        from_denoised = any(
            "desc-cleaned" in f.path.rsplit("/", 1)[-1]
            or "desc-denoised" in f.path.rsplit("/", 1)[-1]
            for f in prov.inputs
        )
        for out in prov.outputs:
            old = out.path
            if prov.step.name == "regfilt" and old.endswith(CLEANED):
                plan.renames[old] = old.removesuffix(CLEANED) + DENOISED
            elif prov.step.name == "func_to_mni" and from_denoised and old.endswith(PREPROC):
                plan.renames[old] = old.removesuffix(PREPROC) + DENOISED
    # The record of func_to_mni also lists the renamed image as its input (the old name).
    return plan


def apply_migration(ws: Workspace, plan: Migration) -> Migration:
    """Rename the files, bring the records and the database along, and note the new naming
    version in workspace.json. A copy of the database is kept next to it first."""
    backup = ws.root / "db.sqlite.before-naming"
    if not backup.exists():
        shutil.copy2(ws.root / "db.sqlite", backup)
    plan.backup = backup
    for old, new in plan.renames.items():
        src, dst = ws.abspath(old), ws.abspath(new)
        if src.exists() and not dst.exists():
            src.rename(dst)
    # Records: every provenance file gets the new paths; the bumped steps get version 2.
    for path, _prov in _records(ws):
        text = path.read_text()
        for old, new in plan.renames.items():
            text = text.replace(old, new)
        data = json.loads(text)
        if path in plan.records:
            data["step"]["version"] = "2"
        path.write_text(json.dumps(data, indent=2) + "\n")
    with ws.session() as s:
        for row in s.scalars(select(File)):
            if row.relpath in plan.renames:
                row.relpath = plan.renames[row.relpath]
        for job in s.scalars(select(Job)):
            if job.step_name in BUMPED and job.step_version == "1":
                job.step_version = "2"
            if job.inputs:
                text = json.dumps(job.inputs)
                changed = text
                for old, new in plan.renames.items():
                    changed = changed.replace(old, new)
                if changed != text:
                    job.inputs = json.loads(changed)
    meta_path = ws.root / "workspace.json"
    meta = json.loads(meta_path.read_text())
    meta["names_version"] = NAMES_VERSION
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    plan.applied = True
    return plan


def migrate(ws: Workspace, dry_run: bool = False) -> Migration:
    plan = plan_migration(ws)
    return plan if dry_run else apply_migration(ws, plan)


def needs_migration(root: Path) -> bool:
    meta = json.loads((root / "workspace.json").read_text())
    return int(meta.get("names_version", 1)) < NAMES_VERSION
