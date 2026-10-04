"""Writing FEAT's ``design.fsf`` for preprocessing only (no statistics).

FEAT reads all of its settings from this file, so a faithful, deterministic design file is
both the parameter record of a run and a way to reproduce it by hand: open it in the FEAT
GUI (File > Load) and press Go. Key names and meanings come from FSL's own FEAT code
(``$FSLDIR/tcl/featlib.tcl``) and from a design file produced by the FEAT GUI.

Only the keys FEAT needs for "Pre-stats" (analysis mode 1) are written. A design with these
keys gave bit-identical results to the full GUI-generated design on a test run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# BIDS gives the phase-encoding direction along the image axes (i, j, k, optionally with a
# minus sign); FEAT/fugue take x, y, z in the same voxel axes.  REVIEW(domain): confirm the
# sign convention on your scanner's data (the unwarped result should look less stretched).
BIDS_TO_FEAT_DIRECTION = {"i": "x", "i-": "x-", "j": "y", "j-": "y-", "k": "z", "k-": "z-"}


class FeatDesign(BaseModel):
    """Everything that goes into a pre-stats design file. Paths are absolute; image paths
    are written without extension, as FEAT's own GUI does."""

    outputdir: str  # FEAT creates "<outputdir>.feat"
    func: str  # 4D BOLD image
    tr_s: float = Field(gt=0)
    volumes: int = Field(ge=2)  # in the input, before any are deleted
    voxels_per_volume: int = Field(ge=1)
    delete_volumes: int = Field(default=5, ge=0)  # REVIEW(domain): proposal, confirmed 5
    motion_correction: bool = True
    slice_timing: Literal["none", "file"] = "none"
    slice_timing_file: str | None = None  # slicetimer --tcustom file: fractions of TR
    # REVIEW(domain): how BIDS SliceTiming (seconds) maps to this file and its sign.
    brain_extraction: bool = True
    # REVIEW(domain): 5 mm FWHM and 150 s high-pass are proposals; 0 smoothing = off.
    smoothing_fwhm_mm: float = Field(default=5.0, ge=0)
    intensity_normalisation: bool = False  # REVIEW(domain)
    highpass_cutoff_s: float | None = 150.0  # None switches temporal filtering off
    # B0 unwarping with a processed fieldmap (fsl_prepare_fieldmap output).
    fieldmap_rads: str | None = None
    fieldmap_magnitude_brain: str | None = None
    epi_te_ms: float | None = None
    dwell_ms: float | None = None  # effective echo spacing in ms
    unwarp_direction: str | None = None  # x, y, z with optional minus sign
    signal_loss_threshold_pct: int = 10
    # Registration to the structural image (the fsl_anat brain). Standard space is left to
    # MRForge's own step, which reuses the fsl_anat warp.
    highres_brain: str | None = None
    registration_search_deg: int = 90
    highres_dof: Literal["BBR", "3", "6", "7", "9", "12"] = "BBR"  # REVIEW(domain)
    standard_brain: str = ""  # only written, never used (standard-space registration is off)

    @model_validator(mode="after")
    def _consistent(self) -> FeatDesign:
        if self.delete_volumes >= self.volumes:
            raise ValueError("cannot delete all volumes")
        unwarp = [self.fieldmap_rads, self.fieldmap_magnitude_brain]
        if any(unwarp) and not all(unwarp):
            raise ValueError("unwarping needs both the fieldmap and its brain magnitude image")
        if self.fieldmap_rads is not None:
            if not (self.highres_brain and self.epi_te_ms and self.dwell_ms):
                raise ValueError("unwarping needs a structural image, the EPI TE and dwell time")
            if self.unwarp_direction not in set(BIDS_TO_FEAT_DIRECTION.values()):
                raise ValueError("unwarping needs the phase-encoding direction (x, y, z, ...)")
        if self.slice_timing == "file" and not self.slice_timing_file:
            raise ValueError("slice timing needs a timing file")
        return self


def _q(value: str) -> str:
    return '"' + value.replace('"', "") + '"'


def _flag(value: bool) -> str:
    return "1" if value else "0"


