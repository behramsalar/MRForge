"""Undoing a whole import.

Raw data is not changed once it is written (docs/DECISIONS.md), with one exception the user
asked for: an import can be undone as a whole, on purpose, so its decisions can be changed and
it can be imported again. Undoing removes only the files that import wrote into ``rawbids/``
(checked against what was recorded); the converted copies, the scanner files in
``sourcedata/`` and everything processed from the data stay. Processing results are not
deleted: steps that used the removed files are simply no longer up to date.
"""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from mrforge.errors import StepError
from mrforge.hashing import file_sha256
from mrforge.importing.manifest import manifest_dir, save_manifest
from mrforge.importing.models import ImportManifest
from mrforge.models import File, Job, JobStatus, Subject
from mrforge.runner.jobs import list_jobs, recover_stale_jobs
from mrforge.workspace import Workspace


@dataclass
class UndoPlan:
    subject: str
    files: list[str] = field(default_factory=list)  # workspace-relative, existing, to remove
    bytes: int = 0
    series: int = 0
    only_copy: int = 0  # images with no other copy inside the workspace
    stale_steps: list[str] = field(default_factory=list)  # processed results that use them
    problems: list[str] = field(default_factory=list)  # files that changed since the import


def _target_files(manifest: ImportManifest) -> dict[str, str]:
    return {path: sha for done in manifest.organized.values() for path, sha in done.files.items()}


def undo_plan(ws: Workspace, manifest: ImportManifest) -> UndoPlan:
    """What undoing this import would remove and what it would leave out of date."""
    plan = UndoPlan(subject=manifest.subject, series=len(manifest.organized))
    targets = _target_files(manifest)
    for rel, recorded in sorted(targets.items()):
        path = ws.abspath(rel)
        if not path.is_file():
            continue  # already gone
        # Small text files (sidecars) may legitimately gain IntendedFor entries later.
        if (
            not rel.endswith(".json")
            and not rel.endswith(".tsv")
            and file_sha256(ws, rel) != recorded
        ):
            plan.problems.append(rel.removeprefix("rawbids/"))
            continue
        plan.files.append(rel)
        plan.bytes += path.stat().st_size
        if rel.endswith(".nii.gz") and path.stat().st_nlink == 1:
            plan.only_copy += 1
    used = set(plan.files)
    stale: list[str] = []
    for job in list_jobs(ws):
        values = [v for v in job.inputs.values() if isinstance(v, str)]
        if any(v in used for v in values) and job.step_name not in stale:
            stale.append(job.step_name)
    plan.stale_steps = stale
    return plan


def _running_jobs(ws: Workspace) -> bool:
    recover_stale_jobs(ws)  # a Running job whose process is gone is not running
    return any(j.status == JobStatus.RUNNING.value for j in list_jobs(ws))


def _remove_empty_dirs(root: Path, stop: Path) -> None:
    current = root
    while current != stop and current.is_dir() and not any(current.iterdir()):
        current.rmdir()
        current = current.parent


def _writable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


def _drop_dangling_intended_for(ws: Workspace) -> int:
    """Remove IntendedFor entries that point at runs that no longer exist (the one change to
    existing sidecars that imports are allowed to make)."""
    changed = 0
    for sidecar in sorted((ws.root / "rawbids").glob("**/fmap/*.json")):
        try:
            data = json.loads(sidecar.read_text())
        except (OSError, ValueError):
            continue
        listed = data.get("IntendedFor")
        if not listed:
            continue
        subject_dir = next(
            p for p in [sidecar.parent.parent, *sidecar.parents] if p.name.startswith("sub-")
        )
        kept = [
            t
            for t in (listed if isinstance(listed, list) else [listed])
            if (subject_dir / t).exists()
        ]
        if kept != listed:
            data["IntendedFor"] = kept
            if not kept:
                del data["IntendedFor"]
            _writable(sidecar)
            sidecar.write_text(json.dumps(data, indent=2) + "\n")
            sidecar.chmod(sidecar.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
            changed += 1
    return changed


def undo_import(ws: Workspace, manifest: ImportManifest, who: str | None = None) -> UndoPlan:
    """Remove what the import wrote into rawbids/ and make it importable again."""
    if not manifest.organized:
        raise StepError(
            code="NOTHING_TO_UNDO",
            message="This import has not written anything into the data folder.",
            probable_cause="It was never imported, or it was already undone.",
            suggested_action="Nothing to do: you can change the decisions and import it.",
        )
    if _running_jobs(ws):
        raise StepError(
            code="JOBS_RUNNING",
            message="A processing step is running, so data cannot be removed now.",
            probable_cause="Removing images while a step uses them would break that step.",
            suggested_action="Wait for it to finish (or cancel it), then try again.",
        )
    plan = undo_plan(ws, manifest)
    if plan.problems:
        shown = ", ".join(plan.problems[:3]) + (" ..." if len(plan.problems) > 3 else "")
        raise StepError(
            code="UNDO_FILES_CHANGED",
            message=f"Some imported files were changed after the import ({shown}); nothing "
            "was removed.",
            probable_cause="MRForge never edits raw files; they were changed outside it.",
            suggested_action="Restore the original files, or ask whoever looks after "
            "MRForge for help.",
        )
    rawbids = ws.root / "rawbids"
    for rel in plan.files:
        ws.abspath(rel).unlink(missing_ok=True)
    for rel in plan.files:
        _remove_empty_dirs(ws.abspath(rel).parent, rawbids)
    with ws.session() as s:
        s.execute(delete(File).where(File.relpath.in_(plan.files)))
    # the subject leaves participants.tsv (and the database) when nothing of it remains
    subject_dir = rawbids / manifest.subject
    if not subject_dir.exists():
        participants = rawbids / "participants.tsv"
        if participants.is_file():
            rows = [
                ln
                for ln in participants.read_text().splitlines()
                if ln.split("\t")[0] != manifest.subject
            ]
            _writable(participants)
            participants.write_text("\n".join(rows) + "\n")
        with ws.session() as s:
            subject = s.scalar(select(Subject).where(Subject.label == manifest.subject))
            has_jobs = subject is not None and s.scalar(
                select(Job.id).where(Job.subject_id == subject.id)
            )
            if subject is not None and not has_jobs:
                s.delete(subject)
    _drop_dangling_intended_for(ws)
    manifest.organized = {}
    manifest.organize_notes = []
    manifest.undone = datetime.now(UTC)
    save_manifest(ws, manifest)
    log = {
        "undone": manifest.undone.isoformat(),
        "by": who,
        "removed": [f.removeprefix("rawbids/") for f in plan.files],
        "kept": "converted copies and scanner files",
    }
    (manifest_dir(ws, manifest.id) / "undo-log.json").write_text(json.dumps(log, indent=2) + "\n")
    return plan
