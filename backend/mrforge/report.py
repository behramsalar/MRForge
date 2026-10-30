"""The report of one subject, built only from what was recorded.

Nothing here runs a tool or guesses: every number comes from a step's ``provenance.json``, the
import manifests or the researcher's quality decisions (CLAUDE.md principle 7). Of every step
run, the latest completed one whose results are still there is reported; steps that never ran
are listed as "not run", so a gap is visible rather than silently missing.
"""

from __future__ import annotations

import shlex
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from mrforge import __version__, qc_decisions
from mrforge.importing.classify import effective_all, load_rules
from mrforge.importing.manifest import list_manifests
from mrforge.models import Job, JobStatus, Subject
from mrforge.provenance import read_provenance
from mrforge.workspace import Workspace

# Report sections in reading order: id, title, steps that belong there (in processing order).
SECTIONS: list[tuple[str, str, list[str]]] = [
    ("anatomical", "Structural (anatomical) processing", ["resample_t1", "bet", "fsl_anat"]),
    (
        "functional",
        "Functional preprocessing",
        ["fieldmap_prep", "feat_preproc", "func_qc"],
    ),
    (
        "artifact",
        "Artifact rejection (denoising)",
        ["melodic", "aroma_classify", "ica_labels", "regfilt"],
    ),
    ("standard", "Standard space", ["func_to_mni"]),
]
STEP_TITLES = {
    "resample_t1": "Resampling of the T1 to 1 mm",
    "bet": "Brain extraction (bet)",
    "fsl_anat": "Anatomical processing (fsl_anat)",
    "fieldmap_prep": "Field map preparation",
    "feat_preproc": "Functional preprocessing (FEAT)",
    "func_qc": "Head motion and registration",
    "melodic": "Independent components (MELODIC)",
    "aroma_classify": "Components proposed as noise (ICA-AROMA)",
    "ica_labels": "Component labels (your decision)",
    "regfilt": "Noise removal",
    "func_to_mni": "Alignment to standard space",
}


class ReportSlice(BaseModel):
    plane: str
    position: float
    layer: str
    image: str  # workspace-relative path


class ReportQc(BaseModel):
    name: str
    kind: str
    value: str | None = None
    warning: str | None = None
    image: str | None = None  # workspace-relative path of a picture
    slices: list[ReportSlice] = []  # the single slices of that picture, when they were kept


class ReportCommand(BaseModel):
    command: str  # shell-quoted, ready to copy
    return_code: int
    stdout_log: str
    stderr_log: str


class ReportRun(BaseModel):
    step: str
    title: str
    label: str
    recording: str  # e.g. "task-rest"; empty for steps without a recording
    job_id: int
    step_version: str
    started: str | None
    finished: str | None
    started_by: str | None
    parameters: dict[str, Any]
    inputs: int  # number of input files (hashes are in provenance.json)
    outputs: int
    qc: list[ReportQc] = []
    warnings: list[str] = []
    commands: list[ReportCommand] = []
    tool_versions: dict[str, str] = {}
    run_dir: str


class ReportSection(BaseModel):
    id: str
    title: str
    runs: list[ReportRun] = []
    not_run: list[str] = []  # titles of the steps of this section that have no result


class ReportSeries(BaseModel):
    number: int | None
    description: str
    kind: str  # what it was imported as, e.g. "bold"
    volumes: int | None
    matrix: str
    repetition_time_s: float | None
    echo_time_s: float | None
    import_id: str
    session: str | None


class ReportDecision(BaseModel):
    decision: str
    reason: str
    who: str | None
    when: str
    motion: dict[str, float] | None = None


class SubjectReport(BaseModel):
    subject: str
    generated: str
    mrforge_version: str
    acquisition: list[ReportSeries]
    sections: list[ReportSection]
    decisions: list[ReportDecision]  # the history, oldest first
    warnings: list[str]  # every warning of every reported run, with the step it came from
    software: dict[str, str]  # tool -> version, over all reported runs


def _recording(run_dir: str, label: str) -> str:
    folder = run_dir.rsplit("/", 1)[-1]
    return folder.removeprefix(label).lstrip("_").replace("_", " ")


