"""Find ICA-AROMA (the reference implementation by Pruim et al., ``ICA_AROMA.py``).

It is not part of FSL and not on PyPI under its own name, so MRForge looks for it here, in this
order: the ``MRFORGE_AROMA`` environment variable (path to ``ICA_AROMA.py``), the copy that
``scripts/install_aroma.sh`` puts in ``tools/ICA-AROMA`` of the project, then the PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AromaInstall:
    script: Path
    version: str  # git tag/commit of the copy, or "unknown"


def _version(script: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(script.parent), "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out or "unknown"


def find_aroma() -> AromaInstall | None:
    candidates: list[Path] = []
    if os.environ.get("MRFORGE_AROMA"):
        candidates.append(Path(os.environ["MRFORGE_AROMA"]).expanduser())
    candidates.append(PROJECT / "tools" / "ICA-AROMA" / "ICA_AROMA.py")
    for name in ("ICA_AROMA.py",):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for path in candidates:
        if path.is_file():
            return AromaInstall(path, _version(path))
    return None
