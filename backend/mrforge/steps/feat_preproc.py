"""Functional preprocessing with FSL FEAT (pre-stats only).

MRForge writes a ``design.fsf`` (see ``feat_design.py``), runs ``feat`` on it and keeps FEAT's
own folder (``<name>.feat``, like ``.anat`` for ``fsl_anat``). FEAT does motion correction,
brain extraction, B0 unwarping with a prepared fieldmap, smoothing, temporal filtering and
registration to the structural image. Standard-space registration is left to the
``func_to_mni`` step, which reuses the ``fsl_anat`` warp.

Inputs for FEAT are staged under FEAT's own naming conventions (``<name>_brain``,
``<name>`` for the whole head, ``<name>_wmseg``, ``fmap_mag_brain`` / ``fmap_mag``), because
FEAT finds the whole-head and white-matter images by those names.
"""

from __future__ import annotations

import html
import os
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from mrforge.bids import split_extension
from mrforge.errors import StepError
from mrforge.layout import placed
from mrforge.niftiutil import image_info, is_readable_nifti
from mrforge.steps.base import Problem, Step, StepContext, StepResult
from mrforge.steps.feat_design import BIDS_TO_FEAT_DIRECTION, FeatDesign, write_design
from mrforge.steps.registry import register_step
from mrforge.steps.sidecar import read_sidecar

WM_LABEL = 3  # label of white matter in the fsl_anat segmentation (1 CSF, 2 GM, 3 WM)


class FeatPreprocInput(BaseModel):
    bold: str  # raw 4D BOLD image
    # Structural images from fsl_anat (all three, or none: then no registration is done).
    t1_head: str | None = None  # bias-corrected whole head
    t1_brain: str | None = None  # bias-corrected brain
    t1_seg: str | None = None  # tissue segmentation (1 CSF, 2 GM, 3 WM)
    # Prepared fieldmap (all three, or none: then no distortion correction is done).
    fieldmap: str | None = None  # rad/s, from fieldmap_prep
    fieldmap_magnitude_brain: str | None = None
    fieldmap_magnitude: str | None = None  # whole-head first magnitude image


class FeatPreprocParams(BaseModel):
    # REVIEW(domain): 5 volumes discarded (confirmed), 5 mm FWHM smoothing and a 150 s
    # high-pass (proposals), both applied inside FEAT before any cleanup.
    delete_volumes: int = Field(default=5, ge=0)
    smoothing_fwhm_mm: float = Field(default=5.0, ge=0, le=20)  # 0 = no smoothing
    highpass_cutoff_s: float | None = Field(default=150.0, gt=0)  # None = no temporal filtering
    motion_correction: bool = True
    brain_extraction: bool = True
    # Off by default. Needs the scan's slice times (BIDS SliceTiming); REVIEW(domain): with
    # fast multiband acquisitions it usually changes little.
    slice_timing: bool = False
    intensity_normalisation: bool = False  # REVIEW(domain): FEAT's 4D grand-mean scaling
    signal_loss_threshold_pct: int = Field(default=10, ge=0, le=100)  # REVIEW(domain)
    registration_dof: str = "BBR"  # REVIEW(domain): BBR, or 3/6/7/9/12 degrees of freedom


class FeatPreprocOutput(BaseModel):
    """Key results with BIDS names, next to the native ``.feat`` folder (which is not listed:
    it is a folder, and the files below are hard links into it)."""

    preproc_bold: str
    brain_mask: str
    boldref: str  # the example volume FEAT registers (middle volume, native space)
    motion: (
        str | None
    )  # six realignment parameters per volume (TSV; None without motion correction)
    to_t1_affine: str | None = None  # boldref -> T1 (FSL matrix); the fieldmap is applied apart
    to_t1_warp: str | None = None  # boldref -> T1 warp that includes the distortion correction
    boldref_t1: str | None = None  # boldref resampled into T1 space (for QC and the viewer)
    boldref_distorted_t1: str | None = None  # the same without distortion correction


def slice_timing_fractions(times_s: list[float], tr_s: float) -> list[float]:
    """The value per slice that FSL's ``slicetimer --tcustom`` (and FEAT's "slice timings
    file") expects, from BIDS ``SliceTiming`` (seconds after the start of the volume).

    Checked on synthetic data with known per-slice delays: the file must hold the NEGATIVE of
    each slice's acquisition time as a fraction of TR (a slice taken later is shifted back).
    The reference is the middle of the TR (0.5 minus t/TR), as for FEAT's other options.
    REVIEW(domain): the reference time (middle of the TR) is a choice.
    """
    return [0.5 - t / tr_s for t in times_s]