def _latest_runs(ws: Workspace, subject: str) -> list[Job]:
    """The latest completed run of every step instance (one per results folder)."""
    with ws.session() as s:
        subject_id = s.scalar(select(Subject.id).where(Subject.label == subject))
        jobs = list(
            s.scalars(
                select(Job)
                .where(Job.subject_id == subject_id)
                .where(Job.status == JobStatus.COMPLETED.value)
                .order_by(Job.id)
            )
        )
        s.expunge_all()
    latest: dict[str, Job] = {}
    for job in jobs:
        latest[job.run_dir or f"job-{job.id}"] = job
    return list(latest.values())


def _run(ws: Workspace, job: Job) -> ReportRun | None:
    prov = read_provenance(ws.abspath(job.run_dir or ""))
    if prov is None or any(not ws.abspath(o.path).is_file() for o in prov.outputs):
        return None  # the record or a result is gone: not reported as if it were there
    out_dir = ws.abspath(job.output_dir or "")
    qc: list[ReportQc] = []
    for item in prov.qc:
        qc.append(
            ReportQc(
                name=item.name,
                kind=item.kind,
                value=None if item.value is None else str(item.value),
                warning=item.warning,
                image=ws.relpath(out_dir / item.path) if item.path else None,
                slices=[
                    ReportSlice(
                        plane=sl.plane,
                        position=sl.position,
                        layer=sl.layer,
                        image=ws.relpath(out_dir / sl.path),
                    )
                    for sl in item.slices
                    if (out_dir / sl.path).is_file()
                ],
            )
        )
    warnings = [w.message for w in prov.warnings] + [q.warning for q in qc if q.warning]
    label = job.label or job.step_name
    return ReportRun(
        step=job.step_name,
        title=STEP_TITLES.get(job.step_name, job.step_name),
        label=label,
        recording=_recording(job.run_dir or "", label),
        job_id=job.id,
        step_version=prov.step.version,
        started=prov.started.isoformat() if prov.started else None,
        finished=prov.finished.isoformat() if prov.finished else None,
        started_by=job.started_by,
        parameters=prov.parameters,
        inputs=len(prov.inputs),
        outputs=len(prov.outputs),
        qc=qc,
        warnings=warnings,
        commands=[
            ReportCommand(
                command=shlex.join(c.argv),
                return_code=c.return_code,
                stdout_log=c.stdout_log,
                stderr_log=c.stderr_log,
            )
            for c in prov.commands
        ],
        tool_versions=prov.tool_versions,
        run_dir=job.run_dir or "",
    )


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _acquisition(ws: Workspace, subject: str) -> list[ReportSeries]:
    rules = load_rules(ws)
    rows: list[ReportSeries] = []
    for manifest in list_manifests(ws):
        if manifest.subject != subject or manifest.undone and not manifest.organized:
            continue
        plan = effective_all(manifest, rules)
        for series in manifest.series:
            if series.uid not in manifest.organized:
                continue  # only what really went into the data folder
            rows.append(
                ReportSeries(
                    number=series.number,
                    description=series.label,
                    kind=plan[series.uid].kind,
                    volumes=series.volumes,
                    matrix=series.matrix,
                    repetition_time_s=_r(series.repetition_time_s),
                    echo_time_s=_r(series.echo_time_s),
                    import_id=manifest.id,
                    session=manifest.session,
                )
            )
    return rows


def build_report(ws: Workspace, subject: str) -> SubjectReport:
    runs = [r for job in _latest_runs(ws, subject) if (r := _run(ws, job)) is not None]
    sections: list[ReportSection] = []
    placed: set[str] = set()
    for sid, title, steps in SECTIONS:
        mine = [r for r in runs if r.step in steps]
        mine.sort(key=lambda r: (steps.index(r.step), r.recording, r.job_id))
        placed.update(steps)
        missing = [STEP_TITLES[s] for s in steps if not any(r.step == s for r in mine)]
        sections.append(ReportSection(id=sid, title=title, runs=mine, not_run=missing))
    other = [r for r in runs if r.step not in placed]
    if other:
        sections.append(ReportSection(id="other", title="Other steps", runs=other))
    software: dict[str, str] = {"MRForge": __version__}
    for r in runs:
        software.update(r.tool_versions)
    warnings = [f"{r.title} {r.recording}".strip() + f": {w}" for r in runs for w in r.warnings]
    return SubjectReport(
        subject=subject,
        generated=datetime.now(UTC).isoformat(timespec="seconds"),
        mrforge_version=__version__,
        acquisition=_acquisition(ws, subject),
        sections=sections,
        decisions=[ReportDecision(**e.model_dump()) for e in qc_decisions.history(ws, subject)],
        warnings=warnings,
        software=software,
    )
