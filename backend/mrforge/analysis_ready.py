"""The analysis-ready files: the final result of each recording, in one folder, for group work.

``derivatives/<app>/analysis-ready/`` holds one link per recording to its final image (the
standard-space result) under a name with a fixed pattern (``..._desc-final_bold``), plus the
subject's standard-space brain mask, and a manifest (``analysis-ready.tsv`` / ``.json``) that
says which processing produced each file. The files themselves keep their descriptive names;
what counts as "final" can move when later stages are added, and then the links move, nothing is
renamed. The manifest also shows whether a group mixes files made with different settings,
which is the thing to avoid in a group analysis.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mrforge.provenance import PROVENANCE_FILENAME, Provenance
from mrforge.qc_decisions import current as current_decision
from mrforge.workspace import Workspace

FOLDER = "analysis-ready"
MANIFEST = "analysis-ready"


class ReadyRow(BaseModel):
    subject: str
    recording: str
    file: str  # the analysis-ready link (workspace-relative)
    mask: str | None  # the standard-space brain mask (a link as well)
    source: str  # the real file the link points to
    settings: dict[str, str]  # what was done, in plain words
    decided_by: str | None
    finished: datetime | None
    excluded: bool = False  # the researcher excluded this subject: no link, listed with the reason
    qc_decision: str | None = None
    qc_reason: str | None = None


class Difference(BaseModel):
    setting: str
    groups: dict[str, list[str]]  # value -> subjects that have it


class ReadyReport(BaseModel):
    folder: str
    manifest: str
    rows: list[ReadyRow]
    differences: list[Difference]  # empty: every file was made the same way


def _prov(path: Path) -> Provenance | None:
    try:
        return Provenance.model_validate_json(path.read_text())
    except (OSError, ValueError):
        return None


def _settings(runs: Path, recording: str, bold_input: str) -> tuple[dict[str, str], str | None]:
    """What was done to one recording, read from the records of its steps."""
    out: dict[str, str] = {}
    who: str | None = None
    feat = _prov(runs / f"feat_preproc_{recording}" / PROVENANCE_FILENAME)
    if feat:
        p = feat.parameters
        out["Volumes discarded"] = str(p.get("delete_volumes"))
        out["Smoothing (mm)"] = str(p.get("smoothing_fwhm_mm"))
        out["Slow-drift filter (s)"] = str(p.get("highpass_cutoff_s") or "off")
        out["Slice timing"] = "on" if p.get("slice_timing") else "off"
        out["Distortion correction"] = (
            "fieldmap" if any("fieldmap" in f.path for f in feat.inputs) else "none"
        )
        out["Registration"] = str(p.get("registration_dof"))
    if "desc-denoised" in bold_input.rsplit("/", 1)[-1]:
        labels = next(iter(sorted(runs.parent.glob(f"ica/*{recording}*_labels.json"))), None)
        info: dict[str, Any] = {}
        if labels:
            try:
                info = json.loads(labels.read_text())
            except (OSError, ValueError):
                info = {}
        who = info.get("decided_by")
        out["Noise removal"] = (
            "ICA-AROMA (automatic)" if info.get("source") == "aroma" else "labelled by hand"
        )
        reg = _prov(runs / f"regfilt_{recording}" / PROVENANCE_FILENAME)
        out["Removal mode"] = (
            "aggressive" if reg and reg.parameters.get("aggressive") else "partial"
        )
        out["Uncertain components"] = f"kept as {info.get('uncertain_treated_as', 'signal')}"
    else:
        out["Noise removal"] = "none"
    mni = _prov(runs / f"func_to_mni_{recording}" / PROVENANCE_FILENAME)
    if mni:
        out["Standard space (mm)"] = str(mni.parameters.get("resolution_mm"))
        out["Interpolation"] = str(mni.parameters.get("interpolation"))
    return out, who


def _final_link(name: str) -> str:
    for ending in ("_desc-denoised_bold.nii.gz", "_desc-preproc_bold.nii.gz"):
        if name.endswith(ending):
            return name.removesuffix(ending) + "_desc-final_bold.nii.gz"
    return name


def _relative_link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(os.path.relpath(target, link.parent))


def refresh(ws: Workspace) -> ReadyReport:
    """Recompute the folder and the manifest from what has been processed."""
    base = ws.derivatives_dir
    folder = base / FOLDER
    rows: list[ReadyRow] = []
    wanted: set[Path] = set()
    for record in sorted(base.glob("sub-*/**/func/_runs/func_to_mni_*/" + PROVENANCE_FILENAME)):
        prov = _prov(record)
        if prov is None or prov.status != "Completed":
            continue
        image = next(
            (
                o.path
                for o in prov.outputs
                if o.path.endswith("_bold.nii.gz") and "space-" in o.path
            ),
            None,
        )
        mask = next(
            (
                o.path
                for o in prov.outputs
                if o.path.endswith("_mask.nii.gz") and "space-" in o.path
            ),
            None,
        )
        if image is None or not ws.abspath(image).is_file():
            continue
        runs = record.parent.parent
        recording = record.parent.name.removeprefix("func_to_mni_")
        bold_input = next((f.path for f in prov.inputs if f.path.endswith("_bold.nii.gz")), "")
        settings, who = _settings(runs, recording, bold_input)
        decision = current_decision(ws, prov.subject)
        if decision is not None and decision.decision == "exclude":
            rows.append(
                ReadyRow(
                    subject=prov.subject,
                    recording=recording,
                    file="",
                    mask=None,
                    source=image,
                    settings=settings,
                    decided_by=who,
                    finished=prov.finished,
                    excluded=True,
                    qc_decision="exclude",
                    qc_reason=decision.reason,
                )
            )
            continue
        link = folder / _final_link(image.rsplit("/", 1)[-1])
        _relative_link(link, ws.abspath(image))
        wanted.add(link)
        mask_link = None
        if mask and ws.abspath(mask).is_file():
            mask_path = folder / mask.rsplit("/", 1)[-1]
            _relative_link(mask_path, ws.abspath(mask))
            wanted.add(mask_path)
            mask_link = str(mask_path.relative_to(ws.root))
        rows.append(
            ReadyRow(
                subject=prov.subject,
                recording=recording,
                file=str(link.relative_to(ws.root)),
                mask=mask_link,
                source=image,
                settings=settings,
                decided_by=who,
                finished=prov.finished,
                qc_decision=decision.decision if decision else None,
                qc_reason=decision.reason if decision else None,
            )
        )
    if folder.is_dir():
        for stale in folder.iterdir():
            if stale not in wanted and (stale.is_symlink() or stale.suffix == ".gz"):
                stale.unlink()
    report = ReadyReport(
        folder=ws.relpath(folder),
        manifest=ws.relpath(folder / f"{MANIFEST}.tsv"),
        rows=rows,
        differences=_differences([r for r in rows if not r.excluded]),
    )
    _write_manifest(ws, folder, report)
    return report


def _differences(rows: list[ReadyRow]) -> list[Difference]:
    keys = sorted({k for r in rows for k in r.settings})
    out: list[Difference] = []
    only_with_denoising = ("Removal mode", "Uncertain components")  # compared only where they apply
    for key in keys:
        groups: dict[str, list[str]] = {}
        for r in rows:
            if key in only_with_denoising and key not in r.settings:
                continue
            groups.setdefault(r.settings.get(key, "-"), []).append(
                f"{r.subject} {r.recording}".strip()
            )
        if len(groups) > 1:
            out.append(Difference(setting=key, groups=groups))
    return out


def _write_manifest(ws: Workspace, folder: Path, report: ReadyReport) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in report.rows for k in r.settings})
    with (folder / f"{MANIFEST}.tsv").open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            ["subject", "recording", "file", "mask", "source", *keys, "decided_by", "finished"]
        )
        for r in report.rows:
            writer.writerow(
                [r.subject, r.recording, r.file, r.mask or "", r.source]
                + [r.settings.get(k, "") for k in keys]
                + [r.decided_by or "", r.finished.isoformat() if r.finished else ""]
                + [r.qc_decision or "", r.qc_reason or "", "excluded" if r.excluded else "included"]
            )
    (folder / f"{MANIFEST}.json").write_text(report.model_dump_json(indent=2) + "\n")
