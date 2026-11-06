"""Loose NIfTI files in the review table.

Each folder (one subject) becomes one scan, like a DICOM scan: every NIfTI file is a "series"
described from its JSON sidecar (when there is one) and its header, and the same rules that
recognise DICOM series propose a type with a confidence. Where the rules are unsure the file
is left for the researcher (action "ask"); nothing is guessed. Fieldmaps cannot be made from
loose files (they need their magnitude and phase images together), so the rules' fieldmaps are
shown as skipped with that reason.

The user's own file names are not stored. A name that follows BIDS (``..._task-rest_bold``)
contributes its task and suffix, a sidecar contributes its scanner description; otherwise the
file is called "NIfTI file N".
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

from mrforge.bids import parse_bids_name
from mrforge.errors import StepError
from mrforge.hashing import sha256_of
from mrforge.importing.classify import ENTITY_VALUE, apply_rules, load_rules
from mrforge.importing.convert import _read_image, converted_dir
from mrforge.importing.existing import (
    NiftiFile,
    _copy_image,
    _repetition_time,
    _volumes,
    inspect_nifti,
)
from mrforge.importing.inspect import NiftiFolder
from mrforge.importing.manifest import (
    list_manifests,
    manifest_dir,
    next_manifest_id,
    save_manifest,
)
from mrforge.importing.models import (
    Conversion,
    DicomSeries,
    ImportGroup,
    ImportManifest,
    Override,
    SourceInfo,
)
from mrforge.importing.scan import SUBJECT_RE, next_subject_label
from mrforge.workspace import Workspace


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _name_hints(name: str) -> tuple[str, dict[str, str]]:
    """(description, entities) from a BIDS-like file name, else ("", {})."""
    entities, suffix, _ext = parse_bids_name(name)
    if suffix is None or not entities:
        return "", {}
    keep = {k: v for k, v in entities.items() if k in ("task", "acq")}
    parts = [f"{k}-{v}" for k, v in keep.items()] + [suffix]
    return "_".join(parts), {k: v for k, v in keep.items() if k == "task"}


def _series_for(
    f: NiftiFile, index: int, digest: str, used_numbers: set[int]
) -> tuple[DicomSeries, dict[str, str]]:
    sc = f.sidecar
    hint, entities = _name_hints(f.path.name)
    description = str(sc.get("SeriesDescription") or "") or hint or f"NIfTI file {index}"
    number = sc.get("SeriesNumber")
    number = int(number) if isinstance(number, int | float) else index
    while number in used_numbers:  # echoes of one series share a SeriesNumber
        number += 1000
    used_numbers.add(number)
    image_type = sc.get("ImageType")
    series = DicomSeries(
        uid=f"nifti-{index}-{digest[:12]}",
        number=number,
        description=description,
        protocol=str(sc.get("ProtocolName") or ""),
        sequence_name=str(sc["SequenceName"]) if sc.get("SequenceName") else None,
        modality="MR",
        image_type=[str(x) for x in image_type] if isinstance(image_type, list) else [],
        rows=f.shape[1] if len(f.shape) > 1 else None,
        columns=f.shape[0],
        slices=f.shape[2] if len(f.shape) > 2 else 1,
        volumes=_volumes(f),
        n_files=1,
        repetition_time_s=_float(sc.get("RepetitionTime")),
        echo_time_s=_float(sc.get("EchoTime")),
        flip_angle_deg=_float(sc.get("FlipAngle")),
        slice_thickness_mm=_float(sc.get("SliceThickness")),
        phase_encoding_direction=sc.get("PhaseEncodingDirection"),
    )
    return series, entities


def _fingerprint(folder: Path, rels: list[str], label: str) -> str:
    digest = hashlib.sha256(label.encode())
    for rel in sorted(rels):
        digest.update(f"{rel}\0{(folder / rel).stat().st_size}\0".encode())
    return digest.hexdigest()[:16]


def _subject(ws: Workspace, label: str, taken: set[str]) -> str:
    if SUBJECT_RE.fullmatch(label) and label not in taken:
        return label
    candidate = next_subject_label(ws)
    while candidate in taken:
        candidate = f"sub-{int(candidate[4:]) + 1:03d}"
    return candidate


def scan_nifti_group(
    ws: Workspace,
    folder: Path,
    groups: list[NiftiFolder],
    progress: Callable[[str], None] | None = None,
) -> tuple[list[ImportManifest], bool]:
    """Scan the NIfTI files of ``folder``, one scan per entry of ``groups`` (a subject each).

    Returns (manifests, is_new). Scanning the same files again returns the same scans."""
    say = progress or (lambda _msg: None)
    folder = folder.expanduser().resolve()
    rules = load_rules(ws)
    known = list_manifests(ws)
    fingerprints = {g.label: _fingerprint(folder, g.files, g.label) for g in groups}
    group_key = hashlib.sha256("|".join(sorted(fingerprints.values())).encode()).hexdigest()[:16]
    found = [
        m
        for m in known
        if m.source.kind == "nifti" and m.source.fingerprint in fingerprints.values()
    ]
    if len(found) == len(groups):
        return sorted(found, key=lambda m: m.id), False

    manifests: list[ImportManifest] = []
    taken = {m.subject for m in known}
    done = {m.source.fingerprint: m for m in found}
    for n, g in enumerate(groups, start=1):
        fp = fingerprints[g.label]
        if fp in done:
            manifests.append(done[fp])
            continue
        say(f"Reading NIfTI files {n} of {len(groups)} ({len(g.files)} files)...")
        manifests.append(_scan_one(ws, folder, g, fp, taken, rules))
        taken.add(manifests[-1].subject)
    if len(manifests) > 1:
        study = hashlib.sha256(group_key.encode()).hexdigest()[:12]
        for i, manifest in enumerate(manifests, start=1):
            manifest.group = ImportGroup(source=group_key, index=i, of=len(manifests), study=study)
            save_manifest(ws, manifest)
    return manifests, True


def _scan_one(
    ws: Workspace, folder: Path, g: NiftiFolder, fingerprint: str, taken: set[str], rules: Any
) -> ImportManifest:
    inspected = [inspect_nifti(folder / rel) for rel in sorted(g.files)]
    manifest_id = next_manifest_id(ws)
    manifest = ImportManifest(
        id=manifest_id,
        source=SourceInfo(
            name=g.label, kind="nifti", n_files=len(inspected), fingerprint=fingerprint
        ),
        subject=_subject(ws, g.label, taken),
        tool_versions={"nibabel": metadata.version("nibabel")},
    )
    used: set[int] = set()
    try:
        for index, f in enumerate(inspected, start=1):
            series, entities = _series_for(f, index, sha256_of(f.path), used)
            manifest.series.append(series)
            out = converted_dir(ws, manifest, series)
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir(parents=True)
            _copy_image(f.path, out / f"{index}.nii.gz")
            sidecar = dict(f.sidecar)
            try:
                seconds, _note = _repetition_time(f, None) if len(f.shape) > 3 else (None, None)
            except StepError as problem:
                seconds = None
                series.warnings.append(problem.message)
            if seconds is not None and "RepetitionTime" not in sidecar:
                sidecar["RepetitionTime"] = seconds
                series.repetition_time_s = seconds
            (out / f"{index}.json").write_text(json.dumps(sidecar, indent=2) + "\n")
            if f.bval and f.bvec:
                shutil.copyfile(f.bval, out / f"{index}.bval")
                shutil.copyfile(f.bvec, out / f"{index}.bvec")
            image = _read_image(ws, out, f"{index}.nii.gz")
            manifest.conversions[series.uid] = Conversion(
                series_uid=series.uid, status="ok", images=[image], tool_version="copied"
            )
            valid = {k: v for k, v in entities.items() if ENTITY_VALUE.fullmatch(v)}
            if valid:
                manifest.overrides[series.uid] = Override(entities=valid)
        apply_rules(manifest, rules)
        save_manifest(ws, manifest)
    except BaseException:
        shutil.rmtree(manifest_dir(ws, manifest_id), ignore_errors=True)  # no half-made scan
        raise
    return manifest
