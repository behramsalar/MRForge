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
from typing import Any

from pydantic import BaseModel, Field

from mrforge.bids import parse_bids_name
from mrforge.datafiles import subject_data
from mrforge.functional import (
    anat_results,
    fieldmap_status,
    slice_timing_status,
)
from mrforge.niftiutil import image_info
from mrforge.pipeline import PipelineSpec, PipelineStep
from mrforge.resume import check_reusable
from mrforge.workspace import Workspace

# -- what the user can choose ---------------------------------------------------------------


class AnatomicalOptions(BaseModel):
    strong_bias: bool = False
    subcortical_segmentation: bool = False  # slow; not needed for the functional pipeline


class FunctionalOptions(BaseModel):
    # REVIEW(domain): 5 volumes (confirmed); 5 mm FWHM and 150 s high-pass are proposals.
    delete_volumes: int = Field(default=5, ge=0, le=100)
    smoothing_fwhm_mm: float = Field(default=5.0, ge=0, le=20)
    highpass_cutoff_s: float | None = Field(default=150.0, gt=0)  # None: no temporal filtering
    use_fieldmap: bool = True  # used for every run that has a usable fieldmap
    slice_timing: bool = False  # used for every run whose scan records slice times


class FullOptions(BaseModel):
    subject: str
    # Stages switched off on purpose; missing means "as planned by default".
    stages: dict[str, bool] = {}
    anatomical: AnatomicalOptions = AnatomicalOptions()
    functional: FunctionalOptions = FunctionalOptions()


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
        recorded = check_reusable(
            ctx.ws, "fsl_anat", ctx.subject, {"t1": t1.relpath}, params
        ).reusable
        stage.already_done = recorded
        notes = [f"{len(t1s)} T1 images found; the first one is used."] if len(t1s) > 1 else []
        if existing is not None and not recorded and enabled:
            notes.append(
                "Results from an earlier run exist, but MRForge has no record of making them with "
                "these settings, so they are made again (this takes a while). Untick Anatomical "
                "to use the existing results as they are."
            )
        note = " ".join(notes) or None
        stage.items = [
            PlanItem(
                title=f"Process {Path(t1.relpath).name}",
                note=note,
                settings=[
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
        ctx.steps.append(
            PipelineStep(
                id="fsl_anat",
                step="fsl_anat",
                inputs={"t1": t1.relpath},
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
        if enabled:
            ctx.ready.add(self.id)
        return stage


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
                settings=[PlanSetting(name="Resolution", value="2 mm")],
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


# The order of the stages is the order of the pipeline. Stages that clean the data (artifact
# rejection, WM/CSF regression) belong between Functional and Standard space; stages that use
# the finished data (ROI-to-ROI correlation) after it.
STAGES: list[Stage] = [AnatomicalStage(), FunctionalStage(), StandardSpaceStage()]


def plan_full_processing(ws: Workspace, opts: FullOptions) -> tuple[FullPlan, PipelineSpec | None]:
    """The plan for the dialog and, if anything can run, the pipeline that does it."""
    ctx = PlanContext(ws=ws, opts=opts)
    plans: list[StagePlan] = []
    for stage in STAGES:
        enabled = opts.stages.get(stage.id, stage.default_enabled)
        plans.append(stage.plan(ctx, enabled))
    runnable = [p for p in plans if p.enabled and p.can_run]
    spec = (
        PipelineSpec(name=f"full-{opts.subject}", subject=opts.subject, steps=ctx.steps)
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
