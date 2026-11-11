# ruff: noqa: E501
"""The report as one self-contained HTML file (pictures inside, no outside requests, printable).

The same ``SubjectReport`` the screen shows is rendered here, with the researcher's picture
layout (order, size, hidden) applied. The saved file is a snapshot: it never changes afterwards.
"""

from __future__ import annotations

import base64
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from mrforge.report import ReportQc, ReportRun, SubjectReport
from mrforge.workspace import Workspace

LAYER_NAMES = {
    "functional": "Functional image, white-matter boundary in red",
    "t1": "T1 image, edges of the functional image in red",
    "before": "Before distortion correction",
    "after": "After distortion correction",
    "mni": "Mean functional image, outline of the standard brain in red",
}


def _planes(qc: ReportQc) -> list[tuple[str, list[str]]]:
    """The single slices of one picture as (layer, [paths]) in reading order, grouped by plane
    inside a layer: sagittal, coronal, axial."""
    layers: dict[str, list[str]] = {}
    for sl in qc.slices:
        layers.setdefault(sl.layer, []).append(sl.image)
    return list(layers.items())


def _data_uri(ws: Workspace, rel: str) -> str | None:
    path = ws.abspath(rel)
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def _t(value: object) -> str:
    """A recorded time as 'YYYY-MM-DD HH:MM' (UTC), for reading."""
    text = "" if value is None else str(value)
    return html.escape(text[:16].replace("T", " ") + " UTC" if len(text) >= 16 else text)


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value))


CSS = """
:root{--ink:#1f2430;--mute:#667085;--line:#e3e6ec;--card:#fff;--bg:#f5f6f9;--accent:#4c5fd5;
--ok:#1a7f4b;--okbg:#e4f5ec;--warn:#8a5a00;--warnbg:#fff3d6;--bad:#a4242a;--badbg:#fde8e8}
*{box-sizing:border-box}
body{font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:var(--bg);color:var(--ink)}
main{max-width:1040px;margin:0 auto;padding:1.5rem 1rem 3rem}
header{display:flex;align-items:baseline;gap:.8rem;flex-wrap:wrap;margin-bottom:.2rem}
h1{font-size:1.6rem;margin:0} h2{font-size:1.15rem;margin:2rem 0 .7rem}
.muted{color:var(--mute);font-size:.88em}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:.9rem 1.1rem}
.decision{display:flex;gap:.8rem;align-items:center;flex-wrap:wrap}
.badge{display:inline-block;padding:.1rem .6rem;border-radius:999px;font-weight:600;font-size:.85em;
background:var(--warnbg);color:var(--warn)}
.badge.accept{background:var(--okbg);color:var(--ok)} .badge.exclude{background:var(--badbg);color:var(--bad)}
.warn{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:.5rem .8rem;margin:.5rem 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.6rem;margin:.7rem 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.5rem .8rem}
.stat b{display:block;font-size:1.15rem}
.checks{display:grid;grid-template-columns:repeat(2,1fr);gap:.9rem;margin-top:.9rem}
.checks .card h3{margin:0 0 .4rem;font-size:1rem}
.planes{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.plane{display:grid;grid-template-columns:repeat(2,1fr);gap:3px;background:#000;padding:3px;border-radius:6px;align-content:center}
.plane img{width:100%;display:block}
.wide{display:block;width:100%;background:#000;border-radius:6px}
table{border-collapse:collapse;margin:.4rem 0;width:100%}
td,th{border-bottom:1px solid var(--line);padding:.3rem .6rem;text-align:left;vertical-align:top}
th{color:var(--mute);font-weight:600}
details.fold{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:.45rem 0}
details.fold>summary{cursor:pointer;padding:.65rem 1rem;display:flex;gap:.7rem;align-items:center;list-style:none}
details.fold>summary::-webkit-details-marker{display:none}
details.fold>summary::before{content:"\u25B8";color:var(--mute)}
details.fold[open]>summary::before{content:"\u25BE"}
details.fold>summary .sum{margin-left:auto;color:var(--mute);font-size:.88em}
.body{padding:0 1rem 1rem}
.run{border-top:1px solid var(--line);padding-top:.7rem;margin-top:.7rem}
.run:first-child{border-top:0;margin-top:0;padding-top:0}
.run h3{font-size:1rem;margin:0 0 .2rem}
pre{background:#f1f2f6;padding:.5rem;overflow:auto;font-size:.82em;border-radius:6px}
.notrun{color:var(--mute)}
@media(max-width:760px){.checks,.planes{grid-template-columns:1fr}}
@media print{body{background:#fff} main{padding:0} details.fold{break-inside:avoid}}
"""

