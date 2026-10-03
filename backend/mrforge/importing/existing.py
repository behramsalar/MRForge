"""Import data that is already NIfTI or already a BIDS dataset (no conversion).

Safety rules for both:
  * The user's files are only ever COPIED, never hard-linked: making a linked file read-only
    would change the user's original too.
  * Nothing in rawbids/ is overwritten; every check happens before the first file is written;
    a second run with the same data changes nothing.
  * Names of the user's files are never stored (they can contain a person's name); the import
    refers to them by number.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from nibabel.loadsave import load as load_image
from nibabel.nifti1 import Nifti1Header
from sqlalchemy import select

from mrforge.bids import parse_bids_name, split_extension
from mrforge.errors import StepError
from mrforge.hashing import file_sha256, sha256_of
from mrforge.importing.bids_validate import ValidationReport, format_report, validate_path
from mrforge.importing.classify import ENTITY_VALUE, RuleSet, apply_rules, effective_all
from mrforge.importing.convert import _read_image, converted_dir
from mrforge.importing.manifest import (
    list_manifests,
    manifest_dir,
    next_manifest_id,
    save_manifest,
)
from mrforge.importing.models import (
    Conversion,
    DicomSeries,
    ImportManifest,
    OrganizedSeries,
    Override,
    SourceInfo,
)
from mrforge.importing.organize import OrganizeSummary, organize
from mrforge.importing.scan import check_labels, next_subject_label
from mrforge.models import File
from mrforge.niftiutil import is_readable_nifti
from mrforge.workspace import Workspace

TIME_UNITS = {"sec": 1.0, "msec": 1e-3, "usec": 1e-6}
IGNORED_DIRS = {"derivatives", "sourcedata", "code"}  # not raw data: never copied into rawbids/


# -- NIfTI files ------------------------------------------------------------------------------


@dataclass
class NiftiFile:
    path: Path
    shape: list[int]
    zooms: list[float]
    time_unit: str
    sidecar: dict[str, Any]
    bval: Path | None = None
    bvec: Path | None = None


@dataclass
class NiftiImport:
    manifest: ImportManifest
    summary: OrganizeSummary
    is_new: bool
    notes: list[str] = field(default_factory=list)


def _bad_file(path: Path, why: str, action: str) -> StepError:
    return StepError(
        code="INPUT_NOT_NIFTI",
        message=f"The file '{path.name}' cannot be imported: {why}",
        probable_cause="It is not a readable NIfTI image (.nii or .nii.gz).",
        suggested_action=action,
    )


def _stem(path: Path) -> Path:
    return path.with_name(split_extension(path.name)[0])


def inspect_nifti(path: Path) -> NiftiFile:
    if not path.is_file():
        raise _bad_file(path, "it does not exist.", "Check the path.")
    if not path.name.endswith((".nii", ".nii.gz")):
        raise _bad_file(path, "its name does not end in .nii or .nii.gz.", "Choose a NIfTI file.")
    if not is_readable_nifti(path):
        raise _bad_file(path, "it is damaged or not a NIfTI file.", "Check it opens in FSLeyes.")
    try:
        header = cast(Nifti1Header, load_image(path).header)
        shape = [int(x) for x in header.get_data_shape()]  # type: ignore[no-untyped-call]
        zooms = [float(z) for z in header.get_zooms()]  # type: ignore[no-untyped-call]
        unit = str(header.get_xyzt_units()[1])  # type: ignore[no-untyped-call]
    except Exception as exc:
        why = f"it could not be read ({type(exc).__name__})."
        raise _bad_file(path, why, "Check it opens in FSLeyes.") from exc
    sidecar: dict[str, Any] = {}
    json_path = _stem(path).with_name(_stem(path).name + ".json")
    if json_path.is_file():
        try:
            sidecar = json.loads(json_path.read_text())
        except ValueError as exc:
            raise StepError(
                code="INPUT_JSON_INVALID",
                message=f"The sidecar next to '{path.name}' is not valid JSON.",
                probable_cause="It was edited by hand or damaged.",
                suggested_action="Fix or remove the .json file next to the image, then try again.",
            ) from exc
    stem = _stem(path)
    bval, bvec = stem.with_name(stem.name + ".bval"), stem.with_name(stem.name + ".bvec")
    return NiftiFile(
        path, shape, zooms, unit,
        sidecar if isinstance(sidecar, dict) else {},
        bval if bval.is_file() else None, bvec if bvec.is_file() else None,
    )  # fmt: skip


def _volumes(f: NiftiFile) -> int:
    return f.shape[3] if len(f.shape) > 3 else 1


def _check_shape(f: NiftiFile, kind: str) -> None:
    volumes = _volumes(f)
    wanted_3d = kind in ("T1w", "T2w")
    problem = None
    if len(f.shape) > 4:
        problem = "it has more than four dimensions"
    elif wanted_3d and volumes != 1:
        problem = f"a {kind} image should be a single 3D volume, but it has {volumes} volumes"
    elif kind == "bold" and volumes < 2:
        problem = "a functional (bold) image needs several volumes over time, but it has one"
    elif kind == "dwi" and volumes < 2:
        problem = "a diffusion image needs several volumes (one per direction), but it has one"
    if problem:
        raise StepError(
            code="NIFTI_WRONG_SHAPE",
            message=f"'{f.path.name}' does not look like a {kind} image: {problem}.",
            probable_cause="The type chosen with --type does not match the image.",
            suggested_action="Check the file and the --type you gave.",
        )


def _check_dwi(f: NiftiFile) -> None:
    if f.bval is None or f.bvec is None:
        raise StepError(
            code="DWI_NEEDS_DIRECTIONS",
            message=f"The diffusion image '{f.path.name}' needs its b-value and b-vector files.",
            probable_cause="They must sit next to the image with the same name "
            "(for example scan.bval and scan.bvec).",
            suggested_action="Put the .bval and .bvec files next to the image and try again.",
        )
    volumes = _volumes(f)
    n_bval = len(f.bval.read_text().split())
    rows = [ln.split() for ln in f.bvec.read_text().splitlines() if ln.strip()]
    if n_bval != volumes or len(rows) != 3 or any(len(r) != volumes for r in rows):
        raise StepError(
            code="DWI_DIRECTIONS_MISMATCH",
            message=f"The b-value/b-vector files of '{f.path.name}' do not match its "
            f"{volumes} volumes ({n_bval} b-values, {len(rows)} b-vector rows).",
            probable_cause="The direction files belong to a different image, or are incomplete.",
            suggested_action="Use the .bval and .bvec files that were exported with this image.",
        )


def _repetition_time(f: NiftiFile, tr: float | None) -> tuple[float, str | None]:
    """The TR in seconds for a functional image, and a note about where it came from."""
    if tr is not None:
        return tr, "The repetition time was given with --tr."
    if "RepetitionTime" in f.sidecar:
        return float(f.sidecar["RepetitionTime"]), None
    factor = TIME_UNITS.get(f.time_unit)
    if factor and len(f.zooms) > 3 and f.zooms[3] > 0:
        return f.zooms[3] * factor, "The repetition time was read from the image header."
    raise StepError(
        code="TR_NEEDED",
        message=f"The repetition time (TR) of '{f.path.name}' is not known.",
        probable_cause="There is no sidecar with RepetitionTime, and the image header has no "
        "usable time step.",
        suggested_action="Give it in seconds, for example --tr 2.0.",
    )


def _copy_image(src: Path, dest: Path) -> None:
    if src.name.endswith(".gz"):
        shutil.copyfile(src, dest)
        return
    # mtime 0, no stored name: the same input always gives the same bytes
    with src.open("rb") as raw, open(dest, "wb") as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0) as gz:
            shutil.copyfileobj(raw, gz)


def import_nifti(
    ws: Workspace,
    files: list[Path],
    kind: str,
    rules: RuleSet,
    subject: str | None = None,
    session: str | None = None,
    task: str | None = None,
    acq: str | None = None,
    tr: float | None = None,
) -> NiftiImport:
    """Copy NIfTI files into the workspace and write them to rawbids/ (one type per call)."""
    kinds = rules.import_kinds()
    if kind not in kinds or kinds[kind].datatype == "fmap":
        usable = sorted(k for k, r in kinds.items() if r.datatype != "fmap")
        raise StepError(
            code="UNKNOWN_KIND" if kind not in kinds else "NIFTI_TYPE_UNSUPPORTED",
            message=f"'{kind}' cannot be imported from NIfTI files.",
            probable_cause="Fieldmaps need their magnitude and phase images together, so they "
            "are only supported when converting DICOM.",
            suggested_action=f"Use one of: {', '.join(usable)}.",
        )
    if not files:
        raise StepError(
            code="NO_FILES", message="No NIfTI files were given.",
            suggested_action="Give one or more .nii/.nii.gz files.",
        )  # fmt: skip
    labels = {k: v for k, v in (("task", task), ("acq", acq)) if v is not None}
    for key, value in labels.items():
        if not ENTITY_VALUE.fullmatch(value):
            raise StepError(
                code="BAD_LABEL",
                message=f"'{key}={value}' is not a valid label.",
                probable_cause="Labels may only contain letters and digits.",
                suggested_action="Use something like --task rest.",
            )
    if "task" in kinds[kind].needs and "task" not in labels:
        raise StepError(
            code="TASK_NEEDED",
            message=f"A {kind} image needs a task name.",
            probable_cause="BIDS names functional runs after the task that was done.",
            suggested_action="Add it, for example --task rest.",
        )
    check_labels(subject or "sub-001", session)
    inspected = [inspect_nifti(Path(p).expanduser().resolve()) for p in files]
    for f in inspected:
        _check_shape(f, kind)
        if kind == "dwi":
            _check_dwi(f)
    notes: list[str] = []
    times: list[float] = []
    if kind == "bold":
        for f in inspected:
            seconds, note = _repetition_time(f, tr)
            times.append(seconds)
            if note:
                notes.append(f"{f.path.name}: {note}")

    digest = hashlib.sha256()
    for f in inspected:
        digest.update(sha256_of(f.path).encode())
    digest.update(json.dumps([kind, subject, session, labels, tr]).encode())
    fingerprint = digest.hexdigest()[:16]
    for existing in list_manifests(ws):
        if existing.source.kind == "nifti" and existing.source.fingerprint == fingerprint:
            return NiftiImport(existing, organize(ws, existing, rules), False, notes)

    manifest_id = next_manifest_id(ws)
    manifest = ImportManifest(
        id=manifest_id,
        source=SourceInfo(
            name=f"{len(inspected)} NIfTI file(s)", kind="nifti", n_files=len(inspected),
            fingerprint=fingerprint,
        ),
        subject=subject or next_subject_label(ws),
        session=session,
        tool_versions={"nibabel": metadata.version("nibabel")},
    )  # fmt: skip
    try:
        for index, f in enumerate(inspected, start=1):
            digest_i = sha256_of(f.path)
            label = f"NIfTI file {index}"  # the user's own file name is never stored
            series = DicomSeries(
                uid=f"nifti-{index}-{digest_i[:12]}",
                number=index,
                description=label,
                protocol=label,
                modality="MR",
                rows=f.shape[1],
                columns=f.shape[0],
                slices=f.shape[2],
                volumes=_volumes(f),
                n_files=1,
            )
            manifest.series.append(series)
            out = converted_dir(ws, manifest, series)
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir(parents=True)
            _copy_image(f.path, out / f"{index}.nii.gz")
            sidecar = dict(f.sidecar)
            if kind == "bold":
                sidecar["RepetitionTime"] = times[index - 1]
            (out / f"{index}.json").write_text(json.dumps(sidecar, indent=2) + "\n")
            if f.bval and f.bvec:
                shutil.copyfile(f.bval, out / f"{index}.bval")
                shutil.copyfile(f.bvec, out / f"{index}.bvec")
            image = _read_image(ws, out, f"{index}.nii.gz")
            manifest.conversions[series.uid] = Conversion(
                series_uid=series.uid, status="ok", images=[image], tool_version="copied",
            )  # fmt: skip
            manifest.overrides[series.uid] = Override(kind=kind, entities=dict(labels))
        apply_rules(manifest, rules)
        save_manifest(ws, manifest)
        effective_all(manifest, rules)  # fails early if the decisions do not resolve
        summary = organize(ws, manifest, rules)
    except BaseException:
        shutil.rmtree(manifest_dir(ws, manifest_id), ignore_errors=True)  # no half-made import
        raise
    return NiftiImport(manifest, summary, True, notes)


# -- existing BIDS datasets ---------------------------------------------------------------------


@dataclass
class BidsImportSummary:
    subjects: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    in_place: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # top-level files where the existing one stayed
    notes: list[str] = field(default_factory=list)


@dataclass
class BidsImport:
    manifest: ImportManifest
    summary: BidsImportSummary
    is_new: bool
    source_report: ValidationReport | None = None


def _read_description(source: Path) -> dict[str, Any]:
    path = source / "dataset_description.json"
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        raise StepError(
            code="IMPORT_NOT_BIDS",
            message="This folder is not a BIDS dataset (dataset_description.json is missing "
            "or unreadable).",
            probable_cause="A BIDS dataset always has a dataset_description.json at its top.",
            suggested_action="Choose the top folder of the BIDS dataset, or convert DICOM "
            "files with 'mrforge import scan'.",
        ) from exc
    return data


def _plan_bids(source: Path) -> tuple[dict[str, Path], list[str]]:
    """relative path -> source file, and notes about what is left out."""
    files: dict[str, Path] = {}
    notes: list[str] = []
    for current, dirs, names in os.walk(source, followlinks=False):
        here = Path(current)
        rel_dir = here.relative_to(source)
        kept_dirs = []
        for d in sorted(dirs):
            if d.startswith("."):
                notes.append(f"The hidden folder '{d}' was not copied.")
            elif here == source and d in IGNORED_DIRS:
                notes.append(f"The folder '{d}' was not copied (it is not raw data).")
            elif (here / d).is_symlink():
                notes.append(f"The link '{d}' was not copied.")
            else:
                kept_dirs.append(d)
        dirs[:] = kept_dirs
        for name in sorted(names):
            path = here / name
            if path.is_symlink():
                notes.append(f"The link '{(rel_dir / name).as_posix()}' was not copied.")
            elif name.startswith(".") and name != ".bidsignore":
                continue
            else:
                files[(rel_dir / name).as_posix()] = path
    return files, notes


def merge_participants(existing: str | None, incoming: str) -> str:
    """Union of two participants tables: columns are added, existing rows are kept."""

    def parse(text: str) -> tuple[list[str], dict[str, dict[str, str]]]:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        header = lines[0].split("\t")
        rows = {}
        for ln in lines[1:]:
            cells = ln.split("\t")
            row = dict(zip(header, cells, strict=False))
            rows[row.get("participant_id", cells[0])] = row
        return header, rows

    in_header, in_rows = parse(incoming)
    if existing is None:
        return incoming if incoming.endswith("\n") else incoming + "\n"
    ex_header, ex_rows = parse(existing)
    columns = ex_header + [c for c in in_header if c not in ex_header]
    merged = {**in_rows, **ex_rows}  # existing rows win
    out = ["\t".join(columns)]
    for pid in sorted(merged):
        out.append("\t".join(merged[pid].get(c, "n/a") for c in columns))
    return "\n".join(out) + "\n"


def _bids_kind(rel: str) -> str | None:
    _, suffix, ext = parse_bids_name(rel)
    if suffix is None:
        return None
    if ext in (".bval", ".bvec"):
        return ext[1:]  # the same kind names the organizer registers
    return suffix if ext in (".nii", ".nii.gz") else f"{suffix}{ext}"


def import_bids(
    ws: Workspace, source: Path, allow_errors: bool = False, check_source: bool = True
) -> BidsImport:
    """Copy an existing BIDS dataset into rawbids/ (no conversion), register its subjects and
    files, and never overwrite anything."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise StepError(
            code="IMPORT_SOURCE_INVALID",
            message=f"'{source}' is not a folder.",
            suggested_action="Give the top folder of the BIDS dataset.",
        )
    raw_root = ws.root / "rawbids"
    if source == raw_root.resolve() or raw_root.resolve() in source.parents:
        raise StepError(
            code="IMPORT_BIDS_SELF",
            message="That folder is already this workspace's own rawbids/ folder.",
            suggested_action="Choose a different dataset.",
        )
    description = _read_description(source)
    if description.get("DatasetType") == "derivative":
        raise StepError(
            code="IMPORT_BIDS_IS_DERIVATIVE",
            message="This is a derivatives dataset (processed data), not raw data.",
            probable_cause="Its dataset_description.json says DatasetType: derivative.",
            suggested_action="Import the raw BIDS dataset it was made from.",
        )
    notes: list[str] = []
    report: ValidationReport | None = None
    if check_source:
        try:
            report = validate_path(source, source.name)
        except StepError as err:
            if err.code != "VALIDATOR_NOT_FOUND":
                raise
            notes.append("The source dataset was not checked: " + err.message)
        if report is not None and report.errors and not allow_errors:
            first = report.errors[0]
            raise StepError(
                code="IMPORT_BIDS_INVALID",
                message=f"The BIDS dataset has {len(report.errors)} error(s), for example: "
                f"{first.what}",
                probable_cause=first.why,
                suggested_action="Fix them in the source dataset ('mrforge import validate' style "
                "explanations are shown by the BIDS check), or import anyway with --allow-errors.",
            )
    files, plan_notes = _plan_bids(source)
    notes += plan_notes
    top = {rel: p for rel, p in files.items() if "/" not in rel}
    subject_files = {rel: p for rel, p in files.items() if rel.startswith("sub-")}
    other = {rel: p for rel, p in files.items() if rel not in top and rel not in subject_files}
    summary = BidsImportSummary(notes=notes)

    # -- all checks first -----------------------------------------------------------------------
    clashes: list[str] = []
    todo: list[str] = []
    for rel, src in {**subject_files, **other}.items():
        target = raw_root / rel
        if not target.exists():
            todo.append(rel)
        elif target.stat().st_size != src.stat().st_size or sha256_of(target) != sha256_of(src):
            clashes.append(rel)
        else:
            summary.in_place.append(f"rawbids/{rel}")
    if clashes:
        shown = ", ".join(clashes[:3]) + (" ..." if len(clashes) > 3 else "")
        raise StepError(
            code="ORGANIZE_COLLISION",
            message=f"rawbids/ already contains different files with the same names ({shown}).",
            probable_cause="The same subject or session was already imported with different "
            "data; raw data is never overwritten.",
            suggested_action="Import into a new workspace, or rename the subject in the source.",
        )

    # -- writing ---------------------------------------------------------------------------------
    raw_root.mkdir(exist_ok=True)
    created: list[Path] = []
    try:
        for rel in todo:
            target = raw_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(subject_files.get(rel) or other[rel], target)
            created.append(target)
            target.chmod(target.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
            summary.written.append(f"rawbids/{rel}")
        for rel, src in top.items():
            target = raw_root / rel
            if rel == "participants.tsv":
                current = target.read_text() if target.exists() else None
                text = merge_participants(current, src.read_text())
                if current != text:
                    target.write_text(text)
                    summary.written.append("rawbids/participants.tsv")
                else:
                    summary.in_place.append("rawbids/participants.tsv")
            elif not target.exists():
                shutil.copy2(src, target)
                target.chmod(target.stat().st_mode | stat.S_IWUSR)
                summary.written.append(f"rawbids/{rel}")
            elif sha256_of(target) == sha256_of(src):
                summary.in_place.append(f"rawbids/{rel}")
            else:
                summary.kept.append(f"rawbids/{rel}")
                summary.notes.append(
                    f"rawbids/{rel} already exists and differs from the source's; the existing "
                    "file was kept."
                )
    except BaseException:
        for path in created:  # nothing half-imported is left behind
            path.chmod(0o644)
            path.unlink(missing_ok=True)
        raise

    # -- registering -----------------------------------------------------------------------------
    subjects = sorted({rel.split("/")[0] for rel in subject_files})
    summary.subjects = subjects
    ids = {s: ws.get_or_create_subject(s) for s in subjects}
    organized: dict[str, dict[str, str]] = {s: {} for s in subjects}
    for rel in subject_files:  # hash first: hashing writes the cache, so not inside the transaction
        organized[rel.split("/")[0]][f"rawbids/{rel}"] = file_sha256(ws, f"rawbids/{rel}")
    with ws.session() as s:
        for rel in subject_files:
            relpath = f"rawbids/{rel}"
            sub = rel.split("/")[0]
            row = s.scalar(select(File).where(File.relpath == relpath))
            if row is None:
                s.add(File(subject_id=ids[sub], relpath=relpath, kind=_bids_kind(rel)))
            elif row.kind is None:
                row.subject_id, row.kind = ids[sub], _bids_kind(rel)
    fingerprint_src = hashlib.sha256()
    for rel in sorted(files):
        fingerprint_src.update(f"{rel}\0{files[rel].stat().st_size}\n".encode())
    fingerprint = fingerprint_src.hexdigest()[:16]
    existing = next(
        (
            m for m in list_manifests(ws)
            if m.source.kind == "bids" and m.source.fingerprint == fingerprint
        ),
        None,
    )  # fmt: skip
    if existing is not None:
        return BidsImport(existing, summary, False, report)
    manifest = ImportManifest(
        id=next_manifest_id(ws),
        source=SourceInfo(
            name=source.name, kind="bids", n_files=len(files), fingerprint=fingerprint,
        ),
        organized={f"bids:{s}": OrganizedSeries(files=fl) for s, fl in organized.items()},
        organize_notes=list(summary.notes),
        tool_versions={"bids_version": str(description.get("BIDSVersion", "unknown"))},
    )  # fmt: skip
    save_manifest(ws, manifest)
    return BidsImport(manifest, summary, True, report)


def format_bids_import(result: BidsImport) -> str:
    s = result.summary
    lines = [
        f"{result.manifest.id}: BIDS dataset '{result.manifest.source.name}': "
        f"{len(s.subjects)} subject(s), {result.manifest.source.n_files} files.",
        f"rawbids/: {len(s.written)} file(s) written, {len(s.in_place)} already in place.",
    ]
    lines += [f"  Note: {n}" for n in s.notes]
    report = result.source_report
    if report is not None and report.errors:  # warnings show up in the check afterwards
        lines += ["", "The source dataset was checked before copying:", format_report(report)]
    return "\n".join(lines)
