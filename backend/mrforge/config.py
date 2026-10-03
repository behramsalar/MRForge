"""Per-user app settings (a small JSON file). Currently only the FSL location."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def config_path() -> Path:
    override = os.environ.get("MRFORGE_CONFIG")
    return Path(override) if override else Path.home() / ".config" / "mrforge" / "config.json"


def load_config() -> dict[str, Any]:
    try:
        data = json.loads(config_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
