"""The researcher's quality decision about a subject, and the head-motion flag.

QC flags; it never decides (CLAUDE.md principle 6). The flag only tells the researcher that a
subject's head motion is worth a look. The decision (accept / review / exclude, always with a
reason) is the researcher's alone. It is kept as provenance, as a file next to the subject's
results (``sub-X_desc-qc_decision.json``) with the full history, so nothing is ever overwritten
and the numbers the researcher saw at that moment are kept with it.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from mrforge.config import load_config, save_config
from mrforge.errors import StepError
from mrforge.workspace import Workspace

Decision = Literal["accept", "review", "exclude"]


class MotionThresholds(BaseModel):
    # REVIEW(domain): starting proposals in the range commonly used; the flag is a prompt to
    # look at the subject, not a verdict. Framewise displacement as in func_qc (Power 2012).
    mean_fd_mm: float = Field(default=0.3, gt=0)
    fraction_above: float = Field(default=0.2, gt=0, le=1)  # of volumes above the FD threshold


class QcDecisionEntry(BaseModel):
    decision: Decision
    reason: str
    who: str | None = None
    when: str
    motion: dict[str, float] | None = None  # the numbers the researcher saw


def load_thresholds() -> MotionThresholds:
    saved = load_config().get("motion_flag")
    if isinstance(saved, dict):
        try:
            return MotionThresholds.model_validate(saved)
        except ValueError:
            pass
    return MotionThresholds()


def save_thresholds(t: MotionThresholds) -> MotionThresholds:
    config = load_config()
    config["motion_flag"] = t.model_dump()
    save_config(config)
    return t


def motion_flag(
    mean_fd_mm: float, volumes_above: int, n_volumes: int, threshold_mm: float,
    t: MotionThresholds | None = None,
) -> str | None:  # fmt: skip
    """Plain-language reason to look at the head motion, or None."""
    limits = t or load_thresholds()
    reasons: list[str] = []
    if mean_fd_mm > limits.mean_fd_mm:
        reasons.append(f"mean FD {mean_fd_mm:g} mm")
    if n_volumes and volumes_above / n_volumes > limits.fraction_above:
        share = round(100 * volumes_above / n_volumes)
        reasons.append(f"{share}% of volumes above {threshold_mm:g} mm")
    return "check motion: " + ", ".join(reasons) if reasons else None


def _path(ws: Workspace, subject: str) -> Path:
    return ws.derivatives_dir / subject / f"{subject}_desc-qc_decision.json"


def history(ws: Workspace, subject: str) -> list[QcDecisionEntry]:
    path = _path(ws, subject)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
        return [QcDecisionEntry.model_validate(e) for e in data.get("history", [])]
    except (OSError, ValueError):
        return []


def current(ws: Workspace, subject: str) -> QcDecisionEntry | None:
    entries = history(ws, subject)
    return entries[-1] if entries else None


def record(
    ws: Workspace,
    subject: str,
    decision: Decision,
    reason: str,
    who: str | None,
    motion: dict[str, float] | None = None,
) -> QcDecisionEntry:
    """Add a decision to the subject's history. A reason is always required."""
    if not reason.strip():
        raise StepError(
            "REASON_REQUIRED",
            "Please give a reason for your decision.",
            probable_cause="Every quality decision is kept with its reason, so that it can be "
            "understood later.",
            suggested_action="Type a short reason (for example 'too much head motion').",
        )
    entry = QcDecisionEntry(
        decision=decision,
        reason=reason.strip(),
        who=who,
        when=datetime.now(UTC).isoformat(),
        motion=motion,
    )
    entries = [*history(ws, subject), entry]
    path = _path(ws, subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"history": [e.model_dump() for e in entries]}, indent=2) + "\n")
    os.replace(tmp, path)  # never leaves a half-written record
    return entry
