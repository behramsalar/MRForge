"""What the component review screen needs: the MELODIC results of a subject's recordings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

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
    return IcaRecording(
        recording=_recording(summary.name, subject),
        n_components=int(data["n_components"]),
        n_volumes=int(data["n_volumes"]),
        tr_s=float(data["tr_s"]),
        mean_url=_url(ws, ws_id, str(data.get("background", data["mean"]))),
        space=str(data.get("space", "native")),
        components=comps,
    )
