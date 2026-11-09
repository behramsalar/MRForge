"""Functional preprocessing for one BOLD run: what is possible, and the pipeline to run.

The UI asks ``check_ready`` (which results and fieldmap exist, and why something is not
possible) and sends the chosen options to ``build_pipeline``. The pipeline is an ordinary
``PipelineSpec`` of separate steps, so resume, provenance and live status work as for any
other pipeline: ``fieldmap_prep`` (when a usable fieldmap exists), ``feat_preproc``,
``func_qc`` and ``func_to_mni``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mrforge.errors import StepError
from mrforge.pipeline import PipelineSpec, PipelineStep
from mrforge.steps.feat_design import BIDS_TO_FEAT_DIRECTION
from mrforge.steps.fsl_anat import STANDARD_SPACE
from mrforge.steps.sidecar import read_sidecar
from mrforge.workspace import Workspace

# What the functional steps need from fsl_anat (file name endings in the anat results folder).
ANAT_FILES = {
    "t1_head": "_desc-biascorr_T1w.nii.gz",
    "t1_brain": "_desc-brain_T1w.nii.gz",
    "t1_seg": "_dseg.nii.gz",
    "t1_to_mni_warp": f"_from-T1w_to-{STANDARD_SPACE}_mode-image_desc-fnirtcoeff_xfm.nii.gz",
}


class FunctionalOptions(BaseModel):
    subject: str
    bold: str  # workspace-relative path of the raw BOLD image
    session: str | None = None
    # REVIEW(domain): 5 volumes (confirmed); 5 mm FWHM and 150 s high-pass are proposals.
    delete_volumes: int = Field(default=5, ge=0, le=100)
    smoothing_fwhm_mm: float = Field(default=5.0, ge=0, le=20)
    highpass_cutoff_s: float | None = Field(default=150.0, gt=0)  # None: no temporal filtering
    use_fieldmap: bool = True  # only honoured when a usable fieldmap exists
    to_mni: bool = True  # also resample the result into MNI space
    slice_timing: bool = False  # slice timing correction (off by default)


class FieldmapStatus(BaseModel):
    available: bool
    reason: str | None = None  # why not, in plain language
    magnitude1: str | None = None
    phasediff: str | None = None


class SliceTimingStatus(BaseModel):
    available: bool
    reason: str | None = None


class RunStatus(BaseModel):
    bold: str
    name: str  # e.g. "task-rest" or "task-rest run-1"
    volumes: int | None = None
    fieldmap: FieldmapStatus
    slice_timing: SliceTimingStatus


class Readiness(BaseModel):
    subject: str
    anat_ready: bool
    anat_reason: str | None = None
    runs: list[RunStatus]


def _subject_dir(ws: Workspace, root: str, subject: str, session: str | None) -> Path:
    """The subject's folder in ``rawbids`` or in the derivatives dataset."""
    parts = [subject] + ([session] if session else [])
    base = ws.root / "rawbids" if root == "rawbids" else ws.derivatives_dir
    return base.joinpath(*parts)


def anat_results(ws: Workspace, subject: str, session: str | None) -> dict[str, str] | None:
    """Workspace-relative paths of the fsl_anat results the functional steps use, or None."""
    folder = _subject_dir(ws, "derivatives", subject, session) / "anat"
    found: dict[str, str] = {}
    for key, ending in ANAT_FILES.items():
        matches = sorted(
            p
            for p in folder.glob(f"*{ending}")
            if "space-" not in p.name or key == "t1_to_mni_warp"
        )
        if not matches:
            return None
        found[key] = ws.relpath(matches[0])
    return found


def _volumes(ws: Workspace, bold_rel: str) -> int | None:
    from mrforge.niftiutil import image_info

    try:
        shape = image_info(ws.abspath(bold_rel))[0]
    except Exception:  # unreadable image: reported when the step validates it
        return None
    return shape[3] if len(shape) == 4 else None