def native_folder_name(bold_relpath: str) -> str:
    """FEAT's own folder: the BOLD name without extension, plus '.feat'."""
    return placed(split_extension(bold_relpath.rsplit("/", 1)[-1])[0] + ".feat", "func")


# Known FEAT failure messages -> plain language. The first match wins.
FEAT_ERRORS: list[tuple[str, str, str, str]] = [
    (
        "still contain non-brain voxels",
        "FEAT_FIELDMAP_NOT_BRAIN_EXTRACTED",
        "The fieldmap magnitude image still contains the skull.",
        "Prepare the fieldmap again with a higher brain-extraction fraction, or choose to "
        "run without distortion correction.",
    ),
    (
        "Problem with FEAT",
        "FEAT_BAD_INPUT",
        "FEAT could not use one of its input images.",
        "Check that the images open in FSLeyes, then run again.",
    ),
    (
        "No such file or directory",
        "FEAT_FILE_MISSING",
        "FEAT could not find a file it needs.",
        "Run the step again; if it keeps failing, open the log and report the missing file.",
    ),
]


def _plain_text(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", page))


def _feat_log_tail(feat_dir: Path, lines: int = 12) -> str:
    log = feat_dir / "report_log.html"
    try:
        text = _plain_text(log.read_text(errors="replace"))
    except OSError:
        return ""
    kept = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(kept[-lines:])


def _explain_failure(feat_dir: Path, stderr_path: Path) -> StepError:
    tail = _feat_log_tail(feat_dir)
    for needle, code, cause, action in FEAT_ERRORS:
        if needle in tail:
            return StepError(
                code=code,
                message="FEAT stopped before it finished the preprocessing.",
                probable_cause=cause,
                suggested_action=action,
                log_path=stderr_path,
            )
    return StepError(
        code="FEAT_FAILED",
        message="FEAT stopped before it finished the preprocessing.",
        probable_cause="The data may be unsuitable, or one of FEAT's tools hit a problem. "
        + (f"The last lines of its log say: {tail.splitlines()[-1]}" if tail else ""),
        suggested_action="Open the raw log for details, then fix the input and retry.",
        log_path=stderr_path,
    )


@register_step
class FeatPreprocStep(Step[FeatPreprocInput, FeatPreprocParams, FeatPreprocOutput]):
    name = "feat_preproc"
    version = "3"  # 3: optional slice timing; 2: example volume in T1 space (and distorted twin)
    InputSpec, ParamSpec, OutputSpec = FeatPreprocInput, FeatPreprocParams, FeatPreprocOutput
    requires_fsl = True
    datatype = "func"

    # -- helpers ------------------------------------------------------------

    def expected_outputs(
        self, ctx: StepContext[FeatPreprocInput, FeatPreprocParams]
    ) -> FeatPreprocOutput:
        n = ctx.bids_name
        registered = ctx.inputs.t1_brain is not None
        unwarped = ctx.inputs.fieldmap is not None

        def xfm(desc: str, ext: str) -> str:
            return n("xfm", ext, **{"from": "boldref", "to": "T1w", "mode": "image", "desc": desc})

        return FeatPreprocOutput(
            preproc_bold=n("bold", desc=self.desc(ctx, "preproc")),
            brain_mask=n("mask", desc=self.desc(ctx, "brain")),
            boldref=n("boldref", desc=self.desc(ctx, "feat")),
            motion=(
                n("timeseries", ".tsv", desc=self.desc(ctx, "motion"))
                if ctx.params.motion_correction
                else None
            ),
            to_t1_affine=xfm("affine", ".mat") if registered else None,
            to_t1_warp=xfm("warp", ".nii.gz") if registered and unwarped else None,
            boldref_t1=n("boldref", space="T1w", desc=self.desc(ctx, "feat"))
            if registered
            else None,
            boldref_distorted_t1=(
                n("boldref", space="T1w", desc=self.desc(ctx, "distorted"))
                if registered and unwarped
                else None
            ),
        )

    def _tr_s(self, ctx: StepContext[FeatPreprocInput, FeatPreprocParams]) -> float:
        """Repetition time in seconds: the sidecar value, else the NIfTI header's."""
        tr = read_sidecar(ctx.workspace, ctx.inputs.bold).get("RepetitionTime")
        if isinstance(tr, int | float):
            return float(tr)
        return image_info(ctx.input_path(ctx.inputs.bold))[1][3]

    def _design(
        self, ctx: StepContext[FeatPreprocInput, FeatPreprocParams], stage: Path
    ) -> FeatDesign:
        """The FEAT design for this run; ``stage`` holds the renamed structural/fieldmap files."""
        i, p = ctx.inputs, ctx.params
        bold = ctx.input_path(i.bold)
        shape, _ = image_info(bold)
        side = read_sidecar(ctx.workspace, i.bold)
        tr_s = self._tr_s(ctx)
        kw: dict[str, object] = {}
        if i.t1_brain is not None:
            kw["highres_brain"] = str(stage / "T1_brain")
        if i.fieldmap is not None:
            dwell = side.get("EffectiveEchoSpacing")
            te = side.get("EchoTime")
            direction = BIDS_TO_FEAT_DIRECTION.get(str(side.get("PhaseEncodingDirection")))
            kw.update(
                fieldmap_rads=str(stage / "fmap_rads"),
                fieldmap_magnitude_brain=str(stage / "fmap_mag_brain"),
                dwell_ms=float(dwell) * 1000.0 if isinstance(dwell, int | float) else None,
                epi_te_ms=float(te) * 1000.0 if isinstance(te, int | float) else None,
                unwarp_direction=direction,
            )
        if p.slice_timing:
            kw.update(slice_timing="file", slice_timing_file=str(stage / "slice_timing.txt"))
        return FeatDesign(
            outputdir=str(ctx.run_dir / "work" / "feat" / "result"),
            func=str(bold).removesuffix(".gz").removesuffix(".nii"),
            tr_s=tr_s,
            volumes=int(shape[3]),
            voxels_per_volume=int(shape[0] * shape[1] * shape[2]),
            delete_volumes=p.delete_volumes,
            motion_correction=p.motion_correction,
            brain_extraction=p.brain_extraction,
            smoothing_fwhm_mm=p.smoothing_fwhm_mm,
            intensity_normalisation=p.intensity_normalisation,
            highpass_cutoff_s=p.highpass_cutoff_s,
            signal_loss_threshold_pct=p.signal_loss_threshold_pct,
            highres_dof=p.registration_dof,  # type: ignore[arg-type]
            standard_brain=str(ctx.workspace.root / "unused_standard_brain"),
            **kw,  # type: ignore[arg-type]
        )

    # -- validation ---------------------------------------------------------

    def validate_inputs(
        self, ctx: StepContext[FeatPreprocInput, FeatPreprocParams]
    ) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        i = ctx.inputs
        anat = [i.t1_head, i.t1_brain, i.t1_seg]
        fmap = [i.fieldmap, i.fieldmap_magnitude_brain, i.fieldmap_magnitude]
        for group, label in ((anat, "structural (T1)"), (fmap, "fieldmap")):
            if any(group) and not all(group):
                problems.append(
                    Problem(
                        code="FEAT_INPUTS_INCOMPLETE",
                        message=f"The {label} images are only partly given.",
                        probable_cause="All of them are needed together.",
                        suggested_action="Provide all of them, or none.",
                    )
                )
        if any(fmap) and not any(anat):
            problems.append(
                Problem(
                    code="FEAT_FIELDMAP_NEEDS_T1",
                    message="Distortion correction needs the structural (T1) result.",
                    probable_cause="FEAT corrects the distortion while registering to the T1.",
                    suggested_action="Run anatomical processing first.",
                )
            )
        if " " in str(ctx.run_dir):
            problems.append(
                Problem(
                    code="FEAT_PATH_HAS_SPACES",
                    message="FEAT cannot work in a folder whose path contains spaces.",
                    probable_cause="FEAT's own scripts do not handle spaces in file paths.",
                    suggested_action="Create the workspace in a folder without spaces in its path.",
                )
            )
        if problems:
            return problems
        if not is_readable_nifti(ctx.input_path(i.bold)):
            return [
                Problem(
                    code="INPUT_NOT_NIFTI",
                    message=f"The BOLD image could not be read: {i.bold}",
                    probable_cause="The file is damaged, incomplete or not a NIfTI image.",
                    suggested_action="Check that it opens in FSLeyes, or import the scan again.",
                )
            ]
        shape = image_info(ctx.input_path(i.bold))[0]
        if len(shape) != 4 or shape[3] <= ctx.params.delete_volumes + 1:
            return [
                Problem(
                    code="BOLD_TOO_SHORT",
                    message=f"The BOLD run has {shape[3] if len(shape) == 4 else 1} volume(s); "
                    f"after discarding {ctx.params.delete_volumes} too few remain.",
                    probable_cause="The image is not a 4D time series, or the run is very short.",
                    suggested_action="Check the scan, or reduce the number of discarded volumes.",
                )
            ]
        if i.fieldmap is not None:
            side = read_sidecar(ctx.workspace, i.bold)
            missing = [
                label
                for key, label in (
                    ("PhaseEncodingDirection", "phase-encoding direction"),
                    ("EffectiveEchoSpacing", "effective echo spacing"),
                    ("EchoTime", "echo time"),
                )
                if key not in side
            ]
            if side.get("PhaseEncodingDirection") not in BIDS_TO_FEAT_DIRECTION:
                missing = [m for m in missing if m != "phase-encoding direction"] + [
                    "phase-encoding direction"
                ]
            if missing:
                return [
                    Problem(
                        code="UNWARP_INFO_MISSING",
                        message="Distortion correction needs facts the scan does not record: "
                        + ", ".join(sorted(set(missing)))
                        + ".",
                        probable_cause="The scanner headers do not contain them (typical for "
                        "some vendors).",
                        suggested_action="Run without distortion correction, or supply the values "
                        "from your scan protocol.",
                    )
                ]
        if ctx.params.slice_timing:
            side = read_sidecar(ctx.workspace, i.bold)
            times = side.get("SliceTiming")
            slices = shape[2]
            if not isinstance(times, list) or not times:
                return [
                    Problem(
                        code="SLICE_TIMING_MISSING",
                        message="Slice timing correction needs the time each slice was taken, "
                        "and this scan does not record it.",
                        probable_cause="The scanner headers do not contain the slice times.",
                        suggested_action="Run without slice timing correction.",
                    )
                ]
            if len(times) != slices or side.get("SliceEncodingDirection", "k") not in ("k", "k-"):
                return [
                    Problem(
                        code="SLICE_TIMING_MISMATCH",
                        message=f"The scan lists {len(times)} slice times, but the image has "
                        f"{slices} slices along the slice axis.",
                        probable_cause="The slice times belong to a different image layout.",
                        suggested_action="Run without slice timing correction.",
                    )
                ]
        return []

    def validate_outputs(
        self, ctx: StepContext[FeatPreprocInput, FeatPreprocParams]
    ) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        out = self.expected_outputs(ctx)
        src = image_info(ctx.input_path(ctx.inputs.bold))[0][3]
        got = image_info(ctx.output_dir / out.preproc_bold)[0]
        expected = src - ctx.params.delete_volumes
        if len(got) != 4 or got[3] != expected:
            return [
                Problem(
                    code="VOLUME_COUNT_MISMATCH",
                    message=f"The result has {got[3] if len(got) == 4 else 1} volumes, "
                    f"expected {expected} ({src} minus {ctx.params.delete_volumes} discarded).",
                    probable_cause="FEAT finished with an unexpected result.",
                    suggested_action="Open the raw log; run the step again.",
                )
            ]
        return []

    # -- running ------------------------------------------------------------

    def prepare(self, ctx: StepContext[FeatPreprocInput, FeatPreprocParams]) -> None:
        super().prepare(ctx)
        # An interrupted run leaves a partial folder; FEAT would write "name+.feat" next to
        # it instead of replacing it. The run restarts from the beginning.
        shutil.rmtree(ctx.run_dir / "work", ignore_errors=True)
        leftover = ctx.output_dir / native_folder_name(ctx.inputs.bold)
        if leftover.is_dir():
            shutil.rmtree(leftover)

    def _stage(self, ctx: StepContext[FeatPreprocInput, FeatPreprocParams], stage: Path) -> None:
        """Put the structural and fieldmap images where FEAT finds them by name."""
        i = ctx.inputs
        stage.mkdir(parents=True, exist_ok=True)

        def link(rel: str, name: str) -> None:
            target = stage / f"{name}.nii.gz"
            try:
                os.link(ctx.input_path(rel), target)
            except OSError:
                shutil.copy2(ctx.input_path(rel), target)

        if i.t1_head and i.t1_brain and i.t1_seg:
            link(i.t1_head, "T1")
            link(i.t1_brain, "T1_brain")
            ctx.run_command(
                [
                    "fslmaths", str(ctx.input_path(i.t1_seg)),
                    "-thr", str(WM_LABEL), "-uthr", str(WM_LABEL), "-bin",
                    str(stage / "T1_wmseg"),
                ]
            )  # fmt: skip
        if ctx.params.slice_timing:
            side = read_sidecar(ctx.workspace, i.bold)
            tr = side.get("RepetitionTime")
            tr_s = (
                float(tr)
                if isinstance(tr, int | float)
                else image_info(ctx.input_path(i.bold))[1][3]
            )
            fractions = slice_timing_fractions([float(t) for t in side["SliceTiming"]], tr_s)
            (stage / "slice_timing.txt").write_text("".join(f"{v:.6f}\n" for v in fractions))
        if i.fieldmap and i.fieldmap_magnitude_brain and i.fieldmap_magnitude:
            link(i.fieldmap, "fmap_rads")
            link(i.fieldmap_magnitude_brain, "fmap_mag_brain")
            link(i.fieldmap_magnitude, "fmap_mag")

    def run(self, ctx: StepContext[FeatPreprocInput, FeatPreprocParams]) -> StepResult:
        work = ctx.run_dir / "work"
        stage = work / "stage"
        feat_parent = work / "feat"
        feat_parent.mkdir(parents=True, exist_ok=True)
        self._stage(ctx, stage)
        design = self._design(ctx, stage)
        design_path = ctx.run_dir / "design.fsf"
        design_path.write_text(write_design(design))
        record = ctx.run_command(["feat", str(design_path)], check=False)
        made = feat_parent / "result.feat"
        if record.return_code < 0:
            raise StepError(
                code="COMMAND_KILLED",
                message=f"'feat' was stopped before it finished (signal {-record.return_code}).",
                probable_cause="The process was killed, for example by a user or the system.",
                suggested_action="Resume the pipeline to run this step again.",
            )
        if record.return_code != 0 or not (made / "filtered_func_data.nii.gz").is_file():
            raise _explain_failure(made, ctx.workspace.abspath(record.stderr_log))
        native = ctx.output_dir / native_folder_name(ctx.inputs.bold)
        shutil.copy2(design_path, made / "design_mrforge.fsf")
        native.parent.mkdir(parents=True, exist_ok=True)
        os.replace(made, native)
        self._publish(ctx, native)
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def _publish(self, ctx: StepContext[FeatPreprocInput, FeatPreprocParams], native: Path) -> None:
        """Link the key results to their BIDS names; write the motion table."""
        out = self.expected_outputs(ctx)
        links = {
            out.preproc_bold: "filtered_func_data.nii.gz",
            out.brain_mask: "mask.nii.gz",
            out.boldref: "example_func.nii.gz",
        }
        if out.to_t1_affine:
            links[out.to_t1_affine] = "reg/example_func2highres.mat"
        if out.to_t1_warp:
            links[out.to_t1_warp] = "reg/example_func2highres_warp.nii.gz"
        if out.boldref_t1:
            links[out.boldref_t1] = "reg/example_func2highres.nii.gz"
        if out.boldref_distorted_t1:
            links[out.boldref_distorted_t1] = "reg/unwarp/example_func_distorted2highres.nii.gz"
        for target_name, native_name in links.items():
            source = native / native_name
            if not source.is_file():
                continue  # validate_outputs reports it as missing
            target = ctx.output_dir / target_name
            target.unlink(missing_ok=True)
            try:
                os.link(source, target)  # same data, no extra disk space
            except OSError:
                shutil.copy2(source, target)
        par = native / "mc" / "prefiltered_func_data_mcf.par"
        if out.motion and par.is_file():
            rows = ["rot_x\trot_y\trot_z\ttrans_x\ttrans_y\ttrans_z"]
            rows += [
                "\t".join(line.split()) for line in par.read_text().splitlines() if line.strip()
            ]
            (ctx.output_dir / out.motion).write_text("\n".join(rows) + "\n")