SCRIPT = "addEventListener('beforeprint',()=>document.querySelectorAll('details').forEach(d=>d.open=true))"

# The four checks shown first (same names as the on-screen report) and the head-motion numbers.
MAIN_CHECKS = [
    ("Head movement", re.compile(r"^Head motion")),
    ("Alignment to the T1", re.compile(r"^Registration to the T1")),
    ("Field map", re.compile(r"^Distortion correction")),
    ("Standard space", re.compile(r"^Alignment to standard space")),
]
NUMBERS = re.compile(r"^Head motion|framewise|volumes", re.IGNORECASE)


def _is_main_check(q: ReportQc) -> bool:
    return q.kind != "metric" and any(rx.match(q.name) for _, rx in MAIN_CHECKS)


def _pictures_html(ws: Workspace, q: ReportQc) -> str:
    parts: list[str] = []
    if q.slices:
        for layer, paths in _planes(q):
            cols = []
            for k in range(0, len(paths), 4):  # 4 slices per plane
                tiles = "".join(
                    f"<img alt='' src='{uri}'>"
                    for p in paths[k : k + 4]
                    if (uri := _data_uri(ws, p))
                )
                cols.append(f"<div class='plane'>{tiles}</div>")
            caption = _e(LAYER_NAMES.get(layer, layer))
            parts.append(f"<p class='muted'>{caption}</p><div class='planes'>{''.join(cols)}</div>")
    elif q.image and (uri := _data_uri(ws, q.image)):
        parts.append(f"<img class='wide' alt='{_e(q.name)}' src='{uri}'>")
    return "".join(parts)


def _run_html(ws: Workspace, run: ReportRun) -> str:
    title = f"{_e(run.title)} <span class='muted'>{_e(run.recording)}</span>"
    parts = ["<div class='run'>", f"<h3>{title}</h3>"]
    when = f"{_t(run.started)} to {_t(run.finished)}"
    by = f", started by {_e(run.started_by)}" if run.started_by else ""
    parts.append(f"<p class='muted'>Step version {_e(run.step_version)}, ran {when}{by}.</p>")
    metrics = [q for q in run.qc if q.kind == "metric"]
    if metrics:
        rows = "".join(f"<tr><th>{_e(q.name)}</th><td>{_e(q.value)}</td></tr>" for q in metrics)
        parts.append(f"<table>{rows}</table>")
    for q in run.qc:
        if q.kind == "metric" or _is_main_check(q):
            continue  # the main checks are shown at the top
        parts.append(f"<p><strong>{_e(q.name)}</strong></p>{_pictures_html(ws, q)}")
        if q.warning:
            parts.append(f"<p class='warn'>{_e(q.warning)}</p>")
    for w in run.warnings:
        parts.append(f"<p class='warn'>{_e(w)}</p>")
    params = json.dumps(run.parameters, indent=2, default=str)
    cmds = "\n".join(f"{c.command}    # exit code {c.return_code}" for c in run.commands)
    parts.append(
        f"<details class='fold'><summary>Parameters and commands</summary><div class='body'>"
        f"<pre>{_e(params)}</pre><pre>{_e(cmds) or 'No external command was recorded.'}</pre>"
        f"<p class='muted'>{run.inputs} input and {run.outputs} output files, with hashes, are "
        f"in {_e(run.run_dir)}/provenance.json</p></div></details></div>"
    )
    return "".join(parts)


def _fold(title: str, summary: str, inner: str, badge: str = "") -> str:
    return (
        f"<details class='fold'><summary><strong>{_e(title)}</strong>{badge}"
        f"<span class='sum'>{_e(summary)}</span></summary><div class='body'>{inner}</div></details>"
    )


