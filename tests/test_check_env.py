from pathlib import Path

import check_env
import pytest
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


def test_failed_checks_carry_a_plain_language_next_step() -> None:
    from mrforge import system_check

    results = system_check.run_checks(
        [lambda: system_check.Check("dcm2niix", system_check.FAIL, "not found")]
    )
    assert "brew install dcm2niix" in results[0].fix


def test_the_system_route_reports_every_check_and_readiness(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    from fastapi.testclient import TestClient

    from mrforge.api.app import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    body = TestClient(create_app(tmp_path / "w")).get("/api/system").json()
    names = [c["name"] for c in body["checks"]]
    assert "Python" in names and "dcm2niix" in names and "Free disk" in names
    assert body["ready"] == all(c["status"] != "FAIL" for c in body["checks"])


def _fake_tool(folder: Path, name: str, version_line: str = "") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_text(f"#!/bin/sh\necho '{version_line}'\n")
    exe.chmod(0o755)


def test_mrtrix3_is_found_on_the_path_or_through_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mrforge.mrtrix_env import find_mrtrix

    bin_dir = tmp_path / "mrtrix" / "bin"
    for tool in ("dwidenoise", "mrdegibbs"):
        _fake_tool(bin_dir, tool, "== dwidenoise 3.0.8 ==")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert find_mrtrix() is None
    monkeypatch.setenv("MRFORGE_MRTRIX", str(bin_dir))
    found = find_mrtrix()
    assert found is not None and found.version == "3.0.8"
    monkeypatch.delenv("MRFORGE_MRTRIX")
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    assert find_mrtrix() is not None


def test_mrtrix3_needs_both_programs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mrforge.mrtrix_env import find_mrtrix

    _fake_tool(tmp_path / "bin", "dwidenoise")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    assert find_mrtrix() is None


def test_missing_mrtrix3_is_optional_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from mrforge import system_check as sc

    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("MRFORGE_MRTRIX", raising=False)
    check = sc._with_fix(sc.check_mrtrix())
    assert check.status == sc.OPTIONAL and "skipped" in check.detail and check.fix
    assert sc.exit_code([check]) == 0


def test_diffusion_tools_check_lists_what_is_missing(tmp_path: Path) -> None:
    from mrforge import system_check as sc

    fsl = tmp_path / "fsl"
    for name in ("topup", "dtifit"):
        _fake_tool(fsl / "bin", name)
    check = sc.check_fsl_diffusion({"FSLDIR": str(fsl), "PATH": "/nonexistent"})
    assert check.status == sc.OPTIONAL and "eddy" in check.detail and "bet2" in check.detail
