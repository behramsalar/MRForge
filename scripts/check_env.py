"""Check that the tools MRForge needs are available in this shell.

Usage: python scripts/check_env.py
Exit code is 1 if any required check fails, otherwise 0.
The checks themselves live in backend/mrforge/system_check.py (shared with the System page).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from mrforge.system_check import (  # noqa: E402,F401
    FAIL,
    FSL_BINARIES,
    INFO,
    OPTIONAL,
    PASS,
    Check,
    check_aroma,
    check_bids_validator,
    check_dcm2niix,
    check_fsl,
    check_python,
    check_resources,
    exit_code,
    format_report,
    run_checks,
)


def main() -> int:
    results = run_checks()
    print(format_report(results))
    code = exit_code(results)
    print("\nAll required checks passed." if code == 0 else "\nSome required checks FAILED.")
    return code


if __name__ == "__main__":
    sys.exit(main())
