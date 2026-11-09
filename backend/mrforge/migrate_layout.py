"""Sort the files of workspaces made before the subfolder layout (see ``layout.py``).

Every result in a ``func`` folder that ``subfolder_for`` assigns to a subfolder is moved there;
nothing is recomputed and no file is changed. Because the content stays the same, the step
versions stay the same and the resume rule still finds every run valid once the recorded paths
(provenance records, result JSON files, the database) are brought along. Safe to run twice;
nothing is overwritten.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from mrforge.errors import StepError
from mrforge.layout import LAYOUT_VERSION, SORTED_DATATYPES, subfolder_for
from mrforge.models import File, Job, PipelineRun
from mrforge.provenance import PROVENANCE_FILENAME
from mrforge.workspace import Workspace

NATIVE_SUFFIXES = (".feat", ".ica", ".anat")
MARKER = "layout-migration.json"  # the plan, kept so an interrupted run can be finished


@dataclass
class LayoutMigration:
    renames: dict[str, str] = field(default_factory=dict)  # old relpath -> new relpath
    local: dict[Path, dict[str, str]] = field(default_factory=dict)  # folder -> {name: new rel}
    backup: Path | None = None
    applied: bool = False


def _datatype_folders(ws: Workspace) -> list[Path]:
    found: list[Path] = []
    for datatype in SORTED_DATATYPES:
        for path in sorted(ws.derivatives_dir.glob(f"sub-*/**/{datatype}")):
            parts = path.relative_to(ws.derivatives_dir).parts
            if (
                path.is_dir()
                and "_runs" not in parts
                and not any(p.endswith(NATIVE_SUFFIXES) for p in parts)
            ):
                found.append(path)
    return found


def plan_migration(ws: Workspace) -> LayoutMigration:
    """What would move. Nothing is touched."""
    plan = LayoutMigration()
    for folder in _datatype_folders(ws):
        local: dict[str, str] = {}
        for entry in sorted(folder.iterdir()):
            if entry.name.startswith((".", "_")):
                continue
            target = subfolder_for(entry.name, folder.name)
            if not target:
                continue
            new = f"{target}/{entry.name}"
            if (folder / new).exists():
                continue  # already there (a half-finished earlier run): never overwrite
            local[entry.name] = new
            plan.renames[ws.relpath(entry)] = ws.relpath(folder / new)
        if local:
            plan.local[folder] = local
    marker = ws.root / MARKER
    if marker.is_file():  # an earlier run was interrupted after moving some files
        saved = json.loads(marker.read_text())
        for old, new in saved["renames"].items():
            plan.renames.setdefault(old, new)
        for folder_name, names in saved["local"].items():
            plan.local.setdefault(ws.root / folder_name, {}).update(names)
    return plan


def _rewrite(text: str, renames: dict[str, str]) -> str:
    for old in sorted(renames, key=len, reverse=True):
        text = text.replace(old, renames[old])
    return text


def _local_pattern(names: dict[str, str]) -> re.Pattern[str]:
    """A quoted value that starts with one of the moved names (paths relative to the folder,
    such as the slice pictures a QC item lists)."""
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(r'"(' + alternatives + r")")


def _local_replacer(names: dict[str, str]) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        return '"' + names[match.group(1)]

    return replace


def _json_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*.json"):
        parts = path.relative_to(root).parts
        if any(p.endswith(NATIVE_SUFFIXES) for p in parts):
            continue  # the tools' own folders are not ours to edit
        files.append(path)
    return files


def apply_migration(ws: Workspace, plan: LayoutMigration) -> LayoutMigration:
    backup = ws.root / "db.sqlite.before-layout"
    if not backup.exists():
        shutil.copy2(ws.root / "db.sqlite", backup)
    plan.backup = backup
    (ws.root / MARKER).write_text(
        json.dumps(
            {
                "renames": plan.renames,
                "local": {str(f.relative_to(ws.root)): n for f, n in plan.local.items()},
            },
            indent=2,
        )
        + "\n"
    )
    for old, new in plan.renames.items():
        src, dst = ws.abspath(old), ws.abspath(new)
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
    # Records and result files: workspace-relative paths everywhere, and the names relative to
    # the folder in the records of that folder (the slices a QC item lists).
    # Result files first: their content changes, so their recorded hashes must follow.
    hashes: dict[str, str] = {}  # old sha256 -> new sha256
    files = _json_files(ws.derivatives_dir)
    for path in sorted(files, key=lambda p: PROVENANCE_FILENAME == p.name):
        text = path.read_text()
        changed = _rewrite(text, plan.renames)
        for folder, names in plan.local.items():
            if folder in path.parents:
                changed = _local_pattern(names).sub(_local_replacer(names), changed)
        if path.name == PROVENANCE_FILENAME:
            for old_hash, new_hash in hashes.items():
                changed = changed.replace(f'"{old_hash}"', f'"{new_hash}"')
        if changed != text:
            before = hashlib.sha256(text.encode()).hexdigest()
            path.write_text(changed)
            if path.name != PROVENANCE_FILENAME:
                hashes[before] = hashlib.sha256(changed.encode()).hexdigest()
    with ws.session() as s:
        for row in s.scalars(select(File)):
            for old, new in plan.renames.items():
                if row.relpath == old or row.relpath.startswith(old + "/"):
                    row.relpath = new + row.relpath[len(old) :]
                    row.sha256 = row.size = row.mtime_ns = None  # cache: recomputed when needed
                    break
        for job in s.scalars(select(Job)):
            if job.inputs:
                text = json.dumps(job.inputs)
                changed = _rewrite(text, plan.renames)
                if changed != text:
                    job.inputs = json.loads(changed)
        for run in s.scalars(select(PipelineRun)):
            text = json.dumps(run.spec)
            changed = _rewrite(text, plan.renames)
            if changed != text:
                run.spec = json.loads(changed)
    meta_path = ws.root / "workspace.json"
    meta = json.loads(meta_path.read_text())
    meta["layout_version"] = LAYOUT_VERSION
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    (ws.root / MARKER).unlink(missing_ok=True)  # finished: nothing left to resume
    plan.applied = True
    return plan


def migrate(ws: Workspace, dry_run: bool = False) -> LayoutMigration:
    plan = plan_migration(ws)
    return plan if dry_run else apply_migration(ws, plan)


def require_current_layout(ws: Workspace) -> None:
    """Refuse to start work in a workspace whose results are still in the flat layout: the
    steps would look for them in the subfolders, find nothing and run everything again."""
    if not needs_migration(ws.root):
        return
    if not plan_migration(ws).renames:
        meta_path = ws.root / "workspace.json"  # nothing to move: just note the version
        meta = json.loads(meta_path.read_text())
        meta["layout_version"] = LAYOUT_VERSION
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        return
    raise StepError(
        code="WORKSPACE_LAYOUT_OLD",
        message="This workspace keeps its results in the older, flat folder layout.",
        probable_cause="It was made before the results were sorted into subfolders (qc, ica, ...).",
        suggested_action=(
            f"Run 'mrforge workspace migrate {ws.root}' once. Nothing is recomputed; "
            "the files are only moved into subfolders."
        ),
    )


def needs_migration(root: Path) -> bool:
    meta = json.loads((root / "workspace.json").read_text())
    return int(meta.get("layout_version", 1)) < LAYOUT_VERSION
