"""Is this computer ready for MRForge? One implementation of the environment checks, shared by
``scripts/check_env.py``, ``mrforge doctor`` and the System page.

Two flavours: the plain one (``app_aware=False``) looks only at this shell, as the Stage 0
script always did; the app-aware one finds FSL, the BIDS validator and ICA-AROMA the way
MRForge itself does (its settings, common places), which is what decides whether processing
will work.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PASS, FAIL, OPTIONAL, INFO = "PASS", "FAIL", "OPTIONAL", "INFO"

FSL_BINARIES = ["bet", "fsl_anat", "mcflirt", "flirt", "fslmaths", "fslstats"]
MIN_PYTHON = (3, 11)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""  # plain-language next step when the check did not pass


def _run(cmd: list[str]) -> str:
    """Run a command and return its combined output (empty string on failure)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (proc.stdout + proc.stderr).strip()


def check_python() -> Check:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    ok = (v.major, v.minor) >= MIN_PYTHON
    detail = f"{ver} ({sys.executable})"
    if not ok:
        detail += f"; need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    return Check("Python", PASS if ok else FAIL, detail)


def check_fsl(env: dict[str, str] | None = None) -> list[Check]:
    env = dict(os.environ) if env is None else env
    fsldir = env.get("FSLDIR", "")
    if not fsldir:
        return [
            Check(
                "FSLDIR",
                FAIL,
                "not set. Open a login shell, or export FSLDIR and "
                "source $FSLDIR/etc/fslconf/fsl.sh",
            )
        ]
    root = Path(fsldir)
    if not root.is_dir():
        return [Check("FSLDIR", FAIL, f"{fsldir} does not exist")]
    results = [Check("FSLDIR", PASS, fsldir)]
    version_file = root / "etc" / "fslversion"
    if version_file.is_file():
        version = version_file.read_text().strip().splitlines()[0].split(":")[0]
        results.append(Check("FSL version", PASS, version))
    else:
        results.append(Check("FSL version", FAIL, f"{version_file} not found"))
    search_path = os.pathsep.join([str(root / "share" / "fsl" / "bin"), str(root / "bin")])
    search_path += os.pathsep + env.get("PATH", "")
    for name in FSL_BINARIES:
        found = shutil.which(name, path=search_path)
        results.append(Check(f"FSL: {name}", PASS if found else FAIL, found or "not found"))
    return results


def check_dcm2niix() -> Check:
    path = shutil.which("dcm2niix")
    if not path:
        return Check("dcm2niix", FAIL, "not found on PATH (macOS: brew install dcm2niix)")
    out = _run([path, "-v"]).splitlines()
    return Check("dcm2niix", PASS, f"{out[0] if out else 'version unknown'} ({path})")


def check_bids_validator() -> Check:
    path = shutil.which("bids-validator")
    if not path:
        return Check("BIDS validator", FAIL, "not found on PATH (npm install -g bids-validator)")
    out = _run([path, "--version"]).splitlines()
    return Check("BIDS validator", PASS, f"{out[-1] if out else 'version unknown'} ({path})")


def check_aroma() -> Check:
    from mrforge.aroma_env import find_aroma

    found = find_aroma()
    if found:
        return Check("ICA-AROMA", PASS, f"{found.version} ({found.script})")
    return Check(
        "ICA-AROMA",
        OPTIONAL,
        "not found (optional; automatic component labelling. scripts/install_aroma.sh installs it)",
    )


def _ram_bytes() -> int | None:
    if sys.platform == "darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        return int(out) if out.isdigit() else None
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    return None


def check_resources(path: str = ".") -> list[Check]:
    ram = _ram_bytes()
    free = shutil.disk_usage(path).free
    return [
        Check("OS", INFO, f"{platform.system()} {platform.release()} ({platform.machine()})"),
        Check("CPU cores", INFO, str(os.cpu_count())),
        Check("RAM", INFO, f"{ram / 2**30:.1f} GiB" if ram else "unknown"),
        Check("Free disk", INFO, f"{free / 2**30:.1f} GiB in {Path(path).resolve()}"),
    ]


FIXES = {
    "FSL": "Install FSL (https://fsl.fmrib.ox.ac.uk/fsl/docs/), then tell MRForge where it is "
    "with 'mrforge config fsl /path/to/fsl'.",
    "dcm2niix": "Install dcm2niix (macOS: brew install dcm2niix).",
    "BIDS validator": "Install the BIDS validator (npm install -g bids-validator), or tell "
    "MRForge where it is with 'mrforge config bids-validator /path'.",
    "ICA-AROMA": "Optional. Run scripts/install_aroma.sh to install it.",
    "Python": f"MRForge needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
}


def check_fsl_app() -> list[Check]:
    """FSL as MRForge finds it (its setting, FSLDIR, common places)."""
    from mrforge.errors import StepError
    from mrforge.fsl_env import find_fsl

    try:
        install = find_fsl()
    except StepError as err:
        return [Check("FSL", FAIL, err.message, FIXES["FSL"])]
    return check_fsl(install.env)


def check_validator_app() -> Check:
    from mrforge.errors import StepError
    from mrforge.importing.bids_validate import find_validator

    try:
        return Check("BIDS validator", PASS, str(find_validator()))
    except StepError as err:
        return Check("BIDS validator", FAIL, err.message, FIXES["BIDS validator"])


def _with_fix(check: Check) -> Check:
    """Attach the plain-language next step to a check that did not pass."""
    if check.status in (PASS, INFO) or check.fix:
        return check
    key = next((k for k in FIXES if check.name.startswith(k)), None)
    return Check(check.name, check.status, check.detail, FIXES[key]) if key else check


def run_checks(
    probes: list[Callable[[], Check | list[Check]]] | None = None,
    app_aware: bool = False,
    path: str = ".",
) -> list[Check]:
    probes = probes or [
        check_python,
        check_fsl_app if app_aware else check_fsl,
        check_dcm2niix,
        check_validator_app if app_aware else check_bids_validator,
        check_aroma,
        lambda: check_resources(path),
    ]
    results: list[Check] = []
    for probe in probes:
        out = probe()
        results.extend(_with_fix(c) for c in (out if isinstance(out, list) else [out]))
    return results


def format_report(results: list[Check]) -> str:
    width = max(len(c.name) for c in results)
    return "\n".join(f"[{c.status:^8}] {c.name:<{width}}  {c.detail}" for c in results)


def exit_code(results: list[Check]) -> int:
    return 1 if any(c.status == FAIL for c in results) else 0
