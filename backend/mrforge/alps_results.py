"""The ALPS results of a workspace: one table, and its export as CSV and Excel.

Every number comes from the ``alps.json`` that the ``alps_index`` step wrote (principle 7: nothing
is typed or recomputed here). Next to it the table shows the head motion of the same diffusion
series (from ``dwi_qc``) and the researcher's quality decision (Stage 7). Flags warn; they never
leave a subject out (principle 6). The only option that leaves rows out is the researcher's own
"leave out subjects I excluded" at export time, and the exclusions stay listed in the workbook.

The methods paragraph in the workbook is assembled from the recorded settings and versions with a
fixed template, never written by a language model.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel

from mrforge import qc_decisions
from mrforge.bids import parse_bids_name
from mrforge.steps.alps_rois import regions_text
from mrforge.workspace import Workspace

# REVIEW(domain): the same proposal as dwi_qc (mean volume-to-volume movement); a prompt to look,
# not a verdict.
MOTION_WARNING_MM = 1.0
REPOSITORY = "https://github.com/gbarisano/alps"
CITATION = (
    "Liu X, Barisano G, Shao X, et al. Cross-Vendor Test-Retest Validation of Diffusion Tensor "
    "Image Analysis along the Perivascular Space (DTI-ALPS) for Evaluating Glymphatic System "
    "Function. Aging and Disease 2023."
)  # the reference the script asks users to cite
ROI_ORIGIN = (
    "The four regions (left and right superior corona radiata and superior longitudinal "
    "fasciculus) are 2.5 mm spheres in JHU-ICBM-FA 1 mm space, distributed with alps.sh "
    "(G. Barisano, MIT licence)."
)
FORMULA = (
    "ALPS = mean(Dxx_proj, Dxx_assoc) / mean(Dyy_proj, Dzz_assoc), per side; "
    "the index is the mean of both sides."
)
ROI_KEYS = ("proj_L", "assoc_L", "proj_R", "assoc_R")
COMPONENT_KEYS = (
    "x_proj_L", "x_assoc_L", "y_proj_L", "z_assoc_L",
    "x_proj_R", "x_assoc_R", "y_proj_R", "z_assoc_R",
)  # fmt: skip


class AlpsRow(BaseModel):
    """One diffusion series of one subject (and session)."""

    subject: str
    session: str | None
    series: str  # which diffusion series when a subject has several ("run-1", "" if one)
    regions: str  # the set of regions the index was measured in
    record: str  # workspace-relative alps.json
    scanner: str
    alps_L: float
    alps_R: float
    alps: float
    fa: float  # mean over the four regions
    md: float
    components: dict[str, float]
    fa_rois: dict[str, float]
    md_rois: dict[str, float]
    voxels: dict[str, int]
    settings: dict[str, str]
    versions: dict[str, str]
    notes: list[str]
    flags: list[str]  # notes + checks + motion; warnings only
    mean_movement_mm: float | None  # mean volume-to-volume movement (eddy), if eddy was used
    decision: str | None
    decision_reason: str | None
    decision_who: str | None


def _recording(name: str) -> str:
    """The BIDS name parts that tell diffusion series apart ("run-1", "acq-x"), else ""."""
    entities = parse_bids_name(name)[0]
    return "_".join(
        f"{k}-{v}" for k, v in entities.items() if k not in ("sub", "ses", "desc", "space")
    )


def _desc(name: str) -> str:
    m = re.search(r"desc-([A-Za-z0-9]+)", name)
    return m.group(1) if m else ""


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _location(ws: Workspace, record: Path) -> tuple[str, str | None]:
    parts = record.relative_to(ws.derivatives_dir).parts
    session = next((p for p in parts if p.startswith("ses-")), None)
    return parts[0], session


def _movement(record: Path, series: str) -> float | None:
    for path in record.parent.glob("*_qc.json"):
        if _desc(path.name).startswith("dwimetrics") and _recording(path.name) == series:
            metrics = _read(path)
            value = metrics.get("mean_rms_previous_mm") if metrics else None
            return float(value) if isinstance(value, int | float) else None
    return None


def collect(ws: Workspace) -> list[AlpsRow]:
    """Every ALPS result in the workspace, ordered by subject, session and series."""
    rows: list[AlpsRow] = []
    for path in sorted(ws.derivatives_dir.glob("sub-*/**/dwi/*_alps.json")):
        if "_runs" in path.parts:
            continue
        data = _read(path)
        if data is None or "alps" not in data:
            continue
        subject, session = _location(ws, path)
        series = _recording(path.name)
        movement = _movement(path, series)
        flags = [*map(str, data.get("checks", [])), *map(str, data.get("notes", []))]
        if movement is not None and movement > MOTION_WARNING_MM:
            flags.append(
                f"mean movement between volumes is {movement:.2f} mm "
                f"(above {MOTION_WARNING_MM:g} mm)"
            )
        decision = qc_decisions.current(ws, subject)
        fa, md = data["fa"], data["md"]
        rows.append(
            AlpsRow(
                subject=subject,
                session=session,
                series=series,
                # results made before region sets were told apart store the source name ("default")
                regions=regions_text(str(data.get("settings", {}).get("regions", "not recorded"))),
                record=ws.relpath(path),
                scanner=str(data.get("scanner", "")),
                alps_L=data["alps_L"],
                alps_R=data["alps_R"],
                alps=data["alps"],
                fa=(fa["mean_proj"] + fa["mean_assoc"]) / 2,
                md=(md["mean_proj"] + md["mean_assoc"]) / 2,
                components=data["components"],
                fa_rois={k: fa[k] for k in ROI_KEYS},
                md_rois={k: md[k] for k in ROI_KEYS},
                voxels=data.get("voxels", {}),
                settings={k: str(v) for k, v in data.get("settings", {}).items()},
                versions={k: str(v) for k, v in data.get("versions", {}).items()},
                notes=[str(n) for n in data.get("notes", [])],
                flags=flags,
                mean_movement_mm=movement,
                decision=decision.decision if decision else None,
                decision_reason=decision.reason if decision else None,
                decision_who=decision.who if decision else None,
            )
        )
    rows.sort(key=lambda r: (r.subject, r.session or "", r.series, r.regions))
    return rows


# -- export ----------------------------------------------------------------------------------

SUMMARY_HEADER = [
    "subject", "session", "series", "regions", "ALPS", "ALPS left", "ALPS right",
    "FA (mean of regions)", "MD (mean of regions)", "mean movement (mm)",
    "QC decision", "QC reason", "flags",
]  # fmt: skip


def _summary_cells(r: AlpsRow) -> list[Any]:
    return [
        r.subject, r.session or "", r.series, r.regions, r.alps, r.alps_L, r.alps_R, r.fa, r.md,
        r.mean_movement_mm, r.decision or "", r.decision_reason or "", "; ".join(r.flags),
    ]  # fmt: skip


def methods_paragraph(rows: list[AlpsRow]) -> str:
    """A fixed-template description of what was done, from the recorded settings."""
    if not rows:
        return "No ALPS results are recorded."
    first = rows[0]
    s = first.settings
    v = first.versions
    same = all(r.settings == s for r in rows)
    parts = [
        f"The diffusion-tensor analysis along the perivascular space (DTI-ALPS) was computed for "
        f"{len(rows)} diffusion series with MRForge, a port of alps.sh (Barisano, MIT licence).",
        f"Preprocessing: {s.get('preprocessing', 'not recorded')}; distortion correction: "
        f"{s.get('distortion correction', 'not recorded')}; eddy-current and motion correction: "
        f"{s.get('eddy', 'not recorded')}.",
        f"Tensors were fitted with FSL dtifit. Space: {s.get('registration', 'not recorded')} "
        f"(template: {s.get('template', 'not recorded')}; tensor transform: "
        f"{s.get('tensor transform', 'not recorded')}); "
        f"regions: {s.get('regions', 'not recorded')}.",
        FORMULA,
    ]
    if not same:
        parts.append("The settings were not the same for every series; see the Settings sheet.")
    versions = ", ".join(f"{k} {x}" for k, x in v.items() if k != "mrforge_step")
    if versions:
        parts.append(f"Software: {versions}.")
    return " ".join(parts)


def _fmt(value: Any) -> Any:
    return "" if value is None else value


def write_csv(rows: list[AlpsRow], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(SUMMARY_HEADER)
        for r in rows:
            w.writerow([repr(c) if isinstance(c, float) else _fmt(c) for c in _summary_cells(r)])


def _sheet(wb: Workbook, title: str, header: list[str], body: list[list[Any]], first: bool) -> None:
    ws = wb.active if first else wb.create_sheet()
    assert ws is not None
    ws.title = title
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="F3E5C8")
    for line in body:
        ws.append([_fmt(c) for c in line])
    ws.freeze_panes = "A2"
    for i, name in enumerate(header, start=1):
        width = max([len(str(name))] + [len(str(line[i - 1])) for line in body if len(line) >= i])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)


def write_xlsx(rows: list[AlpsRow], path: Path, *, left_out: list[str], created: str) -> None:
    wb = Workbook()
    _sheet(wb, "Summary", SUMMARY_HEADER, [_summary_cells(r) for r in rows], True)
    flagged = PatternFill("solid", fgColor="FBE3E0")
    summary = wb["Summary"]
    for i, r in enumerate(rows, start=2):
        if r.flags:
            for cell in summary[i]:
                cell.fill = flagged

    ident = ["subject", "session", "series", "regions"]
    _sheet(
        wb,
        "ROI diffusivities",
        [*ident, *COMPONENT_KEYS],
        [
            [
                r.subject,
                r.session or "",
                r.series,
                r.regions,
                *[r.components[k] for k in COMPONENT_KEYS],
            ]
            for r in rows
        ],
        False,
    )
    famd_header = [*ident]
    for m in ("FA", "MD"):
        famd_header += [f"{m} {k}" for k in ROI_KEYS]
    _sheet(
        wb,
        "FA & MD",
        famd_header,
        [
            [r.subject, r.session or "", r.series, r.regions]
            + [r.fa_rois[k] for k in ROI_KEYS]
            + [r.md_rois[k] for k in ROI_KEYS]
            for r in rows
        ],
        False,
    )
    keys = sorted({k for r in rows for k in r.settings})
    vkeys = sorted({k for r in rows for k in r.versions})
    _sheet(
        wb,
        "Settings & versions",
        [*ident, "scanner", *keys, *vkeys, *[f"voxels {k}" for k in ROI_KEYS]],
        [
            [r.subject, r.session or "", r.series, r.regions, r.scanner]
            + [r.settings.get(k, "") for k in keys]
            + [r.versions.get(k, "") for k in vkeys]
            + [r.voxels.get(k, "") for k in ROI_KEYS]
            for r in rows
        ],
        False,
    )
    _sheet(
        wb,
        "Flags & notes",
        [*ident, "kind", "text"],
        [
            [r.subject, r.session or "", r.series, r.regions, "flag" if t in r.flags else "note", t]
            for r in rows
            for t in dict.fromkeys([*r.flags, *r.notes])
        ],
        False,
    )
    about = [
        ["Created", created],
        ["Table", "One row per diffusion series. Numbers are the recorded values (alps.json)."],
        ["Formula", FORMULA],
        ["Methods", methods_paragraph(rows)],
        ["Regions", ROI_ORIGIN],
        ["Please cite", CITATION],
        ["Original script", REPOSITORY],
        ["Flags", "Flags warn only. No subject is left out unless you chose to when exporting."],
        ["Left out at export", ", ".join(left_out) if left_out else "nobody"],
    ]
    _sheet(wb, "About", ["", ""], about, False)
    about_sheet = wb["About"]
    about_sheet.column_dimensions["B"].width = 110
    for line in about_sheet.iter_rows(min_row=2):
        line[1].alignment = Alignment(wrap_text=True, vertical="top")
    tmp = path.with_suffix(".tmp")
    wb.save(tmp)
    tmp.replace(path)


def export(ws: Workspace, *, leave_out_excluded: bool = False) -> list[Path]:
    """Write the CSV and Excel files into ``reports/alps/``; returns both paths."""
    rows = collect(ws)
    left_out: list[str] = []
    if leave_out_excluded:
        kept = [r for r in rows if r.decision != "exclude"]
        left_out = sorted({r.subject for r in rows if r.decision == "exclude"})
        rows = kept
    folder = ws.root / "reports" / "alps"
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    base, n = f"alps_results_{stamp}", 1
    while (folder / f"{base}.csv").exists() or (folder / f"{base}.xlsx").exists():
        n += 1
        base = f"alps_results_{stamp}-{n}"
    csv_path, xlsx_path = folder / f"{base}.csv", folder / f"{base}.xlsx"
    write_csv(rows, csv_path)
    write_xlsx(rows, xlsx_path, left_out=left_out, created=now.isoformat(timespec="seconds"))
    return [csv_path, xlsx_path]


def list_exports(ws: Workspace) -> list[Path]:
    root = ws.root / "reports" / "alps"
    files = [*root.glob("alps_results_*.csv"), *root.glob("alps_results_*.xlsx")]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
