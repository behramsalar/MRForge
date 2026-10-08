"""The report as one self-contained HTML file (pictures inside, no outside requests, printable).

The same ``SubjectReport`` the screen shows is rendered here, with the researcher's picture
layout (order, size, hidden) applied. The saved file is a snapshot: it never changes afterwards.
"""

from __future__ import annotations

import base64
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from mrforge.report import ReportQc, ReportRun, SubjectReport
from mrforge.workspace import Workspace

Size = Literal["s", "m", "l"]
TILE_WIDTH = {"s": "110px", "m": "190px", "l": "300px"}  # single slices
WIDE_WIDTH = {"s": "40%", "m": "70%", "l": "100%"}  # joined pictures


class LayoutItem(BaseModel):
    image: str  # workspace-relative path of the picture (single slice or joined picture)
    hidden: bool = False
    size: Size = "m"


class ReportLayout(BaseModel):
    """The order of the pictures (first = first shown) and, per picture, size and hidden."""

    items: list[LayoutItem] = []


def _pictures(qc: ReportQc, layout: ReportLayout) -> list[tuple[str, LayoutItem, bool]]:
    """The pictures of one QC item with the layout applied: (path, settings, is_single_slice).
    Single slices are used when they were kept; otherwise the joined picture."""
    chosen = {i.image: i for i in layout.items}
    order = {i.image: n for n, i in enumerate(layout.items)}
    if qc.slices:
        paths = [s.image for s in qc.slices]
        wide = False
    elif qc.image:
        paths, wide = [qc.image], True
    else:
        return []
    paths = sorted(paths, key=lambda p: order.get(p, len(order)))  # stable: unknown keep order
    out = []
    for p in paths:
        item = chosen.get(p) or LayoutItem(image=p, size="l" if wide else "m")
        if not item.hidden:
            out.append((p, item, wide))
    return out


def _data_uri(ws: Workspace, rel: str) -> str | None:
    path = ws.abspath(rel)
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value))


CSS = """
body{font:15px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:1000px;padding:0 1rem;color:#222}
h1{margin-bottom:.2rem} h2{margin-top:2.2rem;border-bottom:1px solid #ccc;padding-bottom:.2rem}
h3{margin:1.4rem 0 .3rem} table{border-collapse:collapse;margin:.4rem 0}
td,th{border:1px solid #ddd;padding:.25rem .6rem;text-align:left;vertical-align:top}
.muted{color:#666;font-size:.9em} .warn{background:#fff4d6;padding:.3rem .6rem;border-radius:4px}
.tiles{display:flex;flex-wrap:wrap;gap:6px;background:#000;padding:6px;border-radius:4px}
.tiles img,.wide{display:block;background:#000;border-radius:3px}
pre{background:#f5f5f5;padding:.5rem;overflow:auto;font-size:.85em}
details{margin:.3rem 0} .notrun{color:#777}
@media print{details{display:block} body{margin:0}}
"""


def _run_html(ws: Workspace, run: ReportRun, layout: ReportLayout) -> str:
    title = f"{_e(run.title)} <span class='muted'>{_e(run.recording)}</span>"
    parts = [f"<h3>{title}</h3>"]
    when = f"{_e(run.started)} to {_e(run.finished)}"
    by = f", started by {_e(run.started_by)}" if run.started_by else ""
    parts.append(f"<p class='muted'>Step version {_e(run.step_version)}, ran {when}{by}.</p>")
    metrics = [q for q in run.qc if q.kind == "metric"]
    if metrics:
        rows = "".join(f"<tr><th>{_e(q.name)}</th><td>{_e(q.value)}</td></tr>" for q in metrics)
        parts.append(f"<table>{rows}</table>")
    for q in run.qc:
        if q.kind == "metric":
            continue
        pics = _pictures(q, layout)
        if not pics:
            continue
        parts.append(f"<p><strong>{_e(q.name)}</strong></p>")
        if pics[0][2]:  # a joined picture
            for path, item, _ in pics:
                uri = _data_uri(ws, path)
                if uri:
                    parts.append(
                        f"<img class='wide' alt='{_e(q.name)}' src='{uri}' "
                        f"style='width:{WIDE_WIDTH[item.size]}'>"
                    )
        else:
            tiles = []
            for path, item, _ in pics:
                uri = _data_uri(ws, path)
                if uri:
                    tiles.append(f"<img alt='' src='{uri}' style='width:{TILE_WIDTH[item.size]}'>")
            parts.append(f"<div class='tiles'>{''.join(tiles)}</div>")
    for w in run.warnings:
        parts.append(f"<p class='warn'>{_e(w)}</p>")
    params = json.dumps(run.parameters, indent=2, default=str)
    cmds = "\n".join(f"{c.command}    # exit code {c.return_code}" for c in run.commands)
    parts.append(
        f"<details><summary>Parameters and commands</summary><pre>{_e(params)}</pre>"
        f"<pre>{_e(cmds) or 'No external command was recorded.'}</pre>"
        f"<p class='muted'>{run.inputs} input and {run.outputs} output files, with hashes, are "
        f"in {_e(run.run_dir)}/provenance.json</p></details>"
    )
    return "".join(parts)


