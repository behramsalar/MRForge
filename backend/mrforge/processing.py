"""Full processing: the stages of the standard pipeline, planned from one place.

A *stage* is a group of steps with a plain-language name, for example "Anatomical" or
"Functional". Full processing plans the stages in order for one subject, shows the plan (the
confirmation dialog), and turns it into one ordinary ``PipelineSpec`` of separate steps, so
resume, provenance and live status work as for any other pipeline.

Adding a stage later (artifact rejection, WM/CSF regression, ROI-to-ROI correlation, ...) is:
write a ``Stage`` subclass and add it to ``STAGES`` in the right place. A stage reads and
updates the shared ``PlanContext``; in particular ``context.bold[run]`` is the native-space
time series that the next stage should work on, so a cleanup stage placed before "Standard
space" automatically feeds it its cleaned data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from mrforge.aroma_env import find_aroma
from mrforge.bids import parse_bids_name
from mrforge.datafiles import subject_data
from mrforge.diffusion import DiffusionOptions, DiffusionRun, diffusion_runs
from mrforge.functional import (
    anat_results,
    fieldmap_status,
    slice_timing_status,
)
from mrforge.icalabels import SUMMARY_SUFFIX, decision_path
from mrforge.mrtrix_env import find_mrtrix
from mrforge.niftiutil import image_info
from mrforge.pipeline import PipelineSpec, PipelineStep
from mrforge.results import existing_cleaned, existing_functional
from mrforge.resume import check_reusable
from mrforge.runner.jobs import build_context
from mrforge.steps.dwi_to_template import DwiToTemplateParams, resolve_template
from mrforge.steps.melodic import MIN_VOLUMES
from mrforge.steps.resample_t1 import needs_resampling
from mrforge.workspace import Workspace

# -- what the user can choose ---------------------------------------------------------------


class AnatomicalOptions(BaseModel):
    strong_bias: bool = False
    subcortical_segmentation: bool = False  # slow; not needed for the functional pipeline
    # Resample a T1 with voxels finer than 1 mm to 1 mm before fsl_anat (much faster on very
    # high-resolution scans; segmentation then comes from the 1 mm image).
    resample_to_1mm: bool = False


class FunctionalOptions(BaseModel):
    # REVIEW(domain): 5 volumes (confirmed); 5 mm FWHM and 150 s high-pass are proposals.
    delete_volumes: int = Field(default=5, ge=0)
    smoothing_fwhm_mm: float = Field(default=5.0, ge=0, le=20)
    highpass_cutoff_s: float | None = Field(default=150.0, gt=0)  # None: no temporal filtering
    use_fieldmap: bool = True  # used for every run that has a usable fieldmap
    slice_timing: bool = False  # used for every run whose scan records slice times


class ArtifactOptions(BaseModel):
    # REVIEW(domain): "uncertain" components are kept by default (removes less); partial
    # (non-aggressive) removal is fsl_regfilt's default and what ICA-AROMA uses.
    uncertain_as: Literal["signal", "noise"] = "signal"
    aggressive: bool = False
    # Who labels the components. "manual": you (the processing pauses). "aroma_review":
    # ICA-AROMA proposes, you confirm (pauses). "aroma_auto": ICA-AROMA's classification is used
    # as it is (no pause). REVIEW(domain): the automatic mode trusts ICA-AROMA's fixed rules.
    mode: Literal["manual", "aroma_review", "aroma_auto"] = "manual"


class FullOptions(BaseModel):
    subject: str
    preset: str | None = None  # name of the preset these choices came from (recorded only)
    # Stages switched off on purpose; missing means "as planned by default".
    stages: dict[str, bool] = {}
    anatomical: AnatomicalOptions = AnatomicalOptions()
    functional: FunctionalOptions = FunctionalOptions()
    artifact: ArtifactOptions = ArtifactOptions()
    diffusion: DiffusionOptions = DiffusionOptions()


# -- the plan shown to the user ------------------------------------------------------------


class PlanSetting(BaseModel):
    name: str
    value: str


class PlanItem(BaseModel):
    """One thing a stage will do (for the anatomical stage the subject's T1; for the
    functional stage one recording)."""

    title: str
    note: str | None = None  # for example why distortion correction is left out
    settings: list[PlanSetting] = []


class BatchOptions(BaseModel):
    """The same choices as for one subject, applied to several."""

    subjects: list[str]
    stages: dict[str, bool] = {}
    anatomical: AnatomicalOptions = AnatomicalOptions()
    functional: FunctionalOptions = FunctionalOptions()
    artifact: ArtifactOptions = ArtifactOptions()
    diffusion: DiffusionOptions = DiffusionOptions()
    preset: str | None = None  # name of the preset the choices came from (recorded only)

    def for_subject(self, label: str) -> FullOptions:
        return FullOptions(
            subject=label,
            stages=self.stages,
            anatomical=self.anatomical,
            functional=self.functional,
            artifact=self.artifact,
            diffusion=self.diffusion,
            preset=self.preset,
        )


class StagePlan(BaseModel):
    id: str
    label: str
    description: str
    enabled: bool  # ticked in the dialog
    default_enabled: bool
    can_run: bool  # False: inputs are missing (see reason); the stage is left out
    reason: str | None = None
    already_done: bool = False  # results from an earlier run exist (finished work is not repeated)
    items: list[PlanItem] = []


class FullPlan(BaseModel):
    subject: str
    stages: list[StagePlan]
    steps: int  # number of steps in the pipeline that would run
    can_start: bool


class BatchSubjectPlan(BaseModel):
    subject: str
    can_start: bool
    steps: int
    reason: str | None = None  # plain language, when it cannot run


class BatchPlan(BaseModel):
    """What a batch would do: the shared stage descriptions (from the first runnable subject)
    and one line per subject."""

    stages: list[StagePlan]
    subjects: list[BatchSubjectPlan]
    runnable: int


@dataclass
class PlanContext:
    ws: Workspace
    opts: FullOptions
    steps: list[PipelineStep] = field(default_factory=list)
    # Where the structural results come from: a reference to a step of this pipeline, or the
    # path of an earlier run's file. None until the anatomical stage has been planned.
    anat: dict[str, str] | None = None
    # Per recording (slug): the native-space time series and brain mask later stages should use.
    bold: dict[str, str] = field(default_factory=dict)
    brain_mask: dict[str, str] = field(default_factory=dict)
    affine: dict[str, str] = field(default_factory=dict)
    motion: dict[str, str] = field(default_factory=dict)
    runs: dict[str, str] = field(default_factory=dict)  # slug -> raw BOLD path
    ready: set[str] = field(default_factory=set)  # stages that are planned or already satisfied

    @property
    def subject(self) -> str:
        return self.opts.subject


class Stage(ABC):
    id: str
    label: str
    description: str
    default_enabled: bool = True
    depends_on: tuple[str, ...] = ()

    @abstractmethod
    def plan(self, ctx: PlanContext, enabled: bool) -> StagePlan:
        """Describe the stage and, when it is enabled and possible, add its steps to
        ``ctx.steps`` and update the shared context for the stages after it."""

    def blank(self, enabled: bool, **kw: Any) -> StagePlan:
        return StagePlan(
            id=self.id,
            label=self.label,
            description=self.description,
            enabled=enabled,
            default_enabled=self.default_enabled,
            can_run=kw.pop("can_run", True),
            **kw,
        )

    def missing(self, ctx: PlanContext) -> str | None:
        """The first stage this one needs that is neither planned nor already satisfied."""
        for dep in self.depends_on:
            if dep not in ctx.ready:
                return dep
        return None


def recording_slug(bold_rel: str, default: str = "bold") -> str:
    """ "task-rest_run-1" from a BOLD file name; used in step ids (letters, digits, - and _)."""
    entities = parse_bids_name(Path(bold_rel).name)[0]
    parts = [f"{k}-{v}" for k, v in entities.items() if k not in ("sub", "ses")]
    return "_".join(parts) or default


# -- the stages -----------------------------------------------------------------------------


def _resampled_t1_path(ctx: PlanContext, t1_rel: str) -> str:
    """Where the resample_t1 step will put its result (the same name the step itself builds)."""
    step, sctx = build_context(ctx.ws, "resample_t1", ctx.subject, None, {"t1": t1_rel}, {})
    return ctx.ws.relpath(sctx.output_dir / step.expected_outputs(sctx).result)


class AnatomicalStage(Stage):
    id = "anatomical"
    label = "Anatomical"
    description = (
        "Removes the skull from the T1 image, corrects brightness differences, separates the "
        "tissue types and prepares the alignment to standard space."
    )

    def plan(self, ctx: PlanContext, enabled: bool) -> StagePlan:
        existing = anat_results(ctx.ws, ctx.subject, None)
        recorded = False  # finished by MRForge with the same inputs and settings
        t1s = [
            f
            for f in subject_data(ctx.ws, ctx.subject).files
            if f.datatype == "anat" and f.suffix == "T1w"
        ]
        stage = self.blank(enabled)
        if not t1s:
            if existing is not None:
                ctx.anat = existing
                ctx.ready.add(self.id)
            stage.can_run = existing is not None
            stage.reason = None if existing else "This subject has no T1 image."
            return stage
        t1 = t1s[0]
        opts = ctx.opts.anatomical
        params = {
            "strong_bias": opts.strong_bias,
            "subcortical_segmentation": opts.subcortical_segmentation,
        }
        t1_input = t1.relpath
        resample_note: str | None = None
        resample_path: str | None = None
        if opts.resample_to_1mm:
            zooms = image_info(ctx.ws.abspath(t1.relpath))[1]
            if needs_resampling(zooms):
                resample_path = _resampled_t1_path(ctx, t1.relpath)
                t1_input = resample_path
            else:
                sizes = " × ".join(f"{z:.3g}" for z in zooms[:3])
                resample_note = (
                    f"Not resampled: the T1 already has voxels of {sizes} mm (1 mm or coarser)."
                )
        recorded = check_reusable(
            ctx.ws, "fsl_anat", ctx.subject, {"t1": t1_input}, params
        ).reusable
        if recorded and resample_path is not None:
            recorded = check_reusable(
                ctx.ws, "resample_t1", ctx.subject, {"t1": t1.relpath}, {}
            ).reusable
        stage.already_done = recorded
        notes = [f"{len(t1s)} T1 images found; the first one is used."] if len(t1s) > 1 else []
        if existing is not None and not recorded and enabled:
            notes.append(
                "Results from an earlier run exist, but MRForge has no record of making them with "
                "these settings, so they are made again (this takes a while). Untick Anatomical "
                "to use the existing results as they are."
            )
        if resample_note:
            notes.append(resample_note)
        note = " ".join(notes) or None
        resample_value = "yes, to 1 mm (spline)" if resample_path else "skipped (1 mm or coarser)"
        stage.items = [
            PlanItem(
                title=f"Process {Path(t1.relpath).name}",
                note=note,
                settings=[
                    *(
                        [PlanSetting(name="Resample to 1 mm first", value=resample_value)]
                        if opts.resample_to_1mm
                        else []
                    ),
                    PlanSetting(
                        name="Intensity correction",
                        value="strong" if opts.strong_bias else "standard",
                    ),
                    PlanSetting(
                        name="Deep brain structures",
                        value="segmented (slow)"
                        if opts.subcortical_segmentation
                        else "not segmented",
                    ),
                ],
            )
        ]
        if not enabled:
            if existing is not None:  # later stages can still use the earlier results
                ctx.anat = existing
                ctx.ready.add(self.id)
            return stage
        if resample_path is not None:
            ctx.steps.append(
                PipelineStep(id="resample_t1", step="resample_t1", inputs={"t1": t1.relpath})
            )
        ctx.steps.append(
            PipelineStep(
                id="fsl_anat",
                step="fsl_anat",
                inputs={"t1": "${resample_t1.result}" if resample_path else t1.relpath},
                params=params,
            )
        )
        ctx.anat = {
            "t1_head": "${fsl_anat.biascorr}",
            "t1_brain": "${fsl_anat.brain}",
            "t1_seg": "${fsl_anat.segmentation}",
            "t1_to_mni_warp": "${fsl_anat.to_mni_warp}",
        }
        ctx.ready.add(self.id)
        return stage


class FunctionalStage(Stage):
    id = "functional"
    label = "Functional"
    description = (
        "Corrects head motion and image distortion, smooths the data, removes slow drifts and "
        "aligns each functional run to the T1, with quality checks."
    )
    depends_on = ("anatomical",)

    def plan(self, ctx: PlanContext, enabled: bool) -> StagePlan:
        files = [
            f
            for f in subject_data(ctx.ws, ctx.subject).files
            if f.datatype == "func" and f.suffix == "bold"
        ]
        stage = self.blank(enabled)
        if not files:
            stage.can_run, stage.reason = False, "This subject has no functional run."
            return stage
        if enabled and self.missing(ctx) is not None:
            stage.can_run = False
            stage.reason = "Anatomical processing has to be done first (or included)."
            return stage
        opts = ctx.opts.functional
        made_fieldmaps: set[str] = set()
        found: dict[str, dict[str, str]] = {}
        all_existing = True
        for f in files:
            slug = recording_slug(f.relpath)
            fmap = fieldmap_status(ctx.ws, f.relpath)
            slices = slice_timing_status(ctx.ws, f.relpath)
            use_fmap = opts.use_fieldmap and fmap.available
            use_slices = opts.slice_timing and slices.available
            notes: list[str] = []
            if opts.use_fieldmap and not fmap.available:
                notes.append(f"No distortion correction: {fmap.reason}")
            if opts.slice_timing and not slices.available:
                notes.append(f"No slice timing correction: {slices.reason}")
            try:
                volumes = image_info(ctx.ws.abspath(f.relpath))[0][3]
            except Exception:
                volumes = None
            if volumes is not None and volumes <= opts.delete_volumes + 1:
                stage.can_run = False
                stage.reason = (
                    f"Run {slug.replace('_', ' ')} has {volumes} volumes; after discarding "
                    f"{opts.delete_volumes} too few would remain. Lower the discarded volumes."
                )
            stage.items.append(
                PlanItem(
                    title=f"Run {slug.replace('_', ' ')}"
                    + (f" ({volumes} volumes)" if volumes else ""),
                    note=" ".join(notes) or None,
                    settings=[
                        PlanSetting(name="Volumes discarded", value=str(opts.delete_volumes)),
                        PlanSetting(
                            name="Smoothing",
                            value=f"{opts.smoothing_fwhm_mm:g} mm"
                            if opts.smoothing_fwhm_mm
                            else "off",
                        ),
                        PlanSetting(
                            name="Slow-drift filter",
                            value=f"{opts.highpass_cutoff_s:g} s"
                            if opts.highpass_cutoff_s
                            else "off",
                        ),
                        PlanSetting(
                            name="Distortion correction",
                            value="with the fieldmap" if use_fmap else "no",
                        ),
                        PlanSetting(name="Slice timing", value="on" if use_slices else "off"),
                    ],
                )
            )
            if not enabled:
                # Not run now: later stages can use the results of an earlier run.
                earlier = existing_functional(ctx.ws, ctx.subject, f.relpath)
                if earlier is None:
                    all_existing = False
                else:
                    found[slug] = earlier
                continue
            if not stage.can_run:
                continue
            assert ctx.anat is not None
            ctx.runs[slug] = f.relpath
            feat_inputs: dict[str, Any] = {
                "bold": f.relpath,
                "t1_head": ctx.anat["t1_head"],
                "t1_brain": ctx.anat["t1_brain"],
                "t1_seg": ctx.anat["t1_seg"],
            }
            if use_fmap:
                assert fmap.magnitude1 and fmap.phasediff
                fm_slug = recording_slug(fmap.phasediff, "fieldmap")
                fm_id = f"fieldmap_prep__{fm_slug}"
                if fm_id not in made_fieldmaps:
                    made_fieldmaps.add(fm_id)
                    ctx.steps.append(
                        PipelineStep(
                            id=fm_id,
                            label="fieldmap_prep",
                            step="fieldmap_prep",
                            inputs={"magnitude1": fmap.magnitude1, "phasediff": fmap.phasediff},
                        )
                    )
                feat_inputs |= {
                    "fieldmap": f"${{{fm_id}.fieldmap}}",
                    "fieldmap_magnitude_brain": f"${{{fm_id}.magnitude_brain}}",
                    "fieldmap_magnitude": fmap.magnitude1,
                }
            feat_id, qc_id = f"feat_preproc__{slug}", f"func_qc__{slug}"
            ctx.steps.append(
                PipelineStep(
                    id=feat_id,
                    label="feat_preproc",
                    step="feat_preproc",
                    inputs=feat_inputs,
                    params={
                        "delete_volumes": opts.delete_volumes,
                        "smoothing_fwhm_mm": opts.smoothing_fwhm_mm,
                        "highpass_cutoff_s": opts.highpass_cutoff_s,
                        "slice_timing": use_slices,
                    },
                )
            )
            qc_inputs: dict[str, Any] = {
                "motion": f"${{{feat_id}.motion}}",
                "boldref_t1": f"${{{feat_id}.boldref_t1}}",
                "t1_head": ctx.anat["t1_head"],
                "t1_seg": ctx.anat["t1_seg"],
            }
            if use_fmap:
                qc_inputs["boldref_distorted_t1"] = f"${{{feat_id}.boldref_distorted_t1}}"
            ctx.steps.append(
                PipelineStep(id=qc_id, label="func_qc", step="func_qc", inputs=qc_inputs)
            )
            ctx.bold[slug] = f"${{{feat_id}.preproc_bold}}"
            ctx.brain_mask[slug] = f"${{{feat_id}.brain_mask}}"
            ctx.affine[slug] = f"${{{feat_id}.to_t1_affine}}"
            ctx.motion[slug] = f"${{{feat_id}.motion}}"
        if enabled:
            ctx.ready.add(self.id)
        elif all_existing and found:
            raw = {recording_slug(f.relpath): f.relpath for f in files}
            for slug, earlier in found.items():
                ctx.runs[slug] = raw[slug]
                ctx.bold[slug] = earlier["bold"]
                ctx.brain_mask[slug] = earlier["brain_mask"]
                ctx.affine[slug] = earlier["affine"]
                ctx.motion[slug] = earlier["motion"]
            ctx.ready.add(self.id)
        return stage


class ArtifactStage(Stage):
    id = "artifact_rejection"
    label = "Artifact rejection"
    description = (
        "Finds independent components in each run (MELODIC), labels each one as signal or noise "
        "(you, or ICA-AROMA), and removes the noise. Standard space then uses the cleaned data. "
        "When you label, the processing pauses and continues when you save."
    )
    default_enabled = False  # it needs you: the pipeline waits for your decision
    depends_on = ("functional",)

    def plan(self, ctx: PlanContext, enabled: bool) -> StagePlan:
        stage = self.blank(enabled)
        if enabled and self.missing(ctx) is not None:
            stage.can_run = False
            stage.reason = "Functional preprocessing has to be included."
            return stage
        opts = ctx.opts.artifact
        uses_aroma = opts.mode != "manual"
        if uses_aroma and find_aroma() is None:
            stage.can_run = False
            stage.reason = (
                "ICA-AROMA is not installed. Choose to label the components yourself, or run "
                "scripts/install_aroma.sh."
            )
        slugs = list(ctx.runs) or []
        discarded = ctx.opts.functional.delete_volumes
        for slug in slugs:
            raw = ctx.runs[slug]
            try:
                volumes = image_info(ctx.ws.abspath(raw))[0][3] - discarded
            except Exception:
                volumes = None
            if volumes is not None and volumes < MIN_VOLUMES:
                stage.can_run = False
                stage.reason = (
                    f"Run {slug.replace('_', ' ')} would have only {volumes} volumes left; "
                    f"component analysis needs at least {MIN_VOLUMES}."
                )
            who = {
                "manual": "you (processing pauses until you save)",
                "aroma_review": "ICA-AROMA proposes, you confirm (processing pauses)",
                "aroma_auto": "ICA-AROMA decides (no pause)",
            }[opts.mode]
            stage.items.append(
                PlanItem(
                    title=f"Run {slug.replace('_', ' ')}",
                    settings=[
                        PlanSetting(name="Components", value="number found by MELODIC"),
                        PlanSetting(name="Labelling", value=who),
                        PlanSetting(
                            name="Removal",
                            value="aggressive" if opts.aggressive else "partial (non-aggressive)",
                        ),
                        PlanSetting(
                            name="Uncertain components", value=f"kept as {opts.uncertain_as}"
                        ),
                    ],
                )
            )
        if not stage.items:
            stage.items = [PlanItem(title="Every functional run of the subject", settings=[])]
        if not enabled:
            # Standard space on its own should use the cleaned data when there are any. Not when
            # the functional stage runs again in this pipeline: the old cleaned image is stale.
            for slug in slugs:
                cleaned = existing_cleaned(ctx.ws, ctx.subject, ctx.runs[slug])
                if cleaned and not ctx.bold.get(slug, "${").startswith("${"):
                    ctx.bold[slug] = cleaned
            return stage
        if not stage.can_run:
            return stage
        assert ctx.anat is not None
        for slug in slugs:
            ctx.steps.append(
                PipelineStep(
                    id=f"melodic__{slug}",
                    label="melodic",
                    step="melodic",
                    inputs={
                        "bold": ctx.bold[slug],
                        "brain_mask": ctx.brain_mask[slug],
                        "t1_brain": ctx.anat["t1_brain"],
                        "to_t1_affine": ctx.affine[slug],
                    },
                )
            )
        if uses_aroma:
            for slug in slugs:
                ctx.steps.append(
                    PipelineStep(
                        id=f"aroma_classify__{slug}",
                        label="aroma_classify",
                        step="aroma_classify",
                        inputs={
                            "melodic_summary": f"${{melodic__{slug}.summary}}",
                            "bold": ctx.bold[slug],
                            "motion": ctx.motion[slug],
                            "to_t1_affine": ctx.affine[slug],
                            "t1_to_mni_warp": ctx.anat["t1_to_mni_warp"],
                            "brain_mask": ctx.brain_mask[slug],
                        },
                    )
                )
        for slug in slugs:
            summary = self._summary_path(ctx, slug)
            automatic = opts.mode == "aroma_auto"
            labels_inputs: dict[str, Any] = {"melodic_summary": f"${{melodic__{slug}.summary}}"}
            if automatic:
                labels_inputs["aroma"] = f"${{aroma_classify__{slug}.classification}}"
            else:
                labels_inputs["decision"] = decision_path(summary)
            ctx.steps.append(
                PipelineStep(
                    id=f"ica_labels__{slug}",
                    label="ica_labels",
                    step="ica_labels",
                    inputs=labels_inputs,
                    params={
                        "uncertain_as": opts.uncertain_as,
                        "mode": "aroma" if automatic else "manual",
                    },
                )
            )
        for slug in slugs:
            ctx.steps.append(
                PipelineStep(
                    id=f"regfilt__{slug}",
                    label="regfilt",
                    step="regfilt",
                    inputs={
                        "bold": ctx.bold[slug],
                        "mixing": f"${{melodic__{slug}.mixing}}",
                        "labels": f"${{ica_labels__{slug}.labels}}",
                        "brain_mask": ctx.brain_mask[slug],
                    },
                    params={"aggressive": opts.aggressive},
                )
            )
            ctx.bold[slug] = f"${{regfilt__{slug}.cleaned_bold}}"  # the next stage uses this
        ctx.ready.add(self.id)
        return stage

    def _summary_path(self, ctx: PlanContext, slug: str) -> str:
        """Where this run's MELODIC summary will be written. The name depends only on the
        BIDS entities of the first input, which the raw BOLD file and the FEAT result share,
        so the raw file stands in for the not yet existing FEAT result."""
        raw = ctx.runs[slug]
        step, context = build_context(
            ctx.ws, "melodic", ctx.subject, None, {"bold": raw, "brain_mask": raw}, {}, "melodic"
        )
        name = step.expected_outputs(context).summary
        assert name.endswith(SUMMARY_SUFFIX)
        return ctx.ws.relpath(context.output_dir / name)


def _which_data(bold_ref: str) -> str:
    """Plain words for the data a later stage works on."""
    return (
        "denoised data (noise components removed)"
        if "regfilt" in bold_ref or "denoised" in bold_ref
        else "preprocessed data"
    )


class StandardSpaceStage(Stage):
    id = "standard_space"
    label = "Standard space"
    description = (
        "Moves each functional run into standard (MNI) space with one resampling, using the "
        "alignment from the anatomical stage."
    )
    depends_on = ("functional",)

    def plan(self, ctx: PlanContext, enabled: bool) -> StagePlan:
        stage = self.blank(enabled)
        if enabled and self.missing(ctx) is not None:
            stage.can_run, stage.reason = False, "Functional preprocessing has to be included."
            return stage
        stage.items = [
            PlanItem(
                title=f"Run {slug.replace('_', ' ')}",
                settings=[
                    PlanSetting(name="Resolution", value="2 mm"),
                    PlanSetting(name="Data", value=_which_data(ctx.bold.get(slug, ""))),
                ],
            )
            for slug in ctx.runs
        ] or [
            PlanItem(
                title="Every functional run of the subject",
                settings=[PlanSetting(name="Resolution", value="2 mm")],
            )
        ]
        if not enabled:
            return stage
        assert ctx.anat is not None
        for slug in ctx.runs:
            ctx.steps.append(
                PipelineStep(
                    id=f"func_to_mni__{slug}",
                    label="func_to_mni",
                    step="func_to_mni",
                    inputs={
                        "bold": ctx.bold[slug],
                        "to_t1_affine": ctx.affine[slug],
                        "t1_to_mni_warp": ctx.anat["t1_to_mni_warp"],
                        "brain_mask": ctx.brain_mask[slug],
                    },
                )
            )
        ctx.ready.add(self.id)
        return stage


def template_key(o: DiffusionOptions) -> str:
    """The template the maps are moved to: the choice, else by the structural image, else the
    JHU FA template (as in the script)."""
    weight: Literal["t1", "t2"] = "t2" if o.structural == "t2" else "t1"
    return resolve_template(
        DwiToTemplateParams(template=o.template, struct_weight=weight), o.structural != "none"
    )


def _eddy_label(program: str) -> str:
    return {"eddy_cpu": "eddy_cpu (CPU)", "eddy_correct": "eddy_correct (older, simple)"}.get(
        program, program
    )


class DiffusionStage(Stage):
    id = "diffusion"
    label = "Diffusion (ALPS)"
    description = (
        "Prepares each diffusion series (noise and ringing removal if MRtrix3 is installed, "
        "distortion and eddy-current correction), fits the diffusion tensor and computes the "
        "ALPS index (diffusion along perivascular spaces) from four regions of interest."
    )
    default_enabled = False  # long (eddy takes hours) and only for subjects with diffusion data

    def plan(self, ctx: PlanContext, enabled: bool) -> StagePlan:
        opts = ctx.opts.diffusion
        stage = self.blank(enabled)
        runs = diffusion_runs(ctx.ws, ctx.subject, opts.second_is_opposite)
        if not runs:
            stage.can_run, stage.reason = False, "This subject has no diffusion image."
            return stage
        structurals = [
            f
            for f in subject_data(ctx.ws, ctx.subject).files
            if f.datatype == "anat" and f.suffix == {"t1": "T1w", "t2": "T2w"}.get(opts.structural)
        ]
        if opts.structural != "none" and not structurals:
            stage.can_run = False
            stage.reason = (
                f"There is no {opts.structural.upper()} image for the structural registration. "
                "Choose a registration without it."
            )
        if opts.roi_source == "custom" and len(opts.custom_rois) != 4:
            stage.can_run = False
            stage.reason = "Custom regions need four files (projection and association, L and R)."
        mrtrix = find_mrtrix()
        for number, run in enumerate(runs, 1):
            slug = recording_slug(run.relpath, "dwi")
            item, notes = self._item(ctx, run, slug, number, mrtrix is not None)
            stage.items.append(item)
            if run.problem:
                stage.can_run, stage.reason = False, f"{item.title}: {run.problem}"
            if not (enabled and stage.can_run):
                continue
            self._add_steps(ctx, run, slug, notes, mrtrix is not None, structurals)
        if enabled and stage.can_run:
            ctx.ready.add(self.id)
        return stage

    def _item(
        self, ctx: PlanContext, run: DiffusionRun, slug: str, number: int, have_mrtrix: bool
    ) -> tuple[PlanItem, list[str]]:
        o = ctx.opts.diffusion
        notes: list[str] = []
        use_topup = o.topup and run.reverse is not None
        if o.topup and run.reverse is None:
            notes.append(f"No distortion correction: {run.topup_note}.")
        if (o.denoise or o.unring) and not have_mrtrix:
            notes.append("No noise or ringing removal: MRtrix3 is not installed.")
        if o.eddy == "none":
            notes.append("No eddy-current or motion correction (left out on purpose).")
        denoise = o.denoise and have_mrtrix
        unring = o.unring and have_mrtrix
        key = None if o.registration == "native" else template_key(o)
        space = {
            None: "the person's own space (native)",
            "jhu_fa": "JHU-ICBM FA template",
            "mni_t1": "MNI152 T1 template (through the T1)",
            "jhu_t2": "JHU-ICBM T2 template (through the T2)",
        }[key if key in ("jhu_fa", "mni_t1", "jhu_t2") else None]
        how = (
            f"through the {o.structural.upper()}"
            if o.structural != "none"
            else {
                "linear": "linear",
                "fnirt": "non-linear",
                "linear_fnirt": "linear then non-linear",
            }.get(o.registration, "")
        )
        rois = {
            "default": "packaged 2.5 mm spheres",
            "legacy5": "packaged 5 mm boxes (older)",
            "sphere": f"spheres of {o.roi_radius_mm:g} mm radius",
            "custom": "your own four files",
        }[o.roi_source]
        settings = [
            PlanSetting(name="Noise removal", value="yes" if denoise else "no"),
            PlanSetting(name="Ringing removal", value="yes" if unring else "no"),
            PlanSetting(
                name="Distortion correction",
                value=f"TOPUP with the {run.reverse_from}" if use_topup else "no",
            ),
            PlanSetting(
                name="Eddy-current correction",
                value="no" if o.eddy == "none" else _eddy_label(o.eddy),
            ),
            PlanSetting(name="Space", value=space + (f", {how}" if how else "")),
            PlanSetting(name="Regions", value=rois),
        ]
        if o.registration != "native":
            settings.append(
                PlanSetting(
                    name="Tensor moved with",
                    value="flirt (script default)" if o.tensor_method == "flirt" else "vecreg",
                )
            )
        title = f"Series {slug.replace('_', ' ')}" if slug != "dwi" else "Diffusion series"
        if number > 1 and slug == "dwi":
            title = f"Diffusion series {number}"
        return PlanItem(title=title, note=" ".join(notes) or None, settings=settings), notes

    def _add_steps(
        self,
        ctx: PlanContext,
        run: DiffusionRun,
        slug: str,
        notes: list[str],
        have_mrtrix: bool,
        structurals: list[Any],
    ) -> None:
        o = ctx.opts.diffusion
        steps = ctx.steps
        assert run.bval and run.bvec and run.sidecar
        cur = run.relpath
        done: list[str] = []

        def add(step: str, inputs: dict[str, Any], params: dict[str, Any] | None = None) -> str:
            sid = f"{step}__{slug}"
            steps.append(
                PipelineStep(id=sid, label=step, step=step, inputs=inputs, params=params or {})
            )
            return sid

        if o.denoise and have_mrtrix:
            cur = f"${{{add('dwi_denoise', {'dwi': cur})}.dwi}}"
            done.append("denoised")
        if o.unring and have_mrtrix:
            cur = f"${{{add('dwi_unring', {'dwi': cur})}.dwi}}"
            done.append("Gibbs ringing removed")
        topup: str | None = None
        if o.topup and run.reverse is not None:
            inputs: dict[str, Any] = {
                "dwi": cur,
                "dwi_json": run.sidecar,
                "dwi_bval": run.bval,
                "reverse": run.reverse,
            }
            if run.reverse_json:
                inputs["reverse_json"] = run.reverse_json
            if run.reverse_bval:
                inputs["reverse_bval"] = run.reverse_bval
            topup = add("dwi_topup", inputs, {"second_is_opposite": o.second_is_opposite})
        bval, bvec, mask = run.bval, run.bvec, None
        eddy: str | None = None
        if o.eddy != "none":
            inputs = {"dwi": cur, "bval": run.bval, "bvec": run.bvec, "dwi_json": run.sidecar}
            if topup:
                inputs |= {
                    "topup_acqparams": f"${{{topup}.acqparams}}",
                    "topup_fieldcoef": f"${{{topup}.fieldcoef}}",
                    "topup_movpar": f"${{{topup}.movpar}}",
                    "topup_mask": f"${{{topup}.mask}}",
                }
            params: dict[str, Any] = {"program": o.eddy}
            if o.eddy_threads:
                params["threads"] = o.eddy_threads
            eddy = add("dwi_eddy", inputs, params)
            cur, bval, bvec, mask = (f"${{{eddy}.{k}}}" for k in ("dwi", "bval", "bvec", "mask"))
        elif topup:
            mask = f"${{{topup}.mask}}"
        fit_inputs: dict[str, Any] = {"dwi": cur, "bval": bval, "bvec": bvec}
        if mask:
            fit_inputs["mask"] = mask
        fit = add("dwi_dtifit", fit_inputs)
        qc_inputs: dict[str, Any] = {"fa": f"${{{fit}.fa}}", "mask": f"${{{fit}.mask}}"}
        if eddy and o.eddy != "eddy_correct":
            qc_inputs |= {
                "movement_rms": f"${{{eddy}.movement_rms}}",
                "restricted_rms": f"${{{eddy}.restricted_rms}}",
                "outlier_report": f"${{{eddy}.outlier_report}}",
            }
        add("dwi_qc", qc_inputs)

        fa, md, tensor = (f"${{{fit}.{k}}}" for k in ("fa", "md", "tensor"))
        has_struct = o.structural != "none"
        roi_params: dict[str, Any] = {
            "source": o.roi_source,
            "radius_mm": o.roi_radius_mm,
            "space": "native",
            "template": "jhu_fa",
        }
        if o.registration != "native":
            reg_inputs: dict[str, Any] = {
                "fa": fa,
                "md": md,
                "tensor": tensor,
                "mask": f"${{{fit}.mask}}",
            }
            if has_struct:
                reg_inputs["struct"] = structurals[0].relpath
                if topup:
                    reg_inputs["b0"] = f"${{{topup}.b0}}"
            params = {
                "registration": o.registration,
                "template": o.template,
                "struct_weight": o.structural if has_struct else "t1",
                "tensor_method": o.tensor_method,
            }
            reg = add("dwi_to_template", reg_inputs, params)
            fa, md, tensor = (f"${{{reg}.{k}}}" for k in ("fa", "md", "tensor"))
            roi_params["space"] = "template"
            roi_params["template"] = template_key(o)
        roi_inputs: dict[str, Any] = {"fa": fa}
        if o.roi_source == "custom":
            roi_inputs["custom_rois"] = o.custom_rois
        rois = add("alps_rois", roi_inputs, roi_params)
        settings = {
            "preprocessing": ", ".join(done) or "none",
            "distortion correction": "TOPUP" if topup else "none",
            "eddy": o.eddy,
            "registration": "native"
            if o.registration == "native"
            else (f"structural ({o.structural.upper()})" if has_struct else o.registration),
            "template": str(roi_params["template"])
            if roi_params["space"] == "template"
            else "native",
            "tensor transform": o.tensor_method if o.registration != "native" else "none",
            "regions": o.roi_source,
        }
        add(
            "alps_index",
            {
                "tensor": tensor,
                "fa": fa,
                "md": md,
                "proj_l": f"${{{rois}.proj_l}}",
                "proj_r": f"${{{rois}.proj_r}}",
                "assoc_l": f"${{{rois}.assoc_l}}",
                "assoc_r": f"${{{rois}.assoc_r}}",
                "dwi_json": run.sidecar,
            },
            {"round_like_script": o.round_like_script, "settings": settings, "notes": notes},
        )


# The order of the stages is the order of the pipeline. Stages that clean the data (artifact
# rejection, WM/CSF regression) belong between Functional and Standard space; stages that use
# the finished data (ROI-to-ROI correlation) after it.
STAGES: list[Stage] = [
    AnatomicalStage(),
    FunctionalStage(),
    ArtifactStage(),
    StandardSpaceStage(),
    DiffusionStage(),
]


def plan_batch(ws: Workspace, opts: BatchOptions) -> tuple[BatchPlan, list[PipelineSpec]]:
    """Plan every subject with the same choices; the specs of those that can run."""
    lines: list[BatchSubjectPlan] = []
    specs: list[PipelineSpec] = []
    first_plan: FullPlan | None = None
    runnable_plan: FullPlan | None = None
    for label in opts.subjects:
        plan, spec = plan_full_processing(ws, opts.for_subject(label))
        first_plan = first_plan or plan
        if plan.can_start and runnable_plan is None:
            runnable_plan = plan
        reasons = [p.reason for p in plan.stages if p.enabled and not p.can_run and p.reason]
        lines.append(
            BatchSubjectPlan(
                subject=label,
                can_start=plan.can_start and spec is not None,
                steps=plan.steps,
                reason=None if plan.can_start else (reasons[0] if reasons else "Nothing can run."),
            )
        )
        if spec is not None and plan.can_start:
            specs.append(spec)
    shown = runnable_plan or first_plan
    return BatchPlan(
        stages=shown.stages if shown else [], subjects=lines, runnable=len(specs)
    ), specs


def plan_full_processing(ws: Workspace, opts: FullOptions) -> tuple[FullPlan, PipelineSpec | None]:
    """The plan for the dialog and, if anything can run, the pipeline that does it."""
    ctx = PlanContext(ws=ws, opts=opts)
    plans: list[StagePlan] = []
    for stage in STAGES:
        enabled = opts.stages.get(stage.id, stage.default_enabled)
        plans.append(stage.plan(ctx, enabled))
    runnable = [p for p in plans if p.enabled and p.can_run]
    spec = (
        PipelineSpec(
            name=f"full-{opts.subject}",
            subject=opts.subject,
            steps=ctx.steps,
            preset=opts.preset,
        )
        if ctx.steps
        else None
    )
    plan = FullPlan(
        subject=opts.subject,
        stages=plans,
        steps=len(ctx.steps),
        can_start=bool(ctx.steps) and bool(runnable),
    )
    return plan, spec
