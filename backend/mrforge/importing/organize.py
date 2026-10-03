"""Write converted series into ``rawbids/`` as a BIDS dataset.

Rules this module keeps (CLAUDE.md principle 3, "raw data is immutable"):
  * Nothing in rawbids/ is ever overwritten or renamed. If a planned file already exists with
    different content, or a series would need a different name than before, the whole
    organize step stops before writing anything and says why.
  * Running it again with nothing new changes nothing.
  * Files are made read-only after they are written.

Names follow BIDS: ``sub-001[_ses-01]_task-rest_bold``, ``..._T1w``, ``..._dwi``, and for
fieldmaps ``..._magnitude1``, ``..._magnitude2``, ``..._phasediff``. A run number is added only
when the same kind appears more than once, in series-number order.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from mrforge import __version__
from mrforge.bids import BIDS_VERSION, bids_name, label_of
from mrforge.errors import StepError
from mrforge.hashing import file_sha256
from mrforge.importing.classify import RuleSet, effective_all
from mrforge.importing.manifest import save_manifest
from mrforge.importing.models import (
    ConvertedImage,
    DicomSeries,
    ImportManifest,
    OrganizedSeries,
)
from mrforge.models import File
from mrforge.workspace import Workspace

PRIVACY_FILE = Path(__file__).with_name("sidecar_privacy.yaml")
WORKSPACE_PRIVACY = "imports/sidecar_privacy.yaml"
README_TEXT = (
    "This BIDS dataset was created by MRForge from DICOM files. The original DICOM files are\n"
    "kept unchanged in sourcedata/. Files in this folder are never modified after they are\n"
    "written; processed results are written to derivatives/.\n"
)


@dataclass
class PlannedFile:
    uid: str
    target: str  # workspace-relative path in rawbids/
    kind: str  # for the database: T1w, bold, magnitude1, ...
    source: str | None = None  # workspace-relative converted file to link or copy
    data: dict[str, Any] | None = None  # content of a generated JSON file
    text: str | None = None  # the rendered JSON (set when the plan is finished)
    sha256: str = ""


@dataclass
class Plan:
    files: list[PlannedFile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    uses: dict[str, list[str]] = field(default_factory=dict)  # fieldmap label -> runs using it


@dataclass
class OrganizeSummary:
    written: list[str] = field(default_factory=list)
    in_place: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)  # fieldmap sidecars whose IntendedFor grew
    notes: list[str] = field(default_factory=list)


def load_privacy_keys(ws: Workspace | None = None) -> set[str]:
    path = PRIVACY_FILE
    if ws is not None and (ws.root / WORKSPACE_PRIVACY).is_file():
        path = ws.root / WORKSPACE_PRIVACY
    try:
        data = yaml.safe_load(path.read_text())
        keys = data["remove"]
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise ValueError("'remove' must be a list of field names")
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
        raise StepError(
            code="PRIVACY_LIST_INVALID",
            message=f"The sidecar privacy list could not be used: {path.name}",
            probable_cause=f"{exc}",
            suggested_action="Correct the file (it needs a 'remove:' list of field names), or "
            "remove it to use the built-in list.",
        ) from exc
    return set(keys)


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _alnum(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text)


# -- planning (no writes) ---------------------------------------------------------------


def _convert_error(missing: list[DicomSeries], failed: list[DicomSeries]) -> StepError:
    parts = []
    if missing:
        parts.append("not converted yet: " + ", ".join(str(s.number) for s in missing))
    if failed:
        parts.append("conversion failed: " + ", ".join(str(s.number) for s in failed))
    return StepError(
        code="ORGANIZE_NEEDS_CONVERSION",
        message="Not every series that is set to be imported has been converted ("
        + "; ".join(parts)
        + ").",
        probable_cause="rawbids/ is only written from complete, checked conversions.",
        suggested_action="Run 'mrforge import convert' and fix any failed series first.",
    )


def _sidecar(ws: Workspace, image: ConvertedImage, remove: set[str]) -> dict[str, Any]:
    data = json.loads(ws.abspath(image.sidecar or "").read_text())
    return {k: v for k, v in data.items() if k not in remove}


def _json_text(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def build_plan(ws: Workspace, manifest: ImportManifest, rules: RuleSet) -> Plan:
    classes = effective_all(manifest, rules)
    chosen = [s for s in manifest.series if classes[s.uid].action == "import"]
    missing = [s for s in chosen if s.uid not in manifest.conversions]
    failed = [
        s
        for s in chosen
        if s.uid in manifest.conversions and manifest.conversions[s.uid].status != "ok"
    ]
    if missing or failed:
        raise _convert_error(missing, failed)
    remove = load_privacy_keys(ws)
    plan = Plan()
    sub = label_of(manifest.subject, "sub")
    ses = label_of(manifest.session, "ses") if manifest.session else None
    folder = f"{manifest.subject}/{manifest.session}" if manifest.session else manifest.subject
    base_entities: dict[str, str] = {"sub": sub, **({"ses": ses} if ses else {})}

    def relpath(datatype: str, name: str) -> str:
        return f"rawbids/{folder}/{datatype}/{name}"

    def inside_subject(datatype: str, name: str) -> str:
        """Path as BIDS writes it in IntendedFor: relative to the subject folder."""
        return f"{manifest.session + '/' if manifest.session else ''}{datatype}/{name}"

    # -- run numbers: only when the same kind occurs more than once ---------------------
    groups: dict[tuple[str, ...], list[DicomSeries]] = {}
    for s in chosen:
        c = classes[s.uid]
        if c.datatype in ("fmap", None):
            continue
        key = (
            c.datatype or "",
            c.suffix or "",
            c.entities.get("task", ""),
            c.entities.get("acq", ""),
        )
        groups.setdefault(key, []).append(s)
    names: dict[str, str] = {}  # series uid -> BIDS base name (without extension)
    for members in groups.values():
        members.sort(key=lambda s: s.number or 0)
        for index, s in enumerate(members, start=1):
            c = classes[s.uid]
            entities = {**base_entities, **c.entities}
            if len(members) > 1:
                entities["run"] = str(index)
            names[s.uid] = bids_name(entities, c.suffix or "", "")

    # series that gave several images cannot be written as one BIDS file (not supported yet)
    for s in chosen:
        c = classes[s.uid]
        if c.datatype not in ("fmap", None) and len(manifest.conversions[s.uid].images) != 1:
            plan.notes.append(
                f"Series {s.number} gave {len(manifest.conversions[s.uid].images)} images; only "
                f"single-image {c.suffix} series are supported, so it was not written."
            )
            names.pop(s.uid, None)

    # -- fieldmap sets: magnitude (two echoes) + phase ----------------------------------
    mags = sorted(
        (s for s in chosen if classes[s.uid].kind == "fieldmap-magnitude"),
        key=lambda s: s.number or 0,
    )
    phases = sorted(
        (s for s in chosen if classes[s.uid].kind == "fieldmap-phase"), key=lambda s: s.number or 0
    )
    sets: list[tuple[DicomSeries, DicomSeries]] = []
    for mag in mags:
        mag_images = sorted(manifest.conversions[mag.uid].images, key=lambda i: i.suffix)
        partner = next(
            (
                p
                for p in phases
                if p.description == mag.description
                and (p.rows, p.columns, p.slices) == (mag.rows, mag.columns, mag.slices)
                and (p.number or 0) > (mag.number or 0)
            ),
            None,
        )
        if len(mag_images) != 2:
            plan.notes.append(
                f"Fieldmap series {mag.number} gave {len(mag_images)} magnitude image(s), "
                "but two echoes are needed; it was not written."
            )
        elif partner is None:
            plan.notes.append(
                f"Fieldmap series {mag.number} has no matching phase image; it was not written."
            )
        elif len(manifest.conversions[partner.uid].images) != 1:
            plan.notes.append(
                f"Fieldmap phase series {partner.number} did not give exactly one image; "
                "the fieldmap was not written."
            )
        else:
            sets.append((mag, partner))
            phases.remove(partner)
    for orphan in phases:
        plan.notes.append(
            f"Fieldmap phase series {orphan.number} has no matching magnitude image; "
            "it was not written."
        )

    descriptions = [m.description for m, _ in sets]
    use_acq = len(sets) > 1 and len(set(descriptions)) == len(descriptions)
    for index, (mag, phase) in enumerate(sets, start=1):
        extra: dict[str, str] = {}
        if len(sets) > 1:
            extra = {"acq": _alnum(mag.description)} if use_acq else {"run": str(index)}
        e1, e2 = sorted(manifest.conversions[mag.uid].images, key=lambda i: i.suffix)
        phase_image = manifest.conversions[phase.uid].images[0]
        ents = {**base_entities, **extra}
        outputs = [
            (mag, e1, "magnitude1", "magnitude1"),
            (mag, e2, "magnitude2", "magnitude2"),
            (phase, phase_image, "phasediff", "phasediff"),
        ]
        te1 = _sidecar(ws, e1, remove).get("EchoTime")
        te2 = _sidecar(ws, e2, remove).get("EchoTime")
        for series, image, suffix, kind in outputs:
            name = bids_name(ents, suffix, "")
            data = _sidecar(ws, image, remove)
            if suffix == "phasediff":
                data.pop("EchoTime", None)
                data["EchoTime1"], data["EchoTime2"] = te1, te2
            plan.files.append(
                PlannedFile(
                    series.uid,
                    relpath("fmap", name + ".nii.gz"),
                    kind,
                    source=image.nifti,
                    sha256=image.sha256[image.nifti],
                )
            )
            plan.files.append(
                PlannedFile(series.uid, relpath("fmap", name + ".json"), kind + ".json", data=data)
            )

    # -- which runs does each fieldmap set correct? -------------------------------------
    set_numbers = [m.number or 0 for m, _ in sets]
    intended: dict[int, list[str]] = {n: [] for n in set_numbers}
    for s in chosen:
        c = classes[s.uid]
        if c.datatype not in ("func", "dwi") or s.uid not in names:
            continue
        override = manifest.overrides.get(s.uid)
        wanted = override.fieldmap if override else None
        if wanted == "none":
            continue
        if wanted is not None:
            if not wanted.isdigit() or int(wanted) not in intended:
                raise StepError(
                    code="FIELDMAP_UNKNOWN",
                    message=f"Series {s.number} is set to use fieldmap {wanted}, "
                    "but there is no such fieldmap among the series to import.",
                    suggested_action="Use the series number of a fieldmap magnitude series, "
                    "or 'none'. See 'mrforge import show'.",
                )
            target = int(wanted)
        else:
            earlier = [n for n in set_numbers if n < (s.number or 0)]
            if not earlier:
                if set_numbers:
                    plan.notes.append(
                        f"Series {s.number} comes before every fieldmap, so no fieldmap is "
                        "assigned to it (set one with 'mrforge import set --fieldmap')."
                    )
                continue
            target = max(earlier)
        intended[target].append(inside_subject(c.datatype or "", names[s.uid] + ".nii.gz"))
    for mag, phase in sets:
        paths = sorted(intended[mag.number or 0])
        plan.uses[f"{mag.number}/{phase.number}"] = paths
        for pf in plan.files:
            if pf.uid in (mag.uid, phase.uid) and pf.data is not None:
                pf.data["IntendedFor"] = paths
        if not paths:
            plan.notes.append(
                f"Fieldmap series {mag.number}/{phase.number} is not assigned to any run."
            )

    # -- write plans for anat, func and dwi ---------------------------------------------
    for s in chosen:
        c = classes[s.uid]
        if s.uid not in names:
            continue
        image = manifest.conversions[s.uid].images[0]
        name = names[s.uid]
        data = _sidecar(ws, image, remove)
        if c.datatype == "func":
            data = {"TaskName": c.entities["task"], **data}
        plan.files.append(
            PlannedFile(
                s.uid, relpath(c.datatype or "", name + ".nii.gz"), c.suffix or "",
                source=image.nifti, sha256=image.sha256[image.nifti],
            )
        )  # fmt: skip
        plan.files.append(
            PlannedFile(
                s.uid,
                relpath(c.datatype or "", name + ".json"),
                (c.suffix or "") + ".json",
                data=data,
            )
        )
        for kind, rel in (("bval", image.bval), ("bvec", image.bvec)):
            if rel:
                plan.files.append(
                    PlannedFile(
                        s.uid, relpath(c.datatype or "", f"{name}.{kind}"), kind,
                        source=rel, sha256=image.sha256[rel],
                    )
                )  # fmt: skip
    for pf in plan.files:
        if pf.data is not None:
            pf.text = _json_text(pf.data)
            pf.sha256 = _sha_text(pf.text)
    plan.files.sort(key=lambda f: f.target)
    return plan


# -- writing ----------------------------------------------------------------------------


def _existing_hash(ws: Workspace, rel: str) -> str | None:
    path = ws.abspath(rel)
    return file_sha256(ws, rel) if path.is_file() else None


def _without_intended_for(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k != "IntendedFor"}


def _only_intended_for_differs(ws: Workspace, pf: PlannedFile) -> bool:
    """True if a fieldmap sidecar on disk equals the planned one except for IntendedFor.
    This is the one change allowed to existing files: adding a run later must be able to extend
    the list of runs a fieldmap corrects (BIDS expects that), while the image data and every
    other field stay exactly as they were."""
    if pf.data is None or "IntendedFor" not in pf.data:
        return False
    try:
        current = json.loads(ws.abspath(pf.target).read_text())
    except (OSError, ValueError):
        return False
    return _without_intended_for(current) == _without_intended_for(pf.data)


def _check_safe(
    ws: Workspace, manifest: ImportManifest, plan: Plan
) -> tuple[list[PlannedFile], list[PlannedFile]]:
    """Refuse to overwrite or rename anything. Returns (files to write, sidecars to update)."""
    per_series: dict[str, set[str]] = {}
    for pf in plan.files:
        per_series.setdefault(pf.uid, set()).add(pf.target)
    for uid, targets in per_series.items():
        done = manifest.organized.get(uid)
        if done is not None and set(done.files) != targets:
            raise StepError(
                code="ORGANIZE_WOULD_RENAME",
                message="Adding or changing series would change the names of files that are "
                "already in rawbids/ (for example a second run of the same task needs 'run-1' "
                "and 'run-2').",
                probable_cause="Raw data is never renamed or overwritten once it is written.",
                suggested_action="Create a new workspace and import again with the final choices.",
            )
    todo: list[PlannedFile] = []
    updates: list[PlannedFile] = []
    clashes: list[str] = []
    for pf in plan.files:
        current = _existing_hash(ws, pf.target)
        if current is None:
            todo.append(pf)
        elif current != pf.sha256:
            if _only_intended_for_differs(ws, pf):
                updates.append(pf)
            else:
                clashes.append(pf.target.removeprefix("rawbids/"))
    if clashes:
        shown = ", ".join(clashes[:3]) + (" ..." if len(clashes) > 3 else "")
        raise StepError(
            code="ORGANIZE_COLLISION",
            message=f"rawbids/ already contains different files with the same names ({shown}).",
            probable_cause="Another import was already written for this subject and session; "
            "raw data is never overwritten.",
            suggested_action="Import into another subject or session "
            "(mrforge import scan --subject / --session), or a new workspace.",
        )
    return todo, updates


def _write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _read_only(path: Path) -> None:
    path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _dataset_files(ws: Workspace, manifest: ImportManifest) -> None:
    root = ws.root / "rawbids"
    root.mkdir(exist_ok=True)
    description = root / "dataset_description.json"
    if not description.exists():
        _write_text(
            description,
            _json_text(
                {
                    "Name": ws.name,
                    "BIDSVersion": BIDS_VERSION,
                    "DatasetType": "raw",
                    "GeneratedBy": [{"Name": "MRForge", "Version": __version__}],
                }
            ),
        )
    readme = root / "README"
    if not readme.exists():
        _write_text(readme, README_TEXT)
    participants = root / "participants.tsv"
    ids = {"participant_id"}
    if participants.exists():
        ids |= {ln.split("\t")[0] for ln in participants.read_text().splitlines() if ln.strip()}
    ids.add(manifest.subject)
    rows = ["participant_id"] + sorted(i for i in ids if i != "participant_id")
    text = "\n".join(rows) + "\n"
    if not participants.exists() or participants.read_text() != text:
        _write_text(participants, text)


def organize(ws: Workspace, manifest: ImportManifest, rules: RuleSet) -> OrganizeSummary:
    """Write the BIDS dataset. All checks happen before the first file is written."""
    plan = build_plan(ws, manifest, rules)
    todo, updates = _check_safe(ws, manifest, plan)
    summary = OrganizeSummary(notes=list(plan.notes))
    changing = {id(pf) for pf in [*todo, *updates]}
    summary.in_place = [pf.target for pf in plan.files if id(pf) not in changing]
    _dataset_files(ws, manifest)
    for pf in todo:
        target = ws.abspath(pf.target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if pf.text is not None:
            _write_text(target, pf.text)
        else:
            source = ws.abspath(pf.source or "")
            try:
                os.link(source, target)  # same data, no second copy on disk
            except OSError:
                shutil.copy2(source, target)
        _read_only(target)
        summary.written.append(pf.target)
    for pf in updates:
        target = ws.abspath(pf.target)
        _write_text(target, pf.text or "")  # replaces the read-only file by a new one
        _read_only(target)
        summary.updated.append(pf.target)
    subject_id = ws.get_or_create_subject(manifest.subject)
    with ws.session() as s:
        for pf in plan.files:
            if s.scalar(select(File).where(File.relpath == pf.target)) is None:
                s.add(File(subject_id=subject_id, relpath=pf.target, kind=pf.kind))
    organized: dict[str, dict[str, str]] = {}
    for pf in plan.files:
        organized.setdefault(pf.uid, {})[pf.target] = pf.sha256
    changed_uids = {pf.uid for pf in updates}
    for uid, files in organized.items():
        previous = manifest.organized.get(uid)
        if previous is None or uid in changed_uids:
            manifest.organized[uid] = OrganizedSeries(files=files)
    manifest.organize_notes = list(plan.notes)
    save_manifest(ws, manifest)
    return summary