def write_design(d: FeatDesign) -> str:
    """The design.fsf text for ``d`` (deterministic: the same input always gives the same text)."""
    unwarp = d.fieldmap_rads is not None
    register = d.highres_brain is not None
    rows: list[tuple[str, str]] = [
        ("fmri(version)", "6.00"),
        ("fmri(inmelodic)", "0"),
        ("fmri(level)", "1"),
        ("fmri(analysis)", "1"),  # 1 = Pre-stats only
        ("fmri(relative_yn)", "0"),
        ("fmri(help_yn)", "1"),
        ("fmri(featwatcher_yn)", "0"),
        ("fmri(sscleanup_yn)", "0"),
        ("fmri(outputdir)", _q(d.outputdir)),
        ("fmri(tr)", f"{d.tr_s:.6f}"),
        ("fmri(npts)", str(d.volumes)),
        ("fmri(ndelete)", str(d.delete_volumes)),
        ("fmri(tagfirst)", "1"),
        ("fmri(multiple)", "1"),
        ("fmri(inputtype)", "2"),
        ("fmri(filtering_yn)", "1"),
        ("fmri(brain_thresh)", "10"),
        ("fmri(critical_z)", "5.3"),
        ("fmri(noise)", "0.66"),
        ("fmri(noisear)", "0.34"),
        ("fmri(mc)", _flag(d.motion_correction)),
        ("fmri(sh_yn)", "0"),
        ("fmri(regunwarp_yn)", _flag(unwarp)),
        ("fmri(dwell)", f"{d.dwell_ms:g}" if d.dwell_ms else "0.7"),
        ("fmri(te)", f"{d.epi_te_ms:g}" if d.epi_te_ms else "35"),
        ("fmri(signallossthresh)", str(d.signal_loss_threshold_pct)),
        ("fmri(unwarp_dir)", d.unwarp_direction or "y-"),
        ("fmri(st)", "0" if d.slice_timing == "none" else "4"),  # 4 = slice timings file
        ("fmri(st_file)", _q(d.slice_timing_file or "")),
        ("fmri(bet_yn)", _flag(d.brain_extraction)),
        ("fmri(smooth)", f"{d.smoothing_fwhm_mm:g}"),
        ("fmri(norm_yn)", _flag(d.intensity_normalisation)),
        ("fmri(perfsub_yn)", "0"),
        ("fmri(temphp_yn)", _flag(d.highpass_cutoff_s is not None)),
        ("fmri(templp_yn)", "0"),
        ("fmri(melodic_yn)", "0"),
        ("fmri(stats_yn)", "0"),
        ("fmri(poststats_yn)", "0"),
        ("fmri(reginitial_highres_yn)", "0"),
        ("fmri(reginitial_highres_search)", "90"),
        ("fmri(reginitial_highres_dof)", "3"),
        ("fmri(reghighres_yn)", _flag(register)),
        ("fmri(reghighres_search)", str(d.registration_search_deg)),
        ("fmri(reghighres_dof)", "BBR" if unwarp else d.highres_dof),  # FEAT forces BBR to unwarp
        ("fmri(regstandard_yn)", "0"),
        ("fmri(alternateReference_yn)", "0"),
        ("fmri(regstandard)", _q(d.standard_brain)),
        ("fmri(regstandard_search)", "90"),
        ("fmri(regstandard_dof)", "12"),
        ("fmri(regstandard_nonlinear_yn)", "0"),
        ("fmri(regstandard_nonlinear_warpres)", "10"),
        ("fmri(paradigm_hp)", f"{d.highpass_cutoff_s or 100:g}"),
        ("fmri(totalVoxels)", str(d.voxels_per_volume * d.volumes)),
        ("fmri(ncopeinputs)", "0"),
        ("feat_files(1)", _q(d.func)),
    ]
    if unwarp:
        rows += [
            ("unwarp_files(1)", _q(d.fieldmap_rads or "")),
            ("unwarp_files_mag(1)", _q(d.fieldmap_magnitude_brain or "")),
        ]
    if register:
        rows.append(("highres_files(1)", _q(d.highres_brain or "")))
    rows += [
        ("fmri(alternative_mask)", '""'),
        ("fmri(init_initial_highres)", '""'),
        ("fmri(init_highres)", '""'),
        ("fmri(init_standard)", '""'),
        ("fmri(overwrite_yn)", "0"),
    ]
    header = "# FEAT version 6.00 pre-stats design, written by MRForge.\n"
    header += "# Open it in the FEAT GUI (File > Load) to reproduce the run by hand.\n\n"
    return header + "".join(f"set {k} {v}\n" for k, v in rows)