def fieldmap_status(ws: Workspace, bold_rel: str) -> FieldmapStatus:
    """Whether a Siemens-style gradient-echo fieldmap (two magnitudes plus a phase difference)
    exists for this run, and everything FEAT needs to use it."""
    bold = Path(bold_rel)
    func_dir = ws.abspath(bold_rel).parent
    fmap_dir = func_dir.parent / "fmap"
    # BIDS IntendedFor names the run relative to the subject folder (drop "rawbids/<sub>")
    intended_name = "/".join(bold.parts[2:])
    phasediffs = sorted(fmap_dir.glob("*_phasediff.json")) if fmap_dir.is_dir() else []
    chosen: Path | None = None
    for sidecar in phasediffs:
        try:
            data = json.loads(sidecar.read_text())
        except (OSError, ValueError):
            continue
        targets = data.get("IntendedFor") or []
        if isinstance(targets, str):
            targets = [targets]
        if intended_name in targets:
            chosen = sidecar
            break
    if chosen is None:
        other = fmap_dir.is_dir() and any(
            fmap_dir.glob("*_fieldmap.nii.gz")
        )  # a ready-made fieldmap in Hz (for example Philips B0 maps)
        reason = (
            "This fieldmap type is not supported yet (only Siemens gradient-echo field maps)."
            if other
            else "No fieldmap was acquired for this run."
        )
        return FieldmapStatus(available=False, reason=reason)
    base = chosen.name.removesuffix("_phasediff.json")
    phase = fmap_dir / f"{base}_phasediff.nii.gz"
    mag = fmap_dir / f"{base}_magnitude1.nii.gz"
    if not phase.is_file() or not mag.is_file():
        return FieldmapStatus(available=False, reason="The fieldmap images are incomplete.")
    side = read_sidecar(ws, bold_rel)
    missing = []
    if side.get("PhaseEncodingDirection") not in BIDS_TO_FEAT_DIRECTION:
        missing.append("phase-encoding direction")
    if not isinstance(side.get("EffectiveEchoSpacing"), int | float):
        missing.append("effective echo spacing")
    if not isinstance(side.get("EchoTime"), int | float):
        missing.append("echo time")
    if missing:
        return FieldmapStatus(
            available=False,
            reason="This scan does not record its "
            + ", ".join(missing)
            + ", which distortion correction needs.",
        )
    return FieldmapStatus(available=True, magnitude1=ws.relpath(mag), phasediff=ws.relpath(phase))


def slice_timing_status(ws: Workspace, bold_rel: str) -> SliceTimingStatus:
    """Slice timing correction needs one acquisition time per slice in the scan's sidecar."""
    from mrforge.niftiutil import image_info

    side = read_sidecar(ws, bold_rel)
    times = side.get("SliceTiming")
    if not isinstance(times, list) or not times:
        return SliceTimingStatus(
            available=False, reason="This scan does not record its slice times."
        )
    try:
        slices = image_info(ws.abspath(bold_rel))[0][2]
    except Exception:
        return SliceTimingStatus(available=False, reason="The image could not be read.")
    if len(times) != slices or side.get("SliceEncodingDirection", "k") not in ("k", "k-"):
        return SliceTimingStatus(
            available=False, reason="The recorded slice times do not match the image layout."
        )
    return SliceTimingStatus(available=True)


def check_ready(ws: Workspace, subject: str, session: str | None = None) -> Readiness:
    func_dir = _subject_dir(ws, "rawbids", subject, session) / "func"
    runs: list[RunStatus] = []
    for image in sorted(func_dir.glob("*_bold.nii.gz")) if func_dir.is_dir() else []:
        rel = ws.relpath(image)
        label = image.name.removesuffix("_bold.nii.gz").split("_", 1)[-1].replace("_", " ")
        runs.append(
            RunStatus(
                bold=rel,
                name=label,
                volumes=_volumes(ws, rel),
                fieldmap=fieldmap_status(ws, rel),
                slice_timing=slice_timing_status(ws, rel),
            )
        )
    anat = anat_results(ws, subject, session)
    return Readiness(
        subject=subject,
        anat_ready=anat is not None,
        anat_reason=None if anat else "Anatomical processing has not finished for this subject.",
        runs=runs,
    )