def render_html(ws: Workspace, report: SubjectReport) -> str:
    runs = [run for section in report.sections for run in section.runs]
    body = [
        f"<header><h1>Processing report: {_e(report.subject)}</h1></header>",
        f"<p class='muted'>Generated {_t(report.generated)} by MRForge "
        f"{_e(report.mrforge_version)} from the recorded processing history. Nothing in this "
        "report is estimated: every figure is a recorded one.</p>",
        "<h2>Quality at a glance</h2>",
    ]
    if report.decisions:
        d = report.decisions[-1]
        earlier = (
            f" &middot; {len(report.decisions) - 1} earlier decision(s) below"
            if len(report.decisions) > 1
            else ""
        )
        body.append(
            f"<div class='card decision'><strong>Researcher's decision</strong>"
            f"<span class='badge {_e(d.decision)}'>{_e(d.decision)}</span><span>{_e(d.reason)}</span>"
            f"<span class='muted'>{_e(d.who or 'unknown')}, {_t(d.when)}{earlier}</span></div>"
        )
    else:
        body.append("<div class='card muted'>No quality decision has been recorded yet.</div>")
    body.extend(f"<p class='warn'>{_e(w)}</p>" for w in report.warnings)
    numbers = [q for run in runs for q in run.qc if q.kind == "metric" and NUMBERS.search(q.name)]
    if numbers:
        body.append(
            "<div class='stats'>"
            + "".join(
                f"<div class='stat'><span class='muted'>{_e(q.name)}</span><b>{_e(q.value)}</b></div>"
                for q in numbers
            )
            + "</div>"
        )
    cards = []
    for label, rx in MAIN_CHECKS:
        for run in runs:
            for q in run.qc:
                if q.kind != "metric" and rx.match(q.name):
                    rec = (
                        f" <span class='muted'>{_e(run.recording)}</span>" if run.recording else ""
                    )
                    warn = f"<p class='warn'>{_e(q.warning)}</p>" if q.warning else ""
                    cards.append(
                        f"<div class='card'><h3>{_e(label)}{rec}</h3>{warn}{_pictures_html(ws, q)}</div>"
                    )
    if cards:
        body.append(f"<div class='checks'>{''.join(cards)}</div>")
    else:
        body.append("<p class='muted'>No quality pictures were recorded.</p>")

    body.append("<h2>What was done</h2>")
    if report.acquisition:
        rows = "".join(
            f"<tr><td>{_e(a.number)}</td><td>{_e(a.description)}</td><td>{_e(a.kind)}</td>"
            f"<td>{_e(a.matrix)}</td><td>{_e(a.volumes)}</td><td>{_e(a.repetition_time_s)}</td>"
            f"<td>{_e(a.echo_time_s)}</td><td>{_e(a.session)}</td></tr>"
            for a in report.acquisition
        )
        acq = (
            "<table><tr><th>Series</th><th>Description</th><th>Imported as</th><th>Size</th>"
            f"<th>Volumes</th><th>TR (s)</th><th>TE (s)</th><th>Session</th></tr>{rows}</table>"
        )
        body.append(_fold("Acquisition", f"{len(report.acquisition)} series", acq))
    else:
        body.append(
            _fold(
                "Acquisition",
                "none recorded",
                "<p class='muted'>No imported series are recorded for this subject.</p>",
            )
        )
    for section in report.sections:
        warns = sum(len(r.warnings) + sum(1 for q in r.qc if q.warning) for r in section.runs)
        badge = f"<span class='badge'>{warns} warning(s)</span>" if warns else ""
        inner = "".join(_run_html(ws, run) for run in section.runs)
        if section.not_run:
            inner += "<p class='notrun'>Not run: " + _e(", ".join(section.not_run)) + "</p>"
        summary = f"{len(section.runs)} run(s)" if section.runs else "not run"
        body.append(_fold(section.title, summary, inner, badge))
    if len(report.decisions) > 1:
        rows = "".join(
            f"<tr><td>{_e(d.decision)}</td><td>{_e(d.reason)}</td><td>{_e(d.who or 'unknown')}</td>"
            f"<td>{_t(d.when)}</td></tr>"
            for d in reversed(report.decisions)
        )
        body.append(
            _fold(
                "All quality decisions",
                f"{len(report.decisions)} recorded",
                f"<table><tr><th>Decision</th><th>Reason</th><th>By</th><th>When</th></tr>{rows}</table>",
            )
        )
    soft = "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in report.software.items())
    body.append(_fold("Software", f"{len(report.software)} tools", f"<table>{soft}</table>"))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Processing report {_e(report.subject)}</title><style>{CSS}</style></head>"
        f"<body><main>{''.join(body)}</main><script>{SCRIPT}</script></body></html>"
    )


def reports_dir(ws: Workspace, subject: str) -> Path:
    return ws.root / "reports" / subject


def export_report(ws: Workspace, report: SubjectReport) -> Path:
    """Write the report into ``reports/<subject>/``."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    folder = reports_dir(ws, report.subject)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{report.subject}_report_{stamp}.html"
    n = 1
    while target.exists():  # two exports in the same second
        n += 1
        target = folder / f"{report.subject}_report_{stamp}-{n}.html"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(render_html(ws, report), encoding="utf-8")
    tmp.replace(target)
    return target


def list_exports(ws: Workspace, subject: str | None = None) -> list[Path]:
    root = ws.root / "reports"
    pattern = f"{subject}/*_report_*.html" if subject else "*/*_report_*.html"
    return sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
