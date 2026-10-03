"""Convert the series that are set to be imported from DICOM to NIfTI with dcm2niix.

Design (checked against ``dcm2niix -h`` and the real session, dcm2niix v1.0.20260724):
  * dcm2niix's ``-n`` series filter is unreliable for some series (a fieldmap phase series
    converts to nothing), so each series is converted from its own temporary folder of
    hard links with neutral file names. That converts only what is needed, allows a retry
    per series, and keeps folder names from the source (which can hold a patient's name)
    away from dcm2niix, its messages and our logs.
  * ``-b y -ba y``: BIDS sidecar with dates and personal information removed;
    ``-z y``: gzip (uses pigz if present, else dcm2niix's own compressor); ``-f %s``: files are
    named after the series number.
  * Results go to ``<workspace>/imports/import-NNN/converted/s<number>/`` (not to rawbids/,
    which the BIDS organizer fills in the next step) and are checked against the scan.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from nibabel.loadsave import load as load_image
from nibabel.nifti1 import Nifti1Header

from mrforge.errors import StepError
from mrforge.hashing import file_sha256
from mrforge.importing.classify import RuleSet, effective_all
from mrforge.importing.manifest import manifest_dir, save_manifest
from mrforge.importing.models import (
    Classification,
    CommandRecord,
    Conversion,
    ConvertedImage,
    DicomSeries,
    ImportManifest,
)
from mrforge.importing.scan import _dcm2niix_version, index_files
from mrforge.workspace import Workspace

OUTPUT_NAME = re.compile(r"(\d+)(?:_(.+?))?\.nii\.gz")
LOG_TAIL_LINES = 12


@dataclass
class ConvertSummary:
    converted: list[int] = field(default_factory=list)
    up_to_date: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)


def _label(series: DicomSeries) -> str:
    return f"series {series.number} ({series.label})"


def converted_dir(ws: Workspace, manifest: ImportManifest, series: DicomSeries) -> Path:
    return manifest_dir(ws, manifest.id) / "converted" / f"s{series.number}"


def scrub(text: str, dicom_dir: Path) -> str:
    """Remove source paths from tool output (folder names in a source can identify a person)."""
    return re.sub(re.escape(str(dicom_dir)) + r"\S*", "<dicom>", text)


def stage_files(files: list[Path], dest: Path) -> None:
    """Hard-link (or copy) a series' files into ``dest`` under neutral names."""
    dest.mkdir(parents=True, exist_ok=True)
    for i, source in enumerate(sorted(files)):
        target = dest / f"f{i:06d}"
        try:
            os.link(source, target)
        except OSError:  # a different disk, or links not allowed
            shutil.copy2(source, target)


# -- checking the result against the scan ---------------------------------------------------------


def _spatial(series: DicomSeries) -> list[int] | None:
    dims = [series.columns, series.rows, series.slices]
    return None if any(d is None for d in dims) else sorted(d for d in dims if d is not None)


# dcm2niix tags for images the scanner calculated from the data. They are not raw data: they
# are left out of rawbids/ (they stay in the converted folder).
DERIVED_SUFFIXES = {"ADC", "Trace", "FA", "ColFA"}
STOPPED_EARLY = "do not fill whole volumes"


def check_image(
    ws: Workspace,
    series: DicomSeries,
    kind: str,
    image: ConvertedImage,
    removed_ok: bool = False,
) -> tuple[list[str], list[str]]:
    """(problems, warnings) for one converted image. ``removed_ok`` allows the image to have
    one or two volumes fewer than the scan counted: dcm2niix takes scanner-calculated volumes
    (ADC, trace) out of a diffusion series and writes the complete data to a separate file."""
    problems: list[str] = []
    warnings: list[str] = []
    what = f"image '{image.suffix or 'main'}' of {_label(series)}"
    spatial = sorted(image.shape[:3])
    volumes = image.shape[3] if len(image.shape) > 3 else 1
    expected = _spatial(series)
    if expected is None:
        warnings.append(f"The size of {what} could not be compared (the scan has no size).")
    elif spatial != expected:
        # dcm2niix may reorder axes (for example sagittal scans), so only the set of sizes counts
        problems.append(
            f"The converted {what} has size {'x'.join(map(str, image.shape[:3]))}, but the scan "
            f"says {series.matrix} (the order of the axes may differ)."
        )
    if series.volumes is not None and volumes != series.volumes:
        missing = series.volumes - volumes
        if removed_ok and 1 <= missing <= 2:
            warnings.append(
                f"{what.capitalize()} has {volumes} volume(s); dcm2niix removed {missing} "
                f"scanner-calculated volume(s) (ADC or trace) from the {series.volumes} found."
            )
        else:
            problems.append(
                f"The converted {what} has {volumes} volume(s), but the scan found "
                f"{series.volumes}."
            )
    if kind == "dwi":
        if not (image.bval and image.bvec):
            problems.append(f"The diffusion directions (bval/bvec) of {what} are missing.")
        else:
            n_bvals = len(ws.abspath(image.bval).read_text().split())  # one per volume
            if n_bvals != volumes:
                problems.append(
                    f"{what} has {n_bvals} b-values for {volumes} volumes; they must match."
                )
    if image.sidecar is None:
        problems.append(f"The JSON sidecar of {what} is missing.")
    return problems, warnings


