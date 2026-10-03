from pathlib import Path

import check_env
from check_env import FAIL, OPTIONAL, PASS, Check


def test_exit_code_fails_only_on_required_failure() -> None:
    assert check_env.exit_code([Check("a", PASS, ""), Check("b", OPTIONAL, "")]) == 0
    assert check_env.exit_code([Check("a", PASS, ""), Check("b", FAIL, "")]) == 1


def test_run_checks_flattens_probe_results() -> None:
    results = check_env.run_checks(
        [
            lambda: Check("one", PASS, "x"),
            lambda: [Check("two", PASS, "y"), Check("three", FAIL, "z")],
        ]
    )
    assert [c.name for c in results] == ["one", "two", "three"]
    assert "[  FAIL  ] three" in check_env.format_report(results)


def test_fsl_unset_gives_hint() -> None:
    (result,) = check_env.check_fsl({})
    assert result.status == FAIL and "FSLDIR" in result.detail


def test_fsl_fake_install(tmp_path: Path) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "fslversion").write_text("6.0.7.23:abc\n")
    bindir = tmp_path / "share" / "fsl" / "bin"
    bindir.mkdir(parents=True)
    for name in check_env.FSL_BINARIES:
        exe = bindir / name
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
    results = {c.name: c for c in check_env.check_fsl({"FSLDIR": str(tmp_path), "PATH": ""})}
    assert results["FSL version"].detail == "6.0.7.23"
    assert all(c.status == PASS for c in results.values())


def test_fsl_missing_binary_fails(tmp_path: Path) -> None:
    results = check_env.check_fsl({"FSLDIR": str(tmp_path), "PATH": ""})
    assert any(c.name == "FSL: bet" and c.status == FAIL for c in results)
