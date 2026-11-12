from pathlib import Path

from mrforge.steps.dwi_eddy import _has_nthr_option


def test_has_nthr_option_probes_help(tmp_path: Path) -> None:
    new = tmp_path / "eddy_new"
    new.write_text("#!/bin/sh\necho '--nthr  threads'\n")
    old = tmp_path / "eddy_old"
    old.write_text("#!/bin/sh\necho '--niter  iterations'\nexit 1\n")
    new.chmod(0o755)
    old.chmod(0o755)
    assert _has_nthr_option(new, None)
    assert not _has_nthr_option(old, None)