def _read_image(ws: Workspace, out_dir: Path, name: str) -> ConvertedImage:
    stem = name[: -len(".nii.gz")]
    suffix = OUTPUT_NAME.fullmatch(name)
    assert suffix is not None
    nifti = ws.relpath(out_dir / name)
    header = cast(Nifti1Header, load_image(out_dir / name).header)  # reads the header only
    companions = {
        "sidecar": out_dir / f"{stem}.json",
        "bval": out_dir / f"{stem}.bval",
        "bvec": out_dir / f"{stem}.bvec",
    }
    present = {k: ws.relpath(p) for k, p in companions.items() if p.is_file()}
    hashes = {p: file_sha256(ws, p) for p in [nifti, *present.values()]}
    return ConvertedImage(
        suffix=suffix.group(2) or "",
        nifti=nifti,
        shape=[int(x) for x in header.get_data_shape()],  # type: ignore[no-untyped-call]
        voxel_size_mm=[round(float(z), 4) for z in header.get_zooms()[:3]],  # type: ignore[no-untyped-call]
        sha256=hashes,
        **present,
    )


# -- converting ---------------------------------------------------------------------------------


def convert_series(
    ws: Workspace,
    manifest: ImportManifest,
    series: DicomSeries,
    classification: Classification,
    files: list[Path],
    exe: str,
    version: str,
) -> Conversion:
    """Convert one series. Never raises for data problems: they are recorded in the result."""
    dicom_dir = ws.root / manifest.dicom_dir
    out_dir = converted_dir(ws, manifest, series)
    shutil.rmtree(out_dir, ignore_errors=True)  # a retry starts clean
    out_dir.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="convert-", dir=manifest_dir(ws, manifest.id)))
    try:
        stage_files(files, scratch)
        argv = [exe, "-b", "y", "-ba", "y", "-z", "y", "-f", "%s", "-o", str(out_dir)]
        argv += ["-v", "0", str(scratch)]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    record = CommandRecord(
        argv=[
            a.replace(str(out_dir), "<converted>").replace(str(scratch), "<series>") for a in argv
        ],
        return_code=proc.returncode,
    )
    log = scrub((proc.stdout + proc.stderr).replace(str(scratch), "<series>"), dicom_dir)
    log_dir = manifest_dir(ws, manifest.id) / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / f"convert-s{series.number}.log").write_text(log)

    problems: list[str] = []
    warnings: list[str] = []
    images: list[ConvertedImage] = []
    names = sorted(p.name for p in out_dir.glob("*.nii.gz") if OUTPUT_NAME.fullmatch(p.name))
    if proc.returncode != 0:
        tail = " | ".join(log.strip().splitlines()[-LOG_TAIL_LINES:][-3:])
        problems.append(
            f"dcm2niix stopped with an error (exit code {proc.returncode}) while converting "
            f"{_label(series)}." + (f" Its last messages: {tail}" if tail else "")
        )
        if any(STOPPED_EARLY in w for w in series.warnings):
            problems.append(
                f"The scan already showed that {_label(series)} has slices that do not fill whole "
                "volumes. The acquisition was probably stopped early, and dcm2niix cannot convert "
                "incomplete volumes. Leave it out with "
                f"'mrforge import set {series.number} --skip'."
            )
    elif not names:
        problems.append(f"dcm2niix produced no image for {_label(series)}.")
    for name in names:
        try:
            images.append(_read_image(ws, out_dir, name))
        except Exception as exc:  # an unreadable result is a problem with this series only
            problems.append(f"The converted file {name} could not be read ({type(exc).__name__}).")
    derived = [i for i in images if i.suffix in DERIVED_SUFFIXES]
    images = [i for i in images if i.suffix not in DERIVED_SUFFIXES]
    for image in derived:
        warnings.append(
            f"dcm2niix separated a scanner-calculated '{image.suffix}' image from "
            f"{_label(series)}. It is not raw data and was left out; the rest of the series is "
            "imported."
        )
    if images:
        got = sorted(i.suffix for i in images)
        want = sorted(o.suffix for o in series.outputs if o.suffix not in DERIVED_SUFFIXES) or got
        if got != want:
            problems.append(
                f"{_label(series)} should give the images {want}, but dcm2niix wrote {got}."
            )
        for image in images:
            p, w = check_image(ws, series, classification.kind, image, removed_ok=bool(derived))
            problems += p
            warnings += w
    return Conversion(
        series_uid=series.uid,
        status="failed" if problems else "ok",
        images=images,
        command=record,
        tool_version=version,
        problems=problems,
        warnings=warnings,
    )


