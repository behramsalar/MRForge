"""Tests of the diffusion preparation steps (denoise, unring, topup).

Unit tests need no tools. The ``fsl`` tests run on real diffusion data when it is available
(an imported workspace with a dwi series and a reverse-phase-encoding b0, see docs/TEST_DATA.md;
set MRFORGE_DWI_TESTDATA to its ``rawbids/sub-001`` folder) and compare with the script's own
commands (alps.sh lines 286-417).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge.engine import Action, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import FslInstall, find_fsl
from mrforge.mrtrix_env import find_mrtrix
from mrforge.runner.jobs import build_context
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401  (registers the steps)
from mrforge.steps import dwi_common as c
from mrforge.workspace import Workspace

SIEMENS_AP = {"Manufacturer": "Siemens", "PhaseEncodingDirection": "j-", "TotalReadoutTime": 0.036}
SIEMENS_PA = {"Manufacturer": "Siemens", "PhaseEncodingDirection": "j", "TotalReadoutTime": 0.07}
PHILIPS = {"Manufacturer": "Philips", "PhaseEncodingAxis": "j", "TotalReadoutTime": 0.5}


# -- the acquisition parameters -------------------------------------------------------------


def test_siemens_sidecar_gives_direction_and_readout() -> None:
    e = c.read_encoding(SIEMENS_AP)
    assert (e.direction, e.readout_s, e.line) == ("j-", 0.036, "0 -1 0 0.036")


def test_philips_uses_the_axis_and_assumes_the_readout_time_of_the_script() -> None:
    e = c.read_encoding(PHILIPS)
    assert (e.direction, e.readout_s, e.line) == ("j", 0.1, "0 1 0 0.1")


@pytest.mark.parametrize(
    "direction, vector",
    [("i", "1 0 0"), ("i-", "-1 0 0"), ("j", "0 1 0"), ("j-", "0 -1 0"), ("k", "0 0 1"),
     ("k-", "0 0 -1")],
)  # fmt: skip
def test_all_six_directions(direction: str, vector: str) -> None:
    sc = {"Manufacturer": "GE", "PhaseEncodingDirection": direction, "TotalReadoutTime": 0.05}
    assert c.read_encoding(sc).line == f"{vector} 0.05"


@pytest.mark.parametrize(
    "sidecar",
    [{}, {"PhaseEncodingDirection": "x", "TotalReadoutTime": 0.05},
     {"PhaseEncodingDirection": "j"}, {"PhaseEncodingDirection": "j", "TotalReadoutTime": 0},
     {"Manufacturer": "Philips", "PhaseEncodingDirection": "j"}],
)  # fmt: skip
def test_a_sidecar_that_does_not_say_how_it_was_encoded_is_refused(sidecar: dict) -> None:
    with pytest.raises(c.EncodingError):
        c.read_encoding(sidecar)


@pytest.mark.parametrize("d, o", [("j", "j-"), ("j-", "j"), ("i", "i-"), ("k-", "k")])
def test_opposite(d: str, o: str) -> None:
    assert c.opposite(d) == o


def test_without_a_second_sidecar_the_reverse_is_opposite_with_the_same_readout() -> None:
    main = c.read_encoding(SIEMENS_AP)
    rev = c.reverse_encoding(main, None, assume_opposite=False)
    assert (rev.direction, rev.readout_s) == ("j", 0.036)


def test_two_philips_images_look_alike_unless_told_they_are_opposite() -> None:
    main = c.read_encoding(PHILIPS)
    same = c.reverse_encoding(main, PHILIPS, assume_opposite=False)
    assert c.topup_problem(main, same, True, True) is not None  # the script skips TOPUP here
    flipped = c.reverse_encoding(main, PHILIPS, assume_opposite=True)
    assert flipped.direction == "j-"
    assert c.topup_problem(main, flipped, True, True) is None


def test_topup_needs_opposite_directions_and_b0_first() -> None:
    ap, pa = c.read_encoding(SIEMENS_AP), c.read_encoding(SIEMENS_PA)
    assert c.topup_problem(ap, pa, True, True) is None
    assert "opposite" in (c.topup_problem(ap, ap, True, True) or "")
    assert "b = 0" in (c.topup_problem(ap, pa, True, False) or "")


def test_the_first_volume_is_b0_as_in_the_script() -> None:
    assert c.starts_with_b0("0 1000 1000")
    assert c.starts_with_b0(None)  # no b-value file: assumed, like the script
    assert not c.starts_with_b0("1000 0 0")
    assert not c.starts_with_b0("")


@pytest.mark.parametrize("n, cnf", [(62, "b02b0.cnf"), (63, "b02b0_1.cnf")])
def test_odd_slice_counts_use_the_other_configuration(n: int, cnf: str) -> None:
    assert c.topup_config(n) == cnf


def test_acqparams_text_has_one_line_per_acquisition() -> None:
    ap, pa = c.read_encoding(SIEMENS_AP), c.read_encoding(SIEMENS_PA)
    assert c.acqparams_text(ap, pa) == "0 -1 0 0.036\n0 1 0 0.07\n"


# -- the steps without tools ----------------------------------------------------------------


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def put_image(ws: Workspace, rel: str, shape: tuple[int, ...]) -> str:
    path = ws.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.ones(shape, np.float32), np.eye(4)), path)  # type: ignore[attr-defined]
    return rel


def put_text(ws: Workspace, rel: str, text: str) -> str:
    path = ws.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return rel


def topup_inputs(ws: Workspace, ap: dict, pa: dict | None, bval: str = "0 1000") -> dict:
    d = "rawbids/sub-001"
    inputs = {
        "dwi": put_image(ws, f"{d}/dwi/sub-001_dwi.nii.gz", (4, 4, 4, 2)),
        "dwi_json": put_text(ws, f"{d}/dwi/sub-001_dwi.json", json.dumps(ap)),
        "dwi_bval": put_text(ws, f"{d}/dwi/sub-001_dwi.bval", bval),
        "reverse": put_image(ws, f"{d}/fmap/sub-001_dir-PA_epi.nii.gz", (4, 4, 4)),
    }
    if pa is not None:
        inputs["reverse_json"] = put_text(ws, f"{d}/fmap/sub-001_dir-PA_epi.json", json.dumps(pa))
    return inputs


def test_result_names(ws: Workspace) -> None:
    inputs = topup_inputs(ws, SIEMENS_AP, SIEMENS_PA)
    step, ctx = build_context(ws, "dwi_topup", "sub-001", None, inputs, {})
    out = step.expected_outputs(ctx)
    assert out.acqparams == "sub-001_desc-topup_acqparams.txt"
    assert out.fieldcoef == "sub-001_desc-topup_fieldcoef.nii.gz"
    assert step.topup_base(out) == "sub-001_desc-topup"
    assert out.mask == "sub-001_desc-topup_mask.nii.gz"


def test_topup_inputs_are_fine_for_a_proper_pair(ws: Workspace) -> None:
    step, ctx = build_context(
        ws, "dwi_topup", "sub-001", None, topup_inputs(ws, SIEMENS_AP, SIEMENS_PA), {}
    )
    assert step.validate_inputs(ctx) == []


def test_same_direction_is_explained(ws: Workspace) -> None:
    step, ctx = build_context(
        ws, "dwi_topup", "sub-001", None, topup_inputs(ws, SIEMENS_AP, SIEMENS_AP), {}
    )
    assert [p.code for p in step.validate_inputs(ctx)] == ["TOPUP_NOT_POSSIBLE"]


def test_no_b0_first_is_explained(ws: Workspace) -> None:
    inputs = topup_inputs(ws, SIEMENS_AP, SIEMENS_PA, bval="1000 0")
    step, ctx = build_context(ws, "dwi_topup", "sub-001", None, inputs, {})
    problems = step.validate_inputs(ctx)
    assert [p.code for p in problems] == ["TOPUP_NOT_POSSIBLE"]
    assert "b = 0" in problems[0].message


def test_missing_readout_time_is_explained(ws: Workspace) -> None:
    bad = {"Manufacturer": "Siemens", "PhaseEncodingDirection": "j-"}
    step, ctx = build_context(ws, "dwi_topup", "sub-001", None, topup_inputs(ws, bad, None), {})
    assert [p.code for p in step.validate_inputs(ctx)] == ["DWI_ENCODING_UNKNOWN"]


def test_a_reverse_image_without_sidecar_is_taken_as_opposite(ws: Workspace) -> None:
    step, ctx = build_context(
        ws, "dwi_topup", "sub-001", None, topup_inputs(ws, SIEMENS_AP, None), {}
    )
    assert step.validate_inputs(ctx) == []


def test_mrtrix_steps_say_what_to_install_when_it_is_missing(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mrforge.steps.dwi_mrtrix.find_mrtrix", lambda: None)
    dwi = put_image(ws, "rawbids/sub-001/dwi/sub-001_dwi.nii.gz", (4, 4, 4, 2))
    for name in ("dwi_denoise", "dwi_unring"):
        step, ctx = build_context(ws, name, "sub-001", None, {"dwi": dwi}, {})
        assert [p.code for p in step.validate_inputs(ctx)] == ["MRTRIX_MISSING"]


def test_mrtrix_result_names(ws: Workspace) -> None:
    dwi = put_image(ws, "rawbids/sub-001/dwi/sub-001_dwi.nii.gz", (4, 4, 4, 2))
    names = {}
    for name in ("dwi_denoise", "dwi_unring"):
        step, ctx = build_context(ws, name, "sub-001", None, {"dwi": dwi}, {})
        names[name] = step.expected_outputs(ctx).dwi
    assert names == {
        "dwi_denoise": "sub-001_desc-denoised_dwi.nii.gz",
        "dwi_unring": "sub-001_desc-unring_dwi.nii.gz",
    }


# -- with the real tools --------------------------------------------------------------------


def fsl_or_skip() -> FslInstall:
    try:
        return find_fsl()
    except StepError as err:
        pytest.skip(f"FSL not found: {err.message}")


def real_data() -> Path:
    folder = os.environ.get("MRFORGE_DWI_TESTDATA", "/tmp/niftitry/ws/rawbids/sub-001")
    path = Path(folder)
    needed = ["dwi/sub-001_dwi.nii.gz", "dwi/sub-001_dwi.json", "dwi/sub-001_dwi.bval",
              "fmap/sub-001_dir-PA_epi.nii.gz", "fmap/sub-001_dir-PA_epi.json"]  # fmt: skip
    if not all((path / n).is_file() for n in needed):
        pytest.skip("no real diffusion test data (set MRFORGE_DWI_TESTDATA)")
    return path


def copy_real(ws: Workspace, src: Path) -> dict[str, str]:
    rels = {}
    for key, name in (("dwi", "dwi/sub-001_dwi.nii.gz"), ("dwi_json", "dwi/sub-001_dwi.json"),
                      ("dwi_bval", "dwi/sub-001_dwi.bval"),
                      ("reverse", "fmap/sub-001_dir-PA_epi.nii.gz"),
                      ("reverse_json", "fmap/sub-001_dir-PA_epi.json")):  # fmt: skip
        dest = ws.root / "rawbids/sub-001" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / name, dest)
        rels[key] = ws.relpath(dest)
    return rels


def load(path: Path) -> np.ndarray:
    return np.asarray(nib.load(str(path)).dataobj)  # type: ignore[attr-defined]


@pytest.mark.fsl
def test_topup_matches_the_commands_of_the_script(ws: Workspace, tmp_path: Path) -> None:
    fsl = fsl_or_skip()
    src = real_data()
    inputs = copy_real(ws, src)
    outcome = run_step(ws, LocalJobQueue(ws), "dwi_topup", "sub-001", inputs)
    assert outcome.action == Action.RAN, outcome.reason
    out = ws.root / "derivatives/mrforge/sub-001/dwi"

    # the same by hand, command for command as in alps.sh (lines 336-399)
    env = {**os.environ, "FSLDIR": fsl.fsldir, "FSLOUTPUTTYPE": "NIFTI_GZ"}
    env["PATH"] = f"{fsl.fsldir}/bin:{env['PATH']}"
    by = tmp_path / "manual"
    by.mkdir()

    def sh(*argv: str) -> None:
        subprocess.run(argv, cwd=by, env=env, check=True, capture_output=True)

    ap, pa = src / "dwi/sub-001_dwi.nii.gz", src / "fmap/sub-001_dir-PA_epi.nii.gz"
    sh("fslroi", str(ap), "b0_1", "0", "1")
    sh("fslroi", str(pa), "b0_2", "0", "1")
    sh("fslmerge", "-t", "both_b0", "b0_1", "b0_2")
    ap_sc = json.loads((src / "dwi/sub-001_dwi.json").read_text())
    pa_sc = json.loads((src / "fmap/sub-001_dir-PA_epi.json").read_text())
    lines = [c.read_encoding(ap_sc).line, c.read_encoding(pa_sc).line]
    (by / "acqparams.txt").write_text("\n".join(lines) + "\n")
    assert (out / "sub-001_desc-topup_acqparams.txt").read_text() == (
        by / "acqparams.txt"
    ).read_text()
    sh("topup", "--imain=both_b0", "--datain=acqparams.txt", "--config=b02b0.cnf",
       "--out=my_topup_results", "--iout=my_hifi_b0")  # fmt: skip
    sh("fslmaths", "my_hifi_b0", "-Tmean", "my_hifi_b0")
    sh("bet2", "my_hifi_b0", "b0_brain", "-m")

    assert np.allclose(load(out / "sub-001_desc-topup_b0.nii.gz"), load(by / "my_hifi_b0.nii.gz"))
    assert np.allclose(
        load(out / "sub-001_desc-topup_fieldcoef.nii.gz"),
        load(by / "my_topup_results_fieldcoef.nii.gz"),
    )
    assert np.array_equal(
        load(out / "sub-001_desc-topup_mask.nii.gz"), load(by / "b0_brain_mask.nii.gz")
    )

    # run again with nothing changed: nothing is repeated
    again = run_step(ws, LocalJobQueue(ws), "dwi_topup", "sub-001", inputs)
    assert again.action == Action.REUSED


@pytest.mark.fsl
def test_mrtrix_steps_match_manual_runs(ws: Workspace, tmp_path: Path) -> None:
    fsl_or_skip()
    install = find_mrtrix()
    if install is None:
        pytest.skip("MRtrix3 is not installed")
    src = real_data()
    inputs = copy_real(ws, src)
    q = LocalJobQueue(ws)
    first = run_step(ws, q, "dwi_denoise", "sub-001", {"dwi": inputs["dwi"]})
    assert first.action == Action.RAN, first.reason
    out = ws.root / "derivatives/mrforge/sub-001/dwi"
    den = out / "sub-001_desc-denoised_dwi.nii.gz"
    second = run_step(ws, q, "dwi_unring", "sub-001", {"dwi": ws.relpath(den)})
    assert second.action == Action.RAN, second.reason

    manual_den = tmp_path / "den.nii.gz"
    manual_unr = tmp_path / "unr.nii.gz"
    ap = src / "dwi/sub-001_dwi.nii.gz"
    subprocess.run(
        [str(install.dwidenoise), str(ap), str(manual_den)], check=True, capture_output=True
    )
    subprocess.run(
        [str(install.mrdegibbs), str(manual_den), str(manual_unr)], check=True, capture_output=True
    )
    assert np.allclose(load(den), load(manual_den))
    assert np.allclose(load(out / "sub-001_desc-unring_dwi.nii.gz"), load(manual_unr))
