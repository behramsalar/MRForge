"""Stage 5a: writing FEAT's design.fsf for preprocessing only."""

import pytest
from pydantic import ValidationError

from mrforge.steps.feat_design import BIDS_TO_FEAT_DIRECTION, FeatDesign, write_design


def design(**kw: object) -> FeatDesign:
    base: dict[str, object] = {
        "outputdir": "/w/sub-001_task-rest_desc-feat",
        "func": "/w/rawbids/sub-001/func/sub-001_task-rest_bold",
        "tr_s": 2.0,
        "volumes": 360,
        "voxels_per_volume": 74 * 74 * 62,
    }
    return FeatDesign(**{**base, **kw})


def keys(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("set "):
            _, key, value = line.split(" ", 2)
            found[key] = value
    return found


def test_defaults_are_the_confirmed_proposals() -> None:
    k = keys(write_design(design()))
    assert k["fmri(analysis)"] == "1"  # pre-stats only: no statistics
    assert k["fmri(ndelete)"] == "5"
    assert k["fmri(smooth)"] == "5"
    assert k["fmri(temphp_yn)"] == "1" and k["fmri(paradigm_hp)"] == "150"
    assert k["fmri(mc)"] == "1" and k["fmri(bet_yn)"] == "1"
    assert k["fmri(st)"] == "0" and k["fmri(regunwarp_yn)"] == "0"
    assert k["fmri(regstandard_yn)"] == "0"  # standard space is MRForge's own step
    assert k["fmri(reghighres_yn)"] == "0"  # no structural image given
    assert k["fmri(npts)"] == "360" and k["fmri(totalVoxels)"] == str(74 * 74 * 62 * 360)
    assert k["fmri(tr)"] == "2.000000"


def test_same_input_gives_same_text() -> None:
    assert write_design(design()) == write_design(design())


def test_filtering_can_be_switched_off() -> None:
    k = keys(write_design(design(highpass_cutoff_s=None, smoothing_fwhm_mm=0)))
    assert k["fmri(temphp_yn)"] == "0" and k["fmri(smooth)"] == "0"


def test_registration_to_the_structural_image() -> None:
    k = keys(write_design(design(highres_brain="/w/anat/T1_biascorr_brain")))
    assert k["fmri(reghighres_yn)"] == "1" and k["fmri(reghighres_dof)"] == "BBR"
    assert k["highres_files(1)"] == '"/w/anat/T1_biascorr_brain"'
    assert "unwarp_files(1)" not in k


def test_unwarping_adds_fieldmap_files_and_forces_bbr() -> None:
    k = keys(
        write_design(
            design(
                highres_brain="/w/anat/T1_biascorr_brain",
                highres_dof="12",
                fieldmap_rads="/w/fmap/fmap_rads",
                fieldmap_magnitude_brain="/w/fmap/mag_brain",
                epi_te_ms=30.0,
                dwell_ms=0.3,
                unwarp_direction=BIDS_TO_FEAT_DIRECTION["j-"],
            )
        )
    )
    assert k["fmri(regunwarp_yn)"] == "1" and k["fmri(unwarp_dir)"] == "y-"
    assert k["fmri(dwell)"] == "0.3" and k["fmri(te)"] == "30"
    assert k["unwarp_files(1)"] == '"/w/fmap/fmap_rads"'
    assert k["unwarp_files_mag(1)"] == '"/w/fmap/mag_brain"'
    assert k["fmri(reghighres_dof)"] == "BBR"  # FEAT registers with BBR when unwarping


@pytest.mark.parametrize(
    "bad",
    [
        {"fieldmap_rads": "/f", "fieldmap_magnitude_brain": "/m", "epi_te_ms": 30.0,
         "dwell_ms": 0.3, "unwarp_direction": "y-"},  # no structural image to register to
        {"fieldmap_rads": "/f", "highres_brain": "/t1", "epi_te_ms": 30.0, "dwell_ms": 0.3,
         "unwarp_direction": "y-"},  # magnitude missing
        {"fieldmap_rads": "/f", "fieldmap_magnitude_brain": "/m", "highres_brain": "/t1",
         "epi_te_ms": 30.0, "dwell_ms": 0.3},  # direction missing
        {"delete_volumes": 360},
        {"slice_timing": "file"},
        {"tr_s": 0},
    ],
)  # fmt: skip
def test_inconsistent_designs_are_refused(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        design(**bad)


def test_direction_names_follow_the_image_axes() -> None:
    assert BIDS_TO_FEAT_DIRECTION == {
        "i": "x", "i-": "x-", "j": "y", "j-": "y-", "k": "z", "k-": "z-",
    }  # fmt: skip