def is_up_to_date(ws: Workspace, conversion: Conversion | None, version: str) -> bool:
    """A finished conversion can be reused if every file is still there and unchanged."""
    if conversion is None or conversion.status != "ok" or conversion.tool_version != version:
        return False
    for image in conversion.images:
        for rel, digest in image.sha256.items():
            path = ws.abspath(rel)
            if not path.is_file() or file_sha256(ws, rel) != digest:
                return False
    return bool(conversion.images)


def convert_import(
    ws: Workspace,
    manifest: ImportManifest,
    rules: RuleSet,
    jobs: int | None = None,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> ConvertSummary:
    """Convert every series whose decision is "import". Finished series are not converted
    again; one failing series does not stop the others. The manifest is saved as it goes."""
    say = progress or (lambda _msg: None)
    exe = shutil.which("dcm2niix")
    if exe is None:
        raise StepError(
            code="TOOL_NOT_FOUND",
            message="The program 'dcm2niix' could not be found.",
            probable_cause="It is not installed or not on the path.",
            suggested_action="Run 'python scripts/check_env.py' to see what is missing.",
        )
    version = _dcm2niix_version(exe)
    plan = effective_all(manifest, rules)
    wanted = [s for s in manifest.series if plan[s.uid].action == "import"]
    numbers = [s.number for s in wanted]
    for s in wanted:
        if s.number is None or numbers.count(s.number) > 1:
            raise StepError(
                code="AMBIGUOUS_SERIES",
                message=f"Series number {s.number} is used by more than one series to import.",
                probable_cause="The scanner session contains repeated series numbers.",
                suggested_action="Split the session into folders and import them one by one.",
            )
    summary = ConvertSummary()
    todo: list[DicomSeries] = []
    for s in wanted:
        if not force and is_up_to_date(ws, manifest.conversions.get(s.uid), version):
            summary.up_to_date.append(s.number or 0)
        else:
            todo.append(s)
    if not todo:
        return summary
    if manifest.dicom_removed is not None or not (ws.root / manifest.dicom_dir).is_dir():
        raise StepError(
            code="DICOM_REMOVED",
            message="These series still need converting, but the DICOM files of this import "
            "were removed: " + ", ".join(str(s.number) for s in todo) + ".",
            probable_cause="The copy in sourcedata/ was deleted (mrforge import remove-dicom).",
            suggested_action="Restore it by scanning the original source again with the same "
            f"subject: mrforge import scan <original folder or zip> --subject {manifest.subject}",
        )
    say(f"Converting {len(todo)} series with dcm2niix ({len(summary.up_to_date)} already done)...")
    by_series = index_files(ws.root / manifest.dicom_dir)
    workers = max(1, min(jobs or 4, os.cpu_count() or 1, len(todo)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                convert_series, ws, manifest, s, plan[s.uid], by_series.get(s.uid, []), exe, version
            ): s
            for s in todo
        }
        for future in as_completed(futures):
            s = futures[future]
            result = future.result()
            manifest.conversions[s.uid] = result
            save_manifest(ws, manifest)
            (summary.converted if result.status == "ok" else summary.failed).append(s.number or 0)
            say(_result_line(s, result))
    summary.converted.sort()
    summary.failed.sort()
    return summary


def _result_line(series: DicomSeries, result: Conversion) -> str:
    if result.status == "ok":
        sizes = ", ".join("x".join(map(str, i.shape)) for i in result.images)
        return f"  {_label(series)}: converted ({sizes})"
    details = "".join(f"\n      - {p}" for p in result.problems)
    return f"  {_label(series)}: FAILED{details}"
