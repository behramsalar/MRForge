from pathlib import Path

import pytest
from typer.testing import CliRunner

from mrforge import fsl_env
from mrforge.cli import app
from mrforge.errors import StepError
from mrforge.niftiutil import is_readable_nifti


def fake_fsl(root: Path, version: str = "6.9.9") -> Path:
    (root / "etc").mkdir(parents=True)
    (root / "etc" / "fslversion").write_text(f"{version}:abc\n")
    (root / "bin").mkdir()
    (root / "bin" / "bet").write_text("#!/bin/sh\n")
    return root


@pytest.fixture(autouse=True)
def no_common_locations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fsl_env, "COMMON_LOCATIONS", ())
    monkeypatch.setenv("MRFORGE_CONFIG", str(tmp_path / "config.json"))


def test_setting_beats_environment_variable(tmp_path: Path) -> None:
    a, b = fake_fsl(tmp_path / "a", "1.0"), fake_fsl(tmp_path / "b", "2.0")
    found = fsl_env.find_fsl({"FSLDIR": str(b)}, setting=str(a))
    assert found.fsldir == a and found.source == "app setting" and found.version == "1.0"


def test_environment_variable_used_without_setting(tmp_path: Path) -> None:
    b = fake_fsl(tmp_path / "b", "2.0")
    found = fsl_env.find_fsl({"FSLDIR": str(b)}, setting="")
    assert found.fsldir == b and found.source == "FSLDIR"


def test_common_location_is_searched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = fake_fsl(tmp_path / "fsl_6")
    monkeypatch.setattr(fsl_env, "COMMON_LOCATIONS", (str(tmp_path / "fsl_*"),))
    found = fsl_env.find_fsl({}, setting="")
    assert found.fsldir == c and found.source == "common location"


def test_environment_is_built_from_the_location_not_the_shell(tmp_path: Path) -> None:
    root = fake_fsl(tmp_path / "f")
    env = fsl_env.find_fsl({"FSLDIR": str(root), "PATH": "/usr/bin"}, setting="").env
    assert env["FSLDIR"] == str(root) and env["FSLOUTPUTTYPE"] == "NIFTI_GZ"
    assert env["PATH"].startswith(f"{root}/share/fsl/bin:{root}/bin:")


def test_not_found_is_plain_language(tmp_path: Path) -> None:
    with pytest.raises(StepError) as info:
        fsl_env.find_fsl({"FSLDIR": str(tmp_path / "missing")}, setting="")
    err = info.value
    assert err.code == "FSL_NOT_FOUND" and "mrforge config fsl" in err.suggested_action
    assert str(tmp_path / "missing") in err.probable_cause


def test_config_fsl_command(tmp_path: Path) -> None:
    runner = CliRunner()
    root = fake_fsl(tmp_path / "f", "3.1")
    bad = runner.invoke(app, ["config", "fsl", str(tmp_path)])
    assert bad.exit_code == 1 and "does not look like an FSL" in bad.output
    assert runner.invoke(app, ["config", "fsl", str(root)]).exit_code == 0
    shown = runner.invoke(app, ["config", "fsl"])
    assert shown.exit_code == 0 and "FSL 3.1" in shown.output and "app setting" in shown.output


def test_is_readable_nifti(tmp_path: Path) -> None:
    import gzip
    import struct

    good = tmp_path / "ok.nii.gz"
    with gzip.open(good, "wb") as fh:
        fh.write(struct.pack("<i", 348) + b"\0" * 400)
    plain = tmp_path / "ok.nii"
    plain.write_bytes(struct.pack(">i", 348) + b"\0" * 400)
    bad = tmp_path / "bad.nii.gz"
    bad.write_text("not an image")
    assert is_readable_nifti(good) and is_readable_nifti(plain)
    assert not is_readable_nifti(bad) and not is_readable_nifti(tmp_path / "none.nii.gz")
