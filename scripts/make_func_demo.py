"""Build a small functional demo workspace from a prepared full workspace (see
docs/TEST_DATA.md): the first N volumes of the resting BOLD run, the fieldmap, the T1 and the
``fsl_anat`` results. Everything is copied, nothing in the source workspace is touched.

    ~/progders/bin/python scripts/make_func_demo.py [--volumes 20]
        [--source ~/Documents/mrforge-workspaces/func-test]
        [--dest ~/Documents/mrforge-workspaces/func-e2e]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from mrforge.fsl_env import find_fsl
from mrforge.models import File
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001"
FMAP = ("magnitude1", "magnitude2", "phasediff")
ANAT = (
    "sub-001_desc-biascorr_T1w.nii.gz",
    "sub-001_desc-brain_T1w.nii.gz",
    "sub-001_dseg.nii.gz",
    "sub-001_from-T1w_to-MNI152NLin6Asym_mode-image_desc-fnirtcoeff_xfm.nii.gz",
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    home = Path.home() / "Documents" / "mrforge-workspaces"
    ap.add_argument("--source", type=Path, default=home / "func-test")
    ap.add_argument("--dest", type=Path, default=home / "func-e2e")
    ap.add_argument("--volumes", type=int, default=20)
    args = ap.parse_args()
    src, dest = args.source.expanduser(), args.dest.expanduser()
    bold = "rawbids/sub-001/func/sub-001_task-rest_bold"
    needed = [src / f"{bold}.nii.gz", src / f"{bold}.json"] + [src / D / "anat" / n for n in ANAT]
    missing = [str(p) for p in needed if not p.is_file()]
    if missing:
        print(
            f"The source workspace is not ready (missing {missing[0]}). Import the session and "
            "run anatomical processing first."
        )
        return 1
    ws = Workspace.create(dest, dest.name)
    fsl = find_fsl()
    (ws.root / bold).parent.mkdir(parents=True, exist_ok=True)
    cut = ["fslroi", str(src / f"{bold}.nii.gz"), str(ws.root / bold), "0", str(args.volumes)]
    subprocess.run(cut, env=fsl.env, check=True)
    shutil.copy2(src / f"{bold}.json", ws.root / f"{bold}.json")
    for name in FMAP:
        for ext in (".nii.gz", ".json"):
            rel = f"rawbids/sub-001/fmap/sub-001_{name}{ext}"
            (ws.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, ws.root / rel)
    t1 = "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    (ws.root / t1).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / t1, ws.root / t1)
    for n in ANAT:
        (ws.root / D / "anat").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / D / "anat" / n, ws.root / D / "anat" / n)
    subject_id = ws.get_or_create_subject("sub-001")
    with ws.session() as s:
        s.add(File(subject_id=subject_id, relpath=f"{bold}.nii.gz", kind="bold"))
        s.add(File(subject_id=subject_id, relpath=t1, kind="T1w"))
    print(f"Created {dest} ({args.volumes} volumes). Open the Functional page to run it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
