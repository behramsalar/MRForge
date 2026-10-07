"""The workspace overview for the dashboard: where every subject stands in each stage.

Everything here is derived from what already exists (files, jobs, operations), so it is
always consistent with the rest of the app; nothing extra is stored.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from mrforge.functional import check_ready
from mrforge.models import File, Job, JobStatus, Operation, Subject
from mrforge.operations import list_operations
from mrforge.runner.jobs import list_jobs
from mrforge.workspace import Workspace

State = Literal[
    "none", "unavailable", "waiting", "running", "review", "partial", "done", "failed", "stopped"
]
FUNC_STEPS = ("fieldmap_prep", "feat_preproc", "func_qc", "func_to_mni")
BUSY = (JobStatus.RUNNING.value, JobStatus.QUEUED.value)
ATTENTION_ORDER: tuple[State, ...] = ("running", "review", "waiting", "failed", "stopped")


class StageStatus(BaseModel):
    state: State
    detail: str | None = None  # e.g. "2 of 3 runs"


class StageChip(BaseModel):
    """One stage of one subject, for the status chips (the same list everywhere)."""

    id: str  # import, anatomical, preprocessing, artifact_rejection, standard_space
    label: str
    state: State
    detail: str | None = None


class QcSummary(BaseModel):
    """Motion numbers of a subject's first functional run (reported, never used to exclude)."""

    fd_mean_mm: float
    fd_max_mm: float
    volumes_above: int
    n_volumes: int
    threshold_mm: float


class SubjectOverview(BaseModel):
    label: str
    n_files: int
    anatomical: StageStatus
    functional: StageStatus
    stages: list[StageChip] = []
    complete: bool = False  # everything the standard pipeline does is done
    qc: QcSummary | None = None
    last_activity: datetime | None = None
    last_activity_by: str | None = None


class StageSummary(BaseModel):
    id: str
    label: str
    done: int
    total: int


class RunningItem(BaseModel):
    title: str
    started: datetime | None
    started_by: str | None


class ActivityItem(BaseModel):
    title: str
    status: str
    when: datetime
    started_by: str | None


class ReviewItem(BaseModel):
    """Something that waits for the researcher (for example component labelling)."""

    subject: str
    what: str  # plain language: "Label the components of task-rest"
    since: datetime
    page: str  # where to go, as a page name in the app ("process/ica")


class Overview(BaseModel):
    subjects_total: int
    processed: int  # anatomical and every functional run done
    needs_attention: int  # at least one failed or stopped step
    running: int
    stages: list[StageSummary]
    subjects: list[SubjectOverview]
    running_now: list[RunningItem]
    recent: list[ActivityItem]
    review: list[ReviewItem] = []


def _repeated_since(op: Operation, ops: list[Operation]) -> bool:
    """A failed or stopped task that was later done again successfully is old news."""
    if op.status == JobStatus.COMPLETED.value:
        return False
    return any(
        o.id > op.id and o.title == op.title and o.status == JobStatus.COMPLETED.value for o in ops
    )


def _waiting_for_you(subject: str, jobs: list[Job]) -> list[ReviewItem]:
    """The newest job of every run folder, if that job is waiting for the researcher."""
    newest: dict[str, Job] = {}
    for j in jobs:
        newest[j.run_dir or str(j.id)] = j
    return [
        ReviewItem(
            subject=subject,
            what=("Label the components" + (f" of {_run_name(j)}" if _run_name(j) else "")),
            since=j.created,
            page="process/ica",
        )
        for j in newest.values()
        if j.status == JobStatus.WAITING.value and j.step_name == "ica_labels"
    ]


def _job_state(status: str) -> State:
    states: dict[str, State] = {
        JobStatus.QUEUED.value: "waiting",
        JobStatus.RUNNING.value: "running",
        JobStatus.COMPLETED.value: "done",
        JobStatus.FAILED.value: "failed",
        JobStatus.INTERRUPTED.value: "stopped",
        JobStatus.WAITING.value: "review",
        JobStatus.CANCELLED.value: "stopped",
    }
    return states.get(status, "none")


def _run_name(job: Job) -> str:
    folder = (job.run_dir or "").rsplit("/", 1)[-1]
    return folder.removeprefix(job.label or job.step_name).lstrip("_").replace("_", " ")