def build_pipeline(ws: Workspace, opts: FunctionalOptions) -> PipelineSpec:
    """The steps to run for one BOLD run with the chosen options (all separate steps)."""
    if not ws.abspath(opts.bold).is_file() or not opts.bold.startswith("rawbids/"):
        raise StepError(
            code="UNKNOWN_FILE",
            message="That functional image was not found in the workspace.",
            suggested_action="Import the scan first, then choose the run again.",
        )
    anat = anat_results(ws, opts.subject, opts.session)
    if anat is None:
        raise StepError(
            code="ANAT_NOT_READY",
            message="Anatomical processing has not finished for this subject.",
            probable_cause="Functional preprocessing registers the scan to the T1 and to "
            "standard space, using the anatomical results.",
            suggested_action="Run anatomical processing first.",
        )
    fmap = fieldmap_status(ws, opts.bold)
    if opts.use_fieldmap and not fmap.available:
        raise StepError(
            code="FIELDMAP_UNAVAILABLE",
            message="Distortion correction was requested, but it is not possible here.",
            probable_cause=fmap.reason or "",
            suggested_action="Turn distortion correction off, or add the missing information.",
        )
    if opts.slice_timing and not slice_timing_status(ws, opts.bold).available:
        raise StepError(
            code="SLICE_TIMING_UNAVAILABLE",
            message="Slice timing correction was requested, but it is not possible here.",
            probable_cause=slice_timing_status(ws, opts.bold).reason or "",
            suggested_action="Turn slice timing correction off.",
        )
    stem = Path(opts.bold).name.removesuffix("_bold.nii.gz")
    steps: list[PipelineStep] = []

    def add(step: str, inputs: dict[str, Any], params: dict[str, Any] | None = None) -> None:
        steps.append(
            PipelineStep(
                id=step, step=step, session=opts.session, inputs=inputs, params=params or {}
            )
        )

    feat_inputs: dict[str, Any] = {
        "bold": opts.bold,
        "t1_head": anat["t1_head"],
        "t1_brain": anat["t1_brain"],
        "t1_seg": anat["t1_seg"],
    }
    if opts.use_fieldmap:
        assert fmap.magnitude1 and fmap.phasediff
        add("fieldmap_prep", {"magnitude1": fmap.magnitude1, "phasediff": fmap.phasediff})
        feat_inputs |= {
            "fieldmap": "${fieldmap_prep.fieldmap}",
            "fieldmap_magnitude_brain": "${fieldmap_prep.magnitude_brain}",
            "fieldmap_magnitude": fmap.magnitude1,
        }
    add(
        "feat_preproc",
        feat_inputs,
        {
            "delete_volumes": opts.delete_volumes,
            "smoothing_fwhm_mm": opts.smoothing_fwhm_mm,
            "highpass_cutoff_s": opts.highpass_cutoff_s,
            "slice_timing": opts.slice_timing,
        },
    )
    qc_inputs: dict[str, Any] = {
        "motion": "${feat_preproc.motion}",
        "boldref_t1": "${feat_preproc.boldref_t1}",
        "t1_head": anat["t1_head"],
        "t1_seg": anat["t1_seg"],
    }
    qc_inputs["bold"] = "${feat_preproc.preproc_bold}"
    qc_inputs["brain_mask"] = "${feat_preproc.brain_mask}"
    if opts.use_fieldmap:
        qc_inputs["boldref_distorted_t1"] = "${feat_preproc.boldref_distorted_t1}"
    add("func_qc", qc_inputs)
    if opts.to_mni:
        add(
            "func_to_mni",
            {
                "bold": "${feat_preproc.preproc_bold}",
                "to_t1_affine": "${feat_preproc.to_t1_affine}",
                "t1_to_mni_warp": anat["t1_to_mni_warp"],
                "brain_mask": "${feat_preproc.brain_mask}",
            },
        )
    return PipelineSpec(name=f"functional-{stem}", subject=opts.subject, steps=steps)
