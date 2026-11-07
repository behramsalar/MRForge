"""Find MRtrix3 (``dwidenoise`` and ``mrdegibbs``), an optional extra for diffusion data.

MRtrix3 is not part of FSL. Only two steps of the diffusion stage use it (denoising and removing
Gibbs ringing); without it those two steps are skipped and everything else still runs. MRForge
looks in this order: the ``MRFORGE_MRTRIX`` environment variable (the folder that holds the
MRtrix3 programs), then the PATH.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

TOOLS = ("dwidenoise", "mrdegibbs")


@dataclass(frozen=True)
class MrtrixInstall:
    dwidenoise: Path
    mrdegibbs: Path
    version: str  # e.g. "3.0.8", or "unknown"


def _version(exe: Path) -> str:
    try:
        out = subprocess.run(
            [str(exe), "-version"], capture_output=True, text=True, timeout=20, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    found = re.search(r"==\s*\S+\s+([0-9][^\s=]*)\s*==", out)
    return found.group(1) if found else "unknown"


def find_mrtrix() -> MrtrixInstall | None:
    """The MRtrix3 programs MRForge uses, or None when either one is missing."""
    folder = os.environ.get("MRFORGE_MRTRIX")
    search = str(Path(folder).expanduser()) if folder else None
    found: dict[str, Path] = {}
    for name in TOOLS:
        path = shutil.which(name, path=search) if search else shutil.which(name)
        if path is None and search:  # not in the given folder: fall back to the PATH
            path = shutil.which(name)
        if path is None:
            return None
        found[name] = Path(path)
    return MrtrixInstall(found["dwidenoise"], found["mrdegibbs"], _version(found["dwidenoise"]))
