"""Find FSL and build the environment its tools need.

No FSL path is hard-coded (docs/DECISIONS.md). Lookup order:
  1. the app setting ``fsldir`` (``mrforge config fsl <path>``)
  2. the ``FSLDIR`` environment variable
  3. common install locations
The runner builds the subprocess environment from the result instead of inheriting
whatever shell started the program (non-login shells often lack FSLDIR).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mrforge.config import load_config
from mrforge.errors import StepError

COMMON_LOCATIONS = ("~/fsl", "~/fsl_*", "/usr/local/fsl", "/opt/fsl", "/usr/share/fsl")


@dataclass(frozen=True)
class FslInstall:
    fsldir: Path
    version: str
    env: dict[str, str]
    source: str  # where it was found: "app setting", "FSLDIR", or "common location"


def looks_like_fsl(path: Path) -> bool:
    return (path / "etc" / "fslversion").is_file() and (
        (path / "bin" / "bet").exists() or (path / "share" / "fsl" / "bin" / "bet").exists()
    )


def read_version(fsldir: Path) -> str:
    text = (fsldir / "etc" / "fslversion").read_text().strip()
    return text.splitlines()[0].split(":")[0] if text else "unknown"


def _candidates(environ: Mapping[str, str], setting: str | None) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    configured = setting if setting is not None else load_config().get("fsldir")
    if configured:
        found.append(("app setting", Path(str(configured)).expanduser()))
    if environ.get("FSLDIR"):
        found.append(("FSLDIR", Path(environ["FSLDIR"]).expanduser()))
    for pattern in COMMON_LOCATIONS:
        expanded = Path(pattern).expanduser()
        if "*" in pattern:
            found.extend(
                ("common location", p) for p in sorted(expanded.parent.glob(expanded.name))
            )
        else:
            found.append(("common location", expanded))
    return found


def build_env(fsldir: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment equivalent to sourcing ``$FSLDIR/etc/fslconf/fsl.sh`` (without the optional
    site/user override files, so runs do not depend on personal settings)."""
    env = dict(os.environ if base is None else base)
    env["FSLDIR"] = str(fsldir)
    env["PATH"] = os.pathsep.join(
        [str(fsldir / "share" / "fsl" / "bin"), str(fsldir / "bin"), env.get("PATH", "")]
    )
    env["FSLOUTPUTTYPE"] = "NIFTI_GZ"
    env["FSLMULTIFILEQUIT"] = "TRUE"
    env["FSLTCLSH"] = str(fsldir / "bin" / "fsltclsh")
    env["FSLWISH"] = str(fsldir / "bin" / "fslwish")
    env["FSL_LOAD_NIFTI_EXTENSIONS"] = "0"
    env["FSL_SKIP_GLOBAL"] = "0"
    return env


def find_fsl(environ: Mapping[str, str] | None = None, setting: str | None = None) -> FslInstall:
    environ = os.environ if environ is None else environ
    tried: list[str] = []
    for source, path in _candidates(environ, setting):
        if looks_like_fsl(path):
            return FslInstall(path, read_version(path), build_env(path, environ), source)
        tried.append(f"{path} ({source})")
    raise StepError(
        code="FSL_NOT_FOUND",
        message="FSL (the brain imaging software this step needs) could not be found.",
        probable_cause="FSL is not installed, or MRForge was not told where it is. Looked in: "
        + (", ".join(tried) or "nowhere"),
        suggested_action="Install FSL, or tell MRForge where it is with "
        "'mrforge config fsl /path/to/fsl' (the folder that contains 'etc/fslversion').",
    )