def render_html(ws: Workspace, report: SubjectReport, layout: ReportLayout | None = None) -> str:
    layout = layout or ReportLayout()
    body = [
        f"<h1>Processing report: {_e(report.subject)}</h1>",
        f"<p class='muted'>Generated {_e(report.generated)} by MRForge "
        f"{_e(report.mrforge_version)} from the recorded processing history. Nothing in this "
        "report is estimated: every figure is a recorded one.</p>",
    ]
    if report.decisions:
        body.append(
            "<h2>Quality decision</h2><table><tr><th>Decision</th><th>Reason</th>"
            "<th>By</th><th>When</th></tr>"
        )
        for d in reversed(report.decisions):
            body.append(
                f"<tr><td>{_e(d.decision)}</td><td>{_e(d.reason)}</td>"
                f"<td>{_e(d.who or 'unknown')}</td><td>{_e(d.when)}</td></tr>"
            )
        body.append("</table>")
    if report.warnings:
        body.append("<h2>Warnings</h2>")
        body.extend(f"<p class='warn'>{_e(w)}</p>" for w in report.warnings)
    body.append("<h2>Acquisition</h2>")
    if report.acquisition:
        body.append(
            "<table><tr><th>Series</th><th>Description</th><th>Imported as</th><th>Size</th>"
            "<th>Volumes</th><th>TR (s)</th><th>TE (s)</th><th>Session</th></tr>"
        )
        for a in report.acquisition:
            body.append(
                f"<tr><td>{_e(a.number)}</td><td>{_e(a.description)}</td><td>{_e(a.kind)}</td>"
                f"<td>{_e(a.matrix)}</td><td>{_e(a.volumes)}</td>"
                f"<td>{_e(a.repetition_time_s)}</td><td>{_e(a.echo_time_s)}</td>"
                f"<td>{_e(a.session)}</td></tr>"
            )
        body.append("</table>")
    else:
        body.append("<p class='muted'>No imported series are recorded for this subject.</p>")
    for section in report.sections:
        body.append(f"<h2>{_e(section.title)}</h2>")
        body.extend(_run_html(ws, run, layout) for run in section.runs)
        if section.not_run:
            body.append("<p class='notrun'>Not run: " + _e(", ".join(section.not_run)) + "</p>")
    body.append("<h2>Software</h2><table>")
    body.extend(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in report.software.items())
    body.append("</table>")
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Processing report {_e(report.subject)}</title><style>{CSS}</style></head>"
        f"<body>{''.join(body)}</body></html>"
    )


def reports_dir(ws: Workspace, subject: str) -> Path:
    return ws.root / "reports" / subject


def export_report(ws: Workspace, report: SubjectReport, layout: ReportLayout) -> Path:
    """Write the report (and the layout it used) into ``reports/<subject>/``."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    folder = reports_dir(ws, report.subject)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{report.subject}_report_{stamp}.html"
    n = 1
    while target.exists():  # two exports in the same second
        n += 1
        target = folder / f"{report.subject}_report_{stamp}-{n}.html"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(render_html(ws, report, layout), encoding="utf-8")
    tmp.replace(target)
    target.with_suffix(".layout.json").write_text(layout.model_dump_json(indent=2) + "\n")
    return target


def list_exports(ws: Workspace, subject: str | None = None) -> list[Path]:
    root = ws.root / "reports"
    pattern = f"{subject}/*_report_*.html" if subject else "*/*_report_*.html"
    return sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)


def latest_layout(ws: Workspace, subject: str) -> ReportLayout:
    for page in list_exports(ws, subject):
        layout_file = page.with_suffix(".layout.json")
        if layout_file.is_file():
            try:
                return ReportLayout.model_validate_json(layout_file.read_text())
            except ValueError:
                continue
    return ReportLayout()
