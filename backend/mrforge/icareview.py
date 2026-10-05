"""What the component review screen needs: the MELODIC results of a subject's recordings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mrforge.errors import StepError
from mrforge.icalabels import (
    decision_path,
    draft_path,
    problem_with,
    read_labels,
    write_labels,
)
from mrforge.workspace import Workspace

SUMMARY_SUFFIX = "_desc-melodic_components.json"


class IcaComponent(BaseModel):
    number: int
    variance_pct: float | None
    map_url: str  # 3D z-map, for the viewer overlay
    plots_url: str  # time course and power spectrum
    planes_url: str  # summary of slices through all three planes
    picture_url: str  # the static picture (three planes and the plots)
    peak_mm: list[float]  # where the component is strongest (scanner coordinates, mm)


class IcaRecording(BaseModel):
    recording: str  # for example "task-rest"
    n_components: int
    n_volumes: int
    tr_s: float
    mean_url: str  # the viewer's background: the T1 brain, or the mean functional image
    space: str  # "T1w" when the maps are placed on the T1, else "native"
    components: list[IcaComponent]
    # The researcher's labels: "decided" (final), "draft" (saved but not final), "stale"
    # (made for an earlier MELODIC run, so not used) or "none".
    label_status: str = "none"
    labels: dict[str, str] = {}
    decided_by: str | None = None
    decided_at: str | None = None


def _recording(name: str, subject: str) -> str:
    stem = name.removesuffix(SUMMARY_SUFFIX).removeprefix(f"{subject}_")
    return stem or "run"


def find_ica_results(ws: Workspace, ws_id: str, subject: str) -> list[IcaRecording]:
    """Every recording of the subject that has a complete MELODIC result."""
    folder = ws.derivatives_dir / subject
    out: list[IcaRecording] = []
    for summary in sorted(folder.rglob(f"*{SUMMARY_SUFFIX}")):
        if "_runs" in summary.parts:
            continue
        try:
            data = json.loads(summary.read_text())
            out.append(_read(ws, ws_id, subject, summary, data))
        except (OSError, ValueError, KeyError):
            continue  # unreadable or half-written: simply not offered
    return out


def _url(ws: Workspace, ws_id: str, rel: str) -> str:
    if not ws.abspath(rel).is_file():
        raise KeyError(rel)
    return f"/api/workspaces/{ws_id}/file/{rel}"


def _read(ws: Workspace, ws_id: str, subject: str, summary: Path, data: Any) -> IcaRecording:
    comps = [
        IcaComponent(
            number=int(c["number"]),
            variance_pct=c.get("variance_pct"),
            map_url=_url(ws, ws_id, str(c["map"])),
            plots_url=_url(ws, ws_id, str(c["plots"])),
            planes_url=_url(ws, ws_id, str(c["planes"])),
            picture_url=_url(ws, ws_id, str(c["picture"])),
            peak_mm=[float(v) for v in c["peak_mm"]],
        )
        for c in data["components"]
    ]
    summary_rel = ws.relpath(summary)
    status, labels, who, when = _label_state(ws, summary_rel)
    return IcaRecording(
        recording=_recording(summary.name, subject),
        label_status=status,
        labels=labels,
        decided_by=who,
        decided_at=when,
        n_components=int(data["n_components"]),
        n_volumes=int(data["n_volumes"]),
        tr_s=float(data["tr_s"]),
        mean_url=_url(ws, ws_id, str(data.get("background", data["mean"]))),
        space=str(data.get("space", "native")),
        components=comps,
    )


def _label_state(
    ws: Workspace, summary_rel: str
) -> tuple[str, dict[str, str], str | None, str | None]:
    decision = read_labels(ws, decision_path(summary_rel))
    if decision is not None:
        if problem_with(ws, summary_rel, decision) is None:
            return "decided", decision["labels"], decision.get("who"), decision.get("when")
        status = "stale"
    else:
        status = "none"
    draft = read_labels(ws, draft_path(summary_rel))
    mixing = json.loads(ws.abspath(summary_rel).read_text()).get("mixing_sha256")
    if draft is not None and draft.get("mixing_sha256") == mixing:
        return "draft", draft["labels"], draft.get("who"), draft.get("when")
    return status, {}, None, None


def summary_for(ws: Workspace, subject: str, recording: str) -> str:
    """Workspace path of the MELODIC summary of one recording."""
    for summary in (ws.derivatives_dir / subject).rglob(f"*{SUMMARY_SUFFIX}"):
        if "_runs" not in summary.parts and _recording(summary.name, subject) == recording:
            return ws.relpath(summary)
    raise StepError(
        "NO_COMPONENTS",
        "There are no components for this recording.",
        probable_cause="Component analysis (MELODIC) has not been run for it.",
        suggested_action="Run the artifact rejection stage first.",
    )


def save_labels(
    ws: Workspace,
    subject: str,
    recording: str,
    labels: dict[int, str],
    who: str | None,
    complete: bool,
) -> str:
    """Save the researcher's labels (a draft, or the final decision). Returns the file."""
    return write_labels(ws, summary_for(ws, subject, recording), labels, who, complete)
