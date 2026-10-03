"""Scan a DICOM folder or ZIP: copy it into the workspace, read series metadata.

Only a short list of acquisition tags is ever read (pydicom ``specific_tags``), so patient
names, IDs and dates are never loaded into memory, shown, stored or logged.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

import pydicom
from pydicom.errors import InvalidDicomError

from mrforge.errors import StepError
from mrforge.importing.classify import apply_rules, load_rules
from mrforge.importing.manifest import (
    list_manifests,
    next_manifest_id,
    save_manifest,
)
from mrforge.importing.models import (
    CommandRecord,
    DicomSeries,
    ImportManifest,
    SeriesOutput,
    SkippedFile,
    SourceInfo,
)
from mrforge.workspace import Workspace

TAGS = [
    "SOPClassUID", "SeriesInstanceUID", "SeriesNumber", "SeriesDescription", "ProtocolName",
    "SequenceName", "ImageType", "Modality", "Rows", "Columns", "NumberOfFrames",
    "RepetitionTime", "EchoTime", "FlipAngle", "SliceThickness", "ImagePositionPatient",
]  # fmt: skip
DICOMDIR_SOP_CLASS = "1.2.840.10008.1.3.10"  # Media Storage Directory
PARALLEL_THRESHOLD = 48  # below this many files a process pool costs more than it saves
SUBJECT_RE = re.compile(r"sub-[A-Za-z0-9]+")
SESSION_RE = re.compile(r"ses-[A-Za-z0-9]+")


# -- reading headers -----------------------------------------------------------------------


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_header(path: str) -> dict[str, Any]:
    """Read the acquisition tags of one file. Returns {'skip': reason} if it is not an image."""
    p = Path(path)
    if p.name == "DICOMDIR":
        return {"skip": "directory index (DICOMDIR), not an image"}
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True, specific_tags=TAGS)
    except InvalidDicomError:
        return {"skip": "not a DICOM file"}
    except Exception:  # a damaged or truncated file must not stop the whole scan
        return {"skip": "could not be read (damaged or incomplete)"}
    if str(ds.get("SOPClassUID", "")) == DICOMDIR_SOP_CLASS:
        return {"skip": "directory index (DICOMDIR), not an image"}
    uid = ds.get("SeriesInstanceUID")
    if not uid:
        return {"skip": "has no series information (the file may be damaged or incomplete)"}
    position = ds.get("ImagePositionPatient")
    return {
        "uid": str(uid),
        "number": int(ds["SeriesNumber"].value) if "SeriesNumber" in ds else None,
        "description": str(ds.get("SeriesDescription", "")),
        "protocol": str(ds.get("ProtocolName", "")),
        "sequence_name": str(ds["SequenceName"].value) if "SequenceName" in ds else None,
        "image_type": [str(x) for x in ds.get("ImageType", [])],
        "modality": str(ds.get("Modality", "")),
        "rows": int(ds["Rows"].value) if "Rows" in ds else None,
        "columns": int(ds["Columns"].value) if "Columns" in ds else None,
        "frames": int(ds["NumberOfFrames"].value) if "NumberOfFrames" in ds else 1,
        "tr_ms": _float(ds.get("RepetitionTime")),
        "te_ms": _float(ds.get("EchoTime")),
        "flip": _float(ds.get("FlipAngle")),
        "thickness": _float(ds.get("SliceThickness")),
        "position": tuple(round(float(v), 3) for v in position) if position else None,
    }


def _read_all(paths: Sequence[Path], workers: int | None) -> list[dict[str, Any]]:
    as_text = [str(p) for p in paths]
    if len(as_text) < PARALLEL_THRESHOLD or workers == 1:
        return [read_header(p) for p in as_text]
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(read_header, as_text, chunksize=16))
    except BrokenProcessPool:
        # Worker processes could not start (for example when run from an interactive shell).
        # Reading one file at a time gives the same result, only slower.
        return [read_header(p) for p in as_text]


def build_series(headers: list[dict[str, Any]]) -> DicomSeries:
    first = headers[0]
    warnings: list[str] = []
    for key, label in (("description", "description"), ("rows", "image size")):
        if len({h[key] for h in headers}) > 1:
            warnings.append(f"The files of this series do not agree on their {label}.")
    frames = {h["frames"] for h in headers}
    multiframe = frames != {1}
    if multiframe and len(frames) > 1:
        warnings.append("The files of this series hold different numbers of slices.")
    if multiframe:
        slices: int | None = max(frames)  # enhanced DICOM: the slices are frames of one file
    else:
        positions = {h["position"] for h in headers if h["position"] is not None}
        slices = len(positions) or None
    series = DicomSeries(
        uid=first["uid"],
        number=first["number"],
        description=first["description"],
        protocol=first["protocol"],
        sequence_name=first["sequence_name"],
        modality=first["modality"],
        image_type=first["image_type"],
        multiframe=multiframe,
        rows=first["rows"],
        columns=first["columns"],
        slices=slices,
        n_files=len(headers),
        repetition_time_s=None if first["tr_ms"] is None else first["tr_ms"] / 1000,
        echo_time_s=None if first["te_ms"] is None else first["te_ms"] / 1000,
        flip_angle_deg=first["flip"],
        slice_thickness_mm=first["thickness"],
        warnings=warnings,
    )
    return finalize_volumes(series)


def finalize_volumes(series: DicomSeries) -> DicomSeries:
    """Count 3D volumes. Every echo or magnitude/phase image counts separately in the raw file
    count, so divide by the number of images dcm2niix reports for the series."""
    n_images = max(1, len(series.outputs))
    per_image: int | None
    if series.multiframe:
        per_image = series.n_files
    elif series.slices:
        per_image = series.n_files // series.slices if series.n_files % series.slices == 0 else None
    else:
        per_image = None
    if per_image is None or per_image % n_images != 0:
        series.volumes = None
        note = "The number of volumes could not be worked out from the file count."
        # Series without an image (reports, design files) have no volumes to count.
        if series.rows is not None and note not in series.warnings:
            series.warnings.append(note)
    else:
        series.volumes = per_image // n_images
        series.warnings = [w for w in series.warnings if not w.startswith("The number of volumes")]
    return series


def scan_directory(
    root: Path, workers: int | None = None
) -> tuple[list[DicomSeries], list[SkippedFile]]:
    """Read every file below ``root`` and group the images into series (sorted by number)."""
    files = sorted(p for p in root.rglob("*") if p.is_file())
    headers = _read_all(files, workers)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped: list[SkippedFile] = []
    for path, header in zip(files, headers, strict=True):
        if "skip" in header:
            skipped.append(SkippedFile(name=path.name, reason=header["skip"]))
        else:
            grouped[header["uid"]].append(header)
    series = [build_series(h) for h in grouped.values()]
    series.sort(key=lambda s: (s.number is None, s.number or 0, s.uid))
    return series, skipped


# -- bringing the source into the workspace ------------------------------------------------


def _fingerprint(entries: list[tuple[str, int]]) -> str:
    digest = hashlib.sha256()
    for name, size in sorted(entries):
        digest.update(f"{name}\0{size}\n".encode())
    return digest.hexdigest()[:16]


def describe_source(src: Path) -> SourceInfo:
    if src.is_dir():
        entries = [
            (str(p.relative_to(src)), p.stat().st_size) for p in src.rglob("*") if p.is_file()
        ]
        return SourceInfo(
            name=src.name, kind="folder", n_files=len(entries), fingerprint=_fingerprint(entries)
        )
    if src.is_file() and zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as zf:
            entries = [(i.filename, i.file_size) for i in zf.infolist() if not i.is_dir()]
        return SourceInfo(
            name=src.name, kind="zip", n_files=len(entries), fingerprint=_fingerprint(entries)
        )
    raise StepError(
        code="IMPORT_SOURCE_INVALID",
        message=f"'{src}' is not a folder or a ZIP file.",
        probable_cause="The path is wrong, or the file is not a ZIP archive.",
        suggested_action="Give the folder that contains the DICOM files, or a .zip of it.",
    )


def copy_source(src: Path, dest: Path, info: SourceInfo) -> None:
    """Copy a folder, or unpack a ZIP, into ``dest`` (written under a temporary name first, so
    an interrupted copy never looks complete)."""
    partial = dest.with_name(dest.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    if info.kind == "folder":
        shutil.copytree(src, partial, dirs_exist_ok=True)
    else:
        with zipfile.ZipFile(src) as zf:
            for member in zf.infolist():
                target = (partial / member.filename).resolve()
                if not target.is_relative_to(partial.resolve()):
                    shutil.rmtree(partial, ignore_errors=True)
                    raise StepError(
                        code="IMPORT_ZIP_UNSAFE",
                        message="The ZIP file contains a path that points outside its folder.",
                        probable_cause="The archive is damaged or was built to write elsewhere.",
                        suggested_action="Do not import this file; export the scan again.",
                    )
            zf.extractall(partial)
    if dest.exists():
        shutil.rmtree(dest)
    partial.rename(dest)


# -- dcm2niix sidecar pass -------------------------------------------------------------------

SIDECAR_NAME = re.compile(r"(\d+)(?:_(.+))?\.json")


def _dcm2niix_version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    for line in out.splitlines():
        if "version" in line:
            return line.strip()
    return "unknown"


def sidecar_pass(
    dicom_dir: Path, series: list[DicomSeries]
) -> tuple[CommandRecord | None, str, list[str]]:
    """Run ``dcm2niix -b o`` (JSON sidecars only, no images; takes seconds) to learn what the
    vendor-specific headers say: phase-encoding direction with its sign, and how dcm2niix
    splits a series into images (echoes, magnitude/phase). Fills ``series`` in place."""
    exe = shutil.which("dcm2niix")
    if exe is None:
        raise StepError(
            code="TOOL_NOT_FOUND",
            message="The program 'dcm2niix' could not be found.",
            probable_cause="It is not installed or not on the path.",
            suggested_action="Run 'python scripts/check_env.py' to see what is missing.",
        )
    notes: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        argv = [exe, "-b", "o", "-ba", "y", "-f", "%s", "-o", scratch, "-v", "0", str(dicom_dir)]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=900)
        record = CommandRecord(
            argv=[a.replace(scratch, "<scratch>").replace(str(dicom_dir), "<dicom>") for a in argv],
            return_code=proc.returncode,
        )
        by_number: dict[int, list[SeriesOutput]] = defaultdict(list)
        for path in sorted(Path(scratch).glob("*.json")):
            match = SIDECAR_NAME.fullmatch(path.name)
            if not match:
                continue
            data = json.loads(path.read_text())
            by_number[int(match.group(1))].append(
                SeriesOutput(
                    suffix=match.group(2) or "",
                    echo_number=data.get("EchoNumber"),
                    echo_time_s=data.get("EchoTime"),
                    repetition_time_s=data.get("RepetitionTime"),
                    image_type=data.get("ImageType", []),
                    phase_encoding_direction=data.get("PhaseEncodingDirection"),
                    total_readout_time_s=data.get("TotalReadoutTime"),
                    effective_echo_spacing_s=data.get("EffectiveEchoSpacing"),
                )
            )
    if proc.returncode != 0 and not by_number:
        notes.append(
            "dcm2niix could not read the session headers; phase-encoding information is missing."
        )
    numbers = [s.number for s in series]
    for s in series:
        if s.number is None or numbers.count(s.number) > 1:
            if s.number is not None:
                notes.append(f"Series number {s.number} is used more than once; details skipped.")
            continue
        s.outputs = by_number.get(s.number, [])
        if s.outputs:  # enhanced DICOM keeps TR/TE in private groups; the sidecar knows them
            s.repetition_time_s = s.repetition_time_s or s.outputs[0].repetition_time_s
            s.echo_time_s = s.echo_time_s or s.outputs[0].echo_time_s
        directions = {o.phase_encoding_direction for o in s.outputs if o.phase_encoding_direction}
        s.phase_encoding_direction = sorted(directions)[0] if len(directions) == 1 else None
        finalize_volumes(s)
    return record, _dcm2niix_version(exe), notes


# -- the whole scan --------------------------------------------------------------------------


def next_subject_label(ws: Workspace) -> str:
    """The next free ``sub-NNN`` (looking at subjects in the database and earlier imports)."""
    from sqlalchemy import select

    from mrforge.models import Subject

    with ws.session() as s:
        labels = list(s.scalars(select(Subject.label)))
    labels += [m.subject for m in list_manifests(ws)]
    numbers = [int(m.group(1)) for lb in labels if (m := re.fullmatch(r"sub-(\d+)", lb))]
    return f"sub-{max(numbers, default=0) + 1:03d}"


def check_labels(subject: str, session: str | None) -> None:
    if not SUBJECT_RE.fullmatch(subject):
        raise StepError(
            code="BAD_SUBJECT_LABEL",
            message=f"'{subject}' is not a valid subject label.",
            probable_cause="BIDS labels are 'sub-' followed by letters and digits only.",
            suggested_action="Use something like sub-001.",
        )
    if session is not None and not SESSION_RE.fullmatch(session):
        raise StepError(
            code="BAD_SESSION_LABEL",
            message=f"'{session}' is not a valid session label.",
            probable_cause="BIDS labels are 'ses-' followed by letters and digits only.",
            suggested_action="Use something like ses-01.",
        )


def _label(subject: str, session: str | None) -> str:
    return f"{subject}/{session}" if session else subject


def _find_existing(ws: Workspace, info: SourceInfo) -> ImportManifest | None:
    for manifest in list_manifests(ws):
        same = manifest.source.fingerprint == info.fingerprint
        if same and (ws.root / manifest.dicom_dir).is_dir():
            return manifest
    return None


def scan_source(
    ws: Workspace,
    src: Path,
    subject: str | None = None,
    session: str | None = None,
    workers: int | None = None,
) -> tuple[ImportManifest, bool]:
    """Copy ``src`` into ``sourcedata/dicom/``, read the series and save the manifest.
    Returns (manifest, is_new). Scanning the same source again returns the existing manifest."""
    src = src.expanduser().resolve()
    info = describe_source(src)
    if subject is not None or session is not None:
        check_labels(subject or "sub-001", session)
    existing = _find_existing(ws, info)
    if existing is not None:
        other_label = (subject is not None and subject != existing.subject) or (
            session is not None and session != existing.session
        )
        if other_label:
            raise StepError(
                code="IMPORT_ALREADY_SCANNED",
                message=f"This source was already scanned as {existing.id} "
                f"({_label(existing.subject, existing.session)}).",
                probable_cause="The same data cannot be imported twice under another label.",
                suggested_action="Use the existing import, or choose a different source.",
            )
        return existing, False
    manifest_id = next_manifest_id(ws)
    dest = ws.root / "sourcedata" / "dicom" / manifest_id
    copy_source(src, dest, info)
    series, skipped = scan_directory(dest, workers)
    command, dcm2niix_version, notes = sidecar_pass(dest, series)
    manifest = ImportManifest(
        id=manifest_id,
        source=info,
        dicom_dir=ws.relpath(dest),
        subject=subject or next_subject_label(ws),
        session=session,
        series=series,
        skipped_files=skipped,
        tool_versions={"pydicom": pydicom.__version__, "dcm2niix": dcm2niix_version},
        commands=[command] if command else [],
        warnings=notes,
    )
    apply_rules(manifest, load_rules(ws))
    save_manifest(ws, manifest)
    return manifest, True
