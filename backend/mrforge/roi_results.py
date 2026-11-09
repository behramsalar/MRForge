"""The ROI time series and correlation matrices of a workspace: one table, and an index file.

Every number comes from the records the steps wrote (``..._desc-roi.json`` of
``roi_timeseries`` and ``..._relmat.json`` of ``roi_correlation``); nothing is recomputed here
(principle 7). The index file lists, for each participant, recording and atlas, the full path of
every file, so that the researcher can arrange the matrices into groups for their own study (the
app has no group concept). Flags warn; they never leave anything out (principle 6); the only
option that leaves rows out is the researcher's own "leave out subjects I excluded" at export.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mrforge import qc_decisions
from mrforge.bids import parse_bids_name
from mrforge.workspace import Workspace

R_SUFFIX = "_stat-pearsoncorrelation_relmat"
Z_SUFFIX = "_stat-fisherz_relmat"


class RoiRow(BaseModel):
    """One recording of one subject (and session) for one atlas."""

    subject: str
    session: str | None
    recording: str  # "task-rest_run-1" ("" if the file name has no such parts)
    atlas: str  # the atlas id, e.g. "schaefer100n7"
    atlas_name: str
    regions: int
    volumes: int
    data: str  # "denoised" or "preproc": which data the series come from
    averaging: str  # how voxels were chosen
    mean_coverage: float | None  # mean share of a region's voxels that carry signal
    regions_low_coverage: int
    regions_without_values: int  # no voxel with signal: their rows and columns are 'nan'
    flags: list[str]  # warnings only
    decision: str | None
    decision_reason: str | None
    decision_who: str | None
    files: dict[str, str]  # workspace-relative: timeseries, pearson, fisherz, info, roi


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _location(ws: Workspace, record: Path) -> tuple[str, str | None]:
    parts = record.relative_to(ws.derivatives_dir).parts
    return parts[0], next((p for p in parts if p.startswith("ses-")), None)


def collect(ws: Workspace) -> list[RoiRow]:
    """Every correlation result in the workspace, ordered by subject, session, recording, atlas."""
    from mrforge import atlases

    rows: list[RoiRow] = []
    for info_path in sorted(ws.derivatives_dir.glob(f"sub-*/**/func/*{R_SUFFIX}.json")):
        if "_runs" in info_path.parts:
            continue
        info = _read(info_path)
        if info is None or "regions" not in info:
            continue
        stem = info_path.name.removesuffix(".json").removesuffix(R_SUFFIX)
        folder = info_path.parent
        files = {
            "timeseries": folder / f"{stem}_timeseries.tsv",
            "pearson": folder / f"{stem}{R_SUFFIX}.txt",
            "fisherz": folder / f"{stem}{Z_SUFFIX}.txt",
            "info": info_path,
            "roi": folder / f"{stem}_roi.json",
        }
        entities = parse_bids_name(info_path.name)[0]
        subject, session = _location(ws, info_path)
        atlas_id = entities.get("seg", "")
        try:
            atlas_name = atlases.get_atlas(atlas_id).name
        except atlases.AtlasError:
            atlas_name = atlas_id
        roi = _read(files["roi"]) or {}
        flags: list[str] = []
        missing = [k for k, p in files.items() if k != "roi" and not p.is_file()]
        if missing:
            flags.append(f"missing files: {', '.join(missing)}")
        if not roi:
            flags.append("the extraction record (desc-roi.json) is missing")
        low = int(roi.get("n_low_coverage", 0))
        empty = int(info.get("n_regions_without_values", 0))
        if low:
            share = float(roi.get("min_coverage", 0.5)) * 100
            flags.append(f"{low} region(s) have under {share:g}% of their voxels with signal")
        if empty:
            flags.append(f"{empty} region(s) have no usable signal ('nan' in the matrices)")
        decision = qc_decisions.current(ws, subject)
        recording = "_".join(
            f"{k}-{v}"
            for k, v in entities.items()
            if k not in ("sub", "ses", "space", "seg", "stat", "desc")
        )
        data_name = Path(str(info.get("input", ""))).name
        rows.append(
            RoiRow(
                subject=subject,
                session=session,
                recording=recording,
                atlas=atlas_id,
                atlas_name=atlas_name,
                regions=len(info["regions"]),
                volumes=int(info.get("volumes", 0)),
                data="denoised" if "desc-denoised" in data_name else "preproc",
                averaging=str(roi.get("signal_definition", "not recorded")),
                mean_coverage=roi.get("mean_coverage"),
                regions_low_coverage=low,
                regions_without_values=empty,
                flags=flags,
                decision=decision.decision if decision else None,
                decision_reason=decision.reason if decision else None,
                decision_who=decision.who if decision else None,
                files={k: ws.relpath(p) for k, p in files.items()},
            )
        )
    rows.sort(key=lambda r: (r.subject, r.session or "", r.recording, r.atlas))
    return rows


# -- the index file ----------------------------------------------------------------------------

INDEX_HEADER = [
    "subject", "session", "recording", "atlas", "atlas_name", "regions", "volumes", "data",
    "averaging", "mean_coverage", "regions_low_coverage", "regions_without_values",
    "qc_decision", "qc_reason", "flags",
    "pearson_matrix", "fisherz_matrix", "timeseries", "record",
]  # fmt: skip


def write_index(ws: Workspace, rows: list[RoiRow], path: Path) -> None:
    """The index: one line per recording and atlas, with the full paths of its files."""
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(INDEX_HEADER)
        for r in rows:
            full = {k: str(ws.abspath(p)) for k, p in r.files.items()}
            writer.writerow(
                [
                    r.subject, r.session or "", r.recording, r.atlas, r.atlas_name, r.regions,
                    r.volumes, r.data, r.averaging,
                    "" if r.mean_coverage is None else r.mean_coverage,
                    r.regions_low_coverage, r.regions_without_values,
                    r.decision or "", r.decision_reason or "", "; ".join(r.flags),
                    full["pearson"], full["fisherz"], full["timeseries"], full["info"],
                ]
            )  # fmt: skip
    tmp.replace(path)


def export(ws: Workspace, *, leave_out_excluded: bool = False) -> list[Path]:
    """Write the index into ``reports/roi/``; returns its path (a list, like the other exports)."""
    rows = collect(ws)
    if leave_out_excluded:
        rows = [r for r in rows if r.decision != "exclude"]
    folder = ws.root / "reports" / "roi"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    base, n = f"roi_matrices_{stamp}", 1
    while (folder / f"{base}.csv").exists():
        n += 1
        base = f"roi_matrices_{stamp}-{n}"
    path = folder / f"{base}.csv"
    write_index(ws, rows, path)
    return [path]


def list_exports(ws: Workspace) -> list[Path]:
    root = ws.root / "reports" / "roi"
    return sorted(root.glob("roi_matrices_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