def _run_jobs(jobs: list[Job], run: str) -> list[Job]:
    """The functional-step jobs of one BOLD run (oldest first). A fieldmap step has no run of
    its own, so one that is newer than the run's last attempt counts for it too: when it
    fails the pipeline stops before the run's own steps start."""
    own = [j for j in jobs if j.step_name in FUNC_STEPS[1:] and _run_name(j) == run]
    newest = max((j.id for j in own), default=0)
    shared = [j for j in jobs if j.step_name == "fieldmap_prep" and j.id > newest]
    return sorted(own + shared, key=lambda j: j.id)


def _functional_run_state(jobs: list[Job]) -> State:
    """State of one BOLD run from the jobs of its functional steps (oldest first)."""
    if not jobs:
        return "none"
    latest: dict[str, Job] = {}
    for job in jobs:
        latest[job.step_name] = job
    states = {step: _job_state(j.status) for step, j in latest.items()}
    for wanted in ATTENTION_ORDER:
        if wanted in states.values():
            return wanted
    qc_done = states.get("func_qc") == "done"
    mni_ok = states.get("func_to_mni", "done") == "done"
    return "done" if qc_done and mni_ok else "partial"


def _stage_state(jobs: list[Job], need: tuple[str, ...], also: tuple[str, ...] = ()) -> State:
    """State of a stage made of steps, over every recording: ``need`` steps must all be done."""
    mine = [j for j in jobs if j.step_name in need + also]
    if not mine:
        return "none"
    runs = sorted({_run_name(j) for j in mine if j.step_name in need} or {""})
    per_run: list[State] = []
    for run in runs:
        latest: dict[str, Job] = {}
        for j in mine:
            if j.step_name in also or _run_name(j) == run:
                latest[j.step_name] = j
        states = {step: _job_state(j.status) for step, j in latest.items()}
        picked = next((w for w in ATTENTION_ORDER if w in states.values()), None)
        if picked:
            per_run.append(picked)
        elif all(states.get(step) == "done" for step in need):
            per_run.append("done")
        else:
            per_run.append("partial")
    return _aggregate(per_run)


def _decided_by(ws: Workspace, subject: str) -> str | None:
    """Who or what labelled the components (from the record the labelling step wrote)."""
    for path in sorted((ws.derivatives_dir / subject).rglob("*_labels.json")):
        if "_runs" in path.parts:
            continue
        try:
            who = json.loads(path.read_text()).get("decided_by")
        except (OSError, ValueError):
            continue
        if who:
            return str(who)
    return None


def _qc_summary(ws: Workspace, subject: str) -> QcSummary | None:
    for path in sorted((ws.derivatives_dir / subject).rglob("*_desc-metrics_qc.json")):
        if "_runs" in path.parts:
            continue
        try:
            m = json.loads(path.read_text())
            return QcSummary(
                fd_mean_mm=round(float(m["fd_mean_mm"]), 3),
                fd_max_mm=round(float(m["fd_max_mm"]), 3),
                volumes_above=int(m["fd_above_threshold"]),
                n_volumes=int(m["n_volumes"]),
                threshold_mm=float(m["fd_threshold_mm"]),
            )
        except (OSError, ValueError, KeyError):
            continue
    return None


def _stage_summaries(rows: list[SubjectOverview]) -> list[StageSummary]:
    """How many subjects have finished each stage (the dashboard's pipeline overview).
    Subjects for which a stage is not possible (no T1, no functional run) are not counted."""
    out: list[StageSummary] = []
    for stage_id in (
        "import",
        "anatomical",
        "preprocessing",
        "artifact_rejection",
        "standard_space",
    ):
        chips = [c for r in rows for c in r.stages if c.id == stage_id and c.state != "unavailable"]
        label = chips[0].label if chips else stage_id
        if stage_id == "artifact_rejection":
            label += " (optional)"
        out.append(
            StageSummary(
                id=stage_id,
                label=label,
                done=sum(1 for c in chips if c.state == "done"),
                total=len(chips) if stage_id != "import" else len(rows),
            )
        )
    return out


def _aggregate(states: list[State]) -> State:
    if not states:
        return "none"
    for wanted in ATTENTION_ORDER:
        if wanted in states:
            return wanted
    if all(s == "done" for s in states):
        return "done"
    return "partial" if any(s in ("done", "partial") for s in states) else "none"


