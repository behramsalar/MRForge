"""Shared test helpers: a stand-in ``dcm2niix`` that tests can instruct (fail, write the wrong
size, ...) without needing convertible DICOM files."""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

FAKE = """#!{python}
import json, os, sys
import nibabel as nib
import numpy as np
import pydicom

args = sys.argv[1:]
if args == ["-v"]:
    print("Chris Rorden's dcm2niiX version vTEST")
    sys.exit(0)
spec = json.load(open(os.environ["FAKE_DCM2NIIX_SPEC"]))
out, indir = args[args.index("-o") + 1], args[-1]
names = sorted(os.listdir(indir))
ds = pydicom.dcmread(os.path.join(indir, names[0]), stop_before_pixels=True)
number = int(ds.SeriesNumber)
with open(os.environ["FAKE_DCM2NIIX_LOG"], "a") as log:
    log.write(json.dumps({{"number": number, "names": names, "indir": indir}}) + "\\n")
entry = spec.get(str(number), {{"images": [{{"suffix": ""}}]}})
if entry.get("mode") == "fail":
    print("Error: cannot convert " + indir + "/" + names[0], file=sys.stderr)
    sys.exit(2)
if entry.get("mode") == "nothing":
    sys.exit(0)
for img in entry["images"]:
    shape = img.get("shape", [4, 4, 3])
    suffix = img.get("suffix", "")
    stem = os.path.join(out, str(number) + ("_" + suffix if suffix else ""))
    nib.save(nib.Nifti1Image(np.zeros(shape, dtype="int16"), np.eye(4)), stem + ".nii.gz")
    if not img.get("no_json"):
        json.dump({{"RepetitionTime": 2.0}}, open(stem + ".json", "w"))
    if "bval" in img:
        open(stem + ".bval", "w").write(" ".join(["1000"] * img["bval"]) + "\\n")
        open(stem + ".bvec", "w").write("\\n".join([" ".join(["0"] * img["bval"])] * 3) + "\\n")
"""


class Fake:
    def __init__(self, tmp: Path) -> None:
        self.dir = tmp / "bin"
        self.dir.mkdir()
        self.spec_path = tmp / "spec.json"
        self.log_path = tmp / "calls.jsonl"
        self.spec: dict[str, object] = {}
        script = self.dir / "dcm2niix"
        script.write_text(FAKE.format(python=sys.executable))
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        self.write()

    def write(self) -> None:
        self.spec_path.write_text(json.dumps(self.spec))

    def set(self, number: int, **entry: object) -> None:
        self.spec[str(number)] = entry
        self.write()

    def calls(self) -> list[dict[str, object]]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fake:
    f = Fake(tmp_path)
    monkeypatch.setenv("PATH", f"{f.dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DCM2NIIX_SPEC", str(f.spec_path))
    monkeypatch.setenv("FAKE_DCM2NIIX_LOG", str(f.log_path))
    return f


@pytest.fixture(autouse=True)
def roomy_resources(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests never depend on the computer's own settings or on what else is running: unless a
    test sets its own, processing may use a lot of cores and needs little free memory."""
    if "MRFORGE_CONFIG" in os.environ and os.environ["MRFORGE_CONFIG"].endswith("test-config.json"):
        return
    path = tmp_path_factory.mktemp("config") / "test-config.json"
    path.write_text(
        json.dumps(
            {
                "resources": {
                    "preset": "custom",
                    "max_subjects": 8,
                    "threads_per_job": 1,
                    "cpu_cap": 64,
                    "memory_reserve_gb": 0.0,
                }
            }
        )
    )
    monkeypatch.setenv("MRFORGE_CONFIG", str(path))
