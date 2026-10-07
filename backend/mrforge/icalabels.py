"""The researcher's decision about ICA components: which are signal, which are noise.

A decision is a small JSON file next to the MELODIC result (it is provenance: who decided, when,
and for which decomposition). It names the decomposition by the hash of its mixing matrix, so
labels made for one MELODIC run are never applied to another (component numbers would mean
something else after a re-run with other settings).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from mrforge.errors import StepError
from mrforge.workspace import Workspace

LABELS = ("signal", "noise", "uncertain")
SUMMARY_SUFFIX = "_desc-melodic_components.json"
DECISION_SUFFIX = "_desc-icalabels_decision.json"
DRAFT_SUFFIX = "_desc-icalabels_draft.json"
AROMA_SUFFIX = "_desc-aroma_classification.json"


def decision_path(summary_rel: str) -> str:
    return summary_rel.removesuffix(SUMMARY_SUFFIX) + DECISION_SUFFIX


def draft_path(summary_rel: str) -> str:
    return summary_rel.removesuffix(SUMMARY_SUFFIX) + DRAFT_SUFFIX


def aroma_path(summary_rel: str) -> str:
    return summary_rel.removesuffix(SUMMARY_SUFFIX) + AROMA_SUFFIX


def read_proposal(ws: Workspace, summary_rel: str) -> dict[str, str] | None:
    """ICA-AROMA's proposal for these components (motion components as noise, the rest as
    signal), if it was run on this very decomposition."""
    path = ws.abspath(aroma_path(summary_rel))
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        summary = read_summary(ws, summary_rel)
    except (OSError, ValueError):
        return None
    if data.get("mixing_sha256") != summary.get("mixing_sha256"):
        return None
    noise = {int(n) for n in data["motion_components"]}
    return {
        str(n): ("noise" if n in noise else "signal")
        for n in range(1, int(summary["n_components"]) + 1)
    }


def read_summary(ws: Workspace, summary_rel: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(ws.abspath(summary_rel).read_text())
    return data


def read_labels(ws: Workspace, rel: str) -> dict[str, Any] | None:
    """A saved decision or draft, or None if there is none (or it cannot be read)."""
    path = ws.abspath(rel)
    if not path.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data


def problem_with(ws: Workspace, summary_rel: str, saved: dict[str, Any] | None) -> str | None:
    """Why a saved decision cannot be used, in plain words (None when it is fine)."""
    if saved is None:
        return "The components have not been labelled yet."
    summary = read_summary(ws, summary_rel)
    if saved.get("mixing_sha256") != summary.get("mixing_sha256"):
        return (
            "The components were found again (MELODIC was re-run), so the earlier labels "
            "no longer fit. Please label them again."
        )
    labels = saved.get("labels", {})
    wanted = {str(n) for n in range(1, int(summary["n_components"]) + 1)}
    if set(labels) != wanted or any(v not in LABELS for v in labels.values()):
        return "Not every component has been labelled yet."
    return None


def write_labels(
    ws: Workspace,
    summary_rel: str,
    labels: dict[int, str],
    who: str | None,
    complete: bool,
    source: str = "manual",
) -> str:
    """Save a draft (``complete`` False) or the final decision. Returns the file's path.
    A final decision needs every component to have a valid label."""
    summary = read_summary(ws, summary_rel)
    if "mixing_sha256" not in summary:
        raise StepError(
            "ICA_RESULT_OUTDATED",
            "These components were made by an older version of MRForge.",
            probable_cause="The result does not identify which run the labels belong to.",
            suggested_action="Run the component analysis (MELODIC) again for this recording.",
        )
    n = int(summary["n_components"])
    bad = [k for k, v in labels.items() if v not in LABELS or not 1 <= k <= n]
    if bad:
        raise StepError(
            "INVALID_LABELS",
            "Some labels are not valid.",
            probable_cause=f"Component(s) {sorted(bad)[:5]} are outside 1-{n} or not signal, "
            "noise or uncertain.",
            suggested_action="Reload the page and label the components again.",
        )
    if complete and len(labels) != n:
        raise StepError(
            "LABELS_INCOMPLETE",
            f"{n - len(labels)} component(s) still have no label.",
            probable_cause="Every component must be labelled before the pipeline can go on.",
            suggested_action="Label the remaining components (uncertain is allowed).",
        )
    rel = decision_path(summary_rel) if complete else draft_path(summary_rel)
    payload = {
        "schema": 1,
        "mixing_sha256": summary["mixing_sha256"],
        "n_components": n,
        "labels": {str(k): labels[k] for k in sorted(labels)},
        "who": who,
        "when": datetime.now(UTC).isoformat(),
        "source": source,
    }
    path = ws.abspath(rel)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, path)  # never leaves a half-written decision behind
    if complete:
        ws.abspath(draft_path(summary_rel)).unlink(missing_ok=True)
    return rel