def build_overview(ws: Workspace) -> Overview:
    jobs = list_jobs(ws)
    with ws.session() as s:
        subjects = list(s.scalars(select(Subject).order_by(Subject.label)))
        files = list(s.execute(select(File.subject_id, File.relpath, File.kind)).all())
    by_subject: dict[int, list[Job]] = {}
    for job in jobs:
        if job.subject_id is not None:
            by_subject.setdefault(job.subject_id, []).append(job)

    rows: list[SubjectOverview] = []
    review: list[ReviewItem] = []
    anat_total = anat_done = func_total = func_done = 0
    processed = attention = 0
    for sub in subjects:
        mine = by_subject.get(sub.id, [])
        raw = [
            (rel, kind) for sid, rel, kind in files if sid == sub.id and rel.startswith("rawbids/")
        ]
        has_t1 = any(kind == "T1w" for _, kind in raw)
        ready = check_ready(ws, sub.label)

        anat_jobs = [j for j in mine if j.step_name == "fsl_anat"]
        if ready.anat_ready:
            anat = StageStatus(state="done")
            if anat_jobs and anat_jobs[-1].status in (
                JobStatus.RUNNING.value,
                JobStatus.QUEUED.value,
            ):
                anat = StageStatus(state=_job_state(anat_jobs[-1].status))
        elif anat_jobs:
            anat = StageStatus(state=_job_state(anat_jobs[-1].status))
        elif has_t1:
            anat = StageStatus(state="none")
        else:
            anat = StageStatus(state="unavailable", detail="No T1 image")

        run_states = [_functional_run_state(_run_jobs(mine, run.name)) for run in ready.runs]
        if not ready.runs:
            func = StageStatus(state="unavailable", detail="No functional run")
        else:
            agg = _aggregate(run_states)
            done_runs = sum(1 for r in run_states if r == "done")
            detail = f"{done_runs} of {len(run_states)} runs" if len(run_states) > 1 else None
            func = StageStatus(state=agg, detail=detail)

        review.extend(_waiting_for_you(sub.label, mine))
        pre = _stage_state(mine, ("feat_preproc", "func_qc"), also=("fieldmap_prep",))
        art = _stage_state(mine, ("melodic", "ica_labels", "regfilt"), also=("aroma_classify",))
        std = _stage_state(mine, ("func_to_mni",))
        has_func = bool(ready.runs)
        chips = [
            StageChip(id="import", label="Import", state="done" if raw else "none"),
            StageChip(id="anatomical", label="Anatomical", state=anat.state, detail=anat.detail),
            StageChip(
                id="preprocessing",
                label="Preprocessing",
                state=pre if has_func else "unavailable",
                detail=None if has_func else "No functional run",
            ),
            StageChip(
                id="artifact_rejection",
                label="Artifact rejection",
                state=art if has_func else "unavailable",
                detail=_decided_by(ws, sub.label) if art == "done" else None,
            ),
            StageChip(
                id="standard_space",
                label="Standard space",
                state=std if has_func else "unavailable",
            ),
        ]
        complete = anat.state == "done" and (not has_func or (pre == "done" and std == "done"))
        last = max(mine, key=lambda j: j.id) if mine else None
        rows.append(
            SubjectOverview(
                label=sub.label,
                n_files=len(raw),
                anatomical=anat,
                functional=func,
                stages=chips,
                complete=complete,
                qc=_qc_summary(ws, sub.label),
                last_activity=(last.finished or last.started or last.created) if last else None,
                last_activity_by=last.started_by if last else None,
            )
        )
        if has_t1 or anat.state != "unavailable":
            anat_total += anat.state != "unavailable"
            anat_done += anat.state == "done"
        if ready.runs:
            func_total += 1
            func_done += func.state == "done"
        states = [anat.state, func.state]
        if any(x in ("failed", "stopped") for x in states):
            attention += 1
        elif anat.state == "done" and func.state in ("done", "unavailable"):
            processed += 1

    ops = list_operations(ws)
    running_ops = [o for o in ops if o.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value)]
    recent = [
        ActivityItem(
            title=o.title,
            status=o.status,
            when=o.finished or o.started or o.created,
            started_by=o.started_by,
        )
        for o in sorted(ops, key=lambda o: o.id, reverse=True)
        if not _repeated_since(o, ops)
    ][:8]
    return Overview(
        subjects_total=len(subjects),
        processed=processed,
        needs_attention=attention,
        running=len(running_ops),
        stages=_stage_summaries(rows),
        subjects=rows,
        running_now=[
            RunningItem(title=o.title, started=o.started or o.created, started_by=o.started_by)
            for o in running_ops
        ],
        recent=recent,
        review=review,
    )
