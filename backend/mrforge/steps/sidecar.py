"""Reading the BIDS JSON sidecar that sits next to an image (TR, echo times, phase-encoding
direction, ...). The import step writes one beside every raw image."""

from __future__ import annotations

import json
from typing import Any

from mrforge.bids import split_extension
from mrforge.workspace import Workspace


def read_sidecar(ws: Workspace, image_relpath: str) -> dict[str, Any]:
    """The sidecar of ``image_relpath`` (workspace-relative), or ``{}`` if there is none."""
    stem, _ = split_extension(image_relpath)
    path = ws.abspath(stem + ".json")
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
