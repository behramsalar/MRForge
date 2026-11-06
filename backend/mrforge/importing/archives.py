"""Several archives in one folder: each is scanned as its own source, and the scans are shown
together as one group (so "Import all that are ready" works on all of them)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from mrforge.errors import StepError
from mrforge.importing.manifest import save_manifest
from mrforge.importing.models import ImportGroup, ImportManifest
from mrforge.importing.scan import _find_group, describe_source, scan_group
from mrforge.workspace import Workspace


def scan_archives(
    ws: Workspace,
    folder: Path,
    members: list[str],
    progress: Callable[[str], None] | None = None,
) -> tuple[list[ImportManifest], list[tuple[str, str]], bool]:
    """Scan every archive of ``folder`` (``members`` are paths relative to it).

    Returns (manifests, failures, is_new). An archive that cannot be read is listed in
    ``failures`` as (name, plain-language message) and does not stop the others. Scanning the
    same folder again returns the same imports."""
    say = progress or (lambda _msg: None)
    folder = folder.expanduser().resolve()
    info = describe_source(folder)
    known = _find_group(ws, info.fingerprint)
    if known:
        return known, [], False
    manifests: list[ImportManifest] = []
    failures: list[tuple[str, str]] = []
    new_any = False
    for n, rel in enumerate(sorted(members), start=1):
        say(f"Archive {n} of {len(members)}: {rel}")
        try:
            found, is_new = scan_group(ws, folder / rel, progress=say)
        except StepError as problem:
            say(f"{rel}: {problem.message}")
            failures.append((rel, problem.message))
            continue
        new_any = new_any or is_new
        manifests.extend(found)
    if not manifests:
        first = failures[0][1] if failures else "No scans were found."
        raise StepError(
            code="IMPORT_NO_ARCHIVE_READABLE",
            message=f"None of the {len(members)} archives could be read. First problem: {first}",
            probable_cause="The archives hold no readable scanner files, or are damaged.",
            suggested_action="Check that they are archives of DICOM folders, then try again.",
        )
    for i, manifest in enumerate(manifests, start=1):
        study = manifest.group.study if manifest.group else manifest.source.fingerprint[:12]
        manifest.group = ImportGroup(
            source=info.fingerprint,
            index=i,
            of=len(manifests),
            study=hashlib.sha256(study.encode()).hexdigest()[:12],
        )
        save_manifest(ws, manifest)
    return manifests, failures, new_any
