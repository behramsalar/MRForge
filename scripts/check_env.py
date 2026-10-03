"""Check that the tools MRForge needs are available in this shell.

Usage: python scripts/check_env.py
Exit code is 1 if any required check fails, otherwise 0.
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
    for name in ("ICA_AROMA.py", "aroma", "icaaroma"):
        path = shutil.which(name)
        if path:
            return Check("ICA-AROMA", PASS, path)
    return Check("ICA-AROMA", OPTIONAL, "not found (only needed for denoising, MVP 2)")


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


def run_checks(
    probes: list[Callable[[], Check | list[Check]]] | None = None,
) -> list[Check]:
    probes = probes or [
        check_python,
        check_fsl,
        check_dcm2niix,
        check_bids_validator,
        check_aroma,
        check_resources,
    ]
    results: list[Check] = []
    for probe in probes:
        out = probe()
        results.extend(out if isinstance(out, list) else [out])
    return results


def format_report(results: list[Check]) -> str:
    width = max(len(c.name) for c in results)
    return "\n".join(f"[{c.status:^8}] {c.name:<{width}}  {c.detail}" for c in results)


def exit_code(results: list[Check]) -> int:
    return 1 if any(c.status == FAIL for c in results) else 0


def main() -> int:
    results = run_checks()
    print(format_report(results))
    code = exit_code(results)
    print("\nAll required checks passed." if code == 0 else "\nSome required checks FAILED.")
    return code


if __name__ == "__main__":
    sys.exit(main())
