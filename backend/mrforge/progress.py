"""Live progress of an operation: which step of the pipeline is running now, which finished,
which were skipped as already done, and what the running tool is doing at this moment.

Nothing extra is stored: the list of steps is the pipeline spec of the operation, and each
step's state is read from the jobs that pipeline run created. Because the engine runs steps
in order, a step without a job that comes before a step with a job was already up to date.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select

from mrforge.models import Job, JobStatus, Operation, PipelineRun
from mrforge.pipeline import PipelineSpec, PipelineStep, parse_pipeline
from mrforge.runner.jobs import list_jobs
from mrforge.steps.fsl_anat import native_folder_name
from mrforge.workspace import Workspace

State = Literal["waiting", "running", "review", "done", "reused", "failed", "stopped"]

# What a tool is doing, in words a researcher understands. First match in the last lines wins.
TOOL_PHRASES: list[tuple[str, str]] = [
    ("mcflirt", "Correcting head motion"),
    ("fugue", "Correcting image distortion"),
    ("epi_reg", "Aligning the functional image to the T1"),
    ("slicetimer", "Correcting slice timing"),
    ("susan", "Smoothing the data"),
    ("-bptf", "Removing slow signal drifts"),
    ("fsl_prepare_fieldmap", "Preparing the fieldmap"),
    ("prelude", "Unwrapping the fieldmap phase"),
    ("convertwarp", "Combining the alignments"),
    ("applywarp", "Moving the data to its new space"),
    ("fnirt", "Fitting the alignment to standard space"),
    ("run_first", "Segmenting deep brain structures"),
    ("first_flirt", "Segmenting deep brain structures"),
    ("fast", "Separating grey matter, white matter and CSF"),
    ("bet", "Removing the skull"),
    ("flirt", "Aligning images"),
    ("slicer", "Drawing the quality-check pictures"),
    ("pngappend", "Drawing the quality-check pictures"),
    ("melodic", "Finding independent components"),
    ("fsl_regfilt", "Removing the noise components"),
    ("feat", "Preprocessing the functional data"),
    ("dcm2niix", "Converting the scanner files"),
]
# FEAT writes section headings into its report; they say where it is.
LINE_PHRASES: list[tuple[str, str]] = [
    ("Preprocessing:Stage 1", "Preparing the functional data (stage 1 of 2)"),
    ("Preprocessing:Stage 2", "Preprocessing the functional data (stage 2 of 2)"),
    ("Unwarping", "Correcting image distortion with the fieldmap"),
    ("Registration", "Aligning the functional image to the T1"),
]
_TAG = re.compile(r"<[^>]+>")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class ProgressStep(BaseModel):
    id: str
    step: str  # the step's name, for example "feat_preproc"
    run: str = ""  # which recording, for example "task-rest"
    state: State
    job_id: int | None = None
    started: datetime | None = None
    finished: datetime | None = None
    now: str | None = None  # plain-language "what is happening", for the running step
    live: list[str] = []  # the latest tool output lines, for the running step


class SubjectProgress(BaseModel):
    """One subject of a batch: where it is, and its steps."""

    subject: str
    state: Literal["queued", "running", "waiting", "review", "done", "failed"]
    steps: list[ProgressStep]
    done: int
    total: int
    now: str | None = None  # the running step in plain words, with what the tool does


class OperationProgress(BaseModel):
    id: int
    title: str
    status: str
    started: datetime | None
    finished: datetime | None
    started_by: str | None
    steps: list[ProgressStep]
    current: int | None  # index of the running (or next waiting) step
    done: int  # steps finished or skipped as already done
    total: int
    log_tail: list[str] = []  # what the operation itself wrote (imports and similar)
    subjects: list[SubjectProgress] = []  # batch: one entry per subject


def _tail(path: Path, lines: int = 12) -> list[str]:
    try:
        text = path.read_text(errors="replace")[-20000:]
    except OSError:
        return []
    out = [_ANSI.sub("", ln).strip() for ln in text.splitlines()]
    return [ln for ln in out if ln][-lines:]


def _shorten(line: str) -> str:
    """'/fsl/bin/fslmaths a b' becomes 'fslmaths a b'; long lines are cut."""
    parts = line.split(" ", 1)
    first = parts[0].rsplit("/", 1)[-1]
    text = first + (" " + parts[1] if len(parts) > 1 else "")
    return text if len(text) <= 160 else text[:157] + "..."


def _phrase(lines: list[str]) -> str | None:
    """The newest recognised tool (or FEAT section heading) in the output, as a plain phrase."""
    for line in reversed(lines):
        for needle, phrase in LINE_PHRASES:
            if line.startswith(needle):
                return phrase
        words = line.split()
        if not words:
            continue
        names = {words[0].rsplit("/", 1)[-1]} | {w for w in words if w.startswith("-")}
        for needle, phrase in TOOL_PHRASES:
            if needle in names:
                return phrase
    return None


def live_info(ws: Workspace, job: Job) -> tuple[str | None, list[str]]:
    """(plain-language activity, latest output lines) of a running job."""
    run_dir = ws.abspath(job.run_dir or "")
    logs = run_dir / "logs"
    lines: list[str] = []
    if job.step_name == "feat_preproc":
        # FEAT writes the commands it runs to its own report while it works.
        raw = _tail(run_dir / "work" / "feat" / "result.feat" / "report_log.html", 40)
        cleaned = [_TAG.sub("", ln).strip() for ln in raw]
        lines = [
            ln for ln in cleaned if ln and not ln.startswith(("Option ", "mkdir", "/bin/mkdir"))
        ][-12:]
    elif job.step_name == "fsl_anat":
        t1 = job.inputs.get("t1")
        if isinstance(t1, str) and job.output_dir:
            lines = _tail(ws.abspath(job.output_dir) / native_folder_name(t1) / "log.txt")
        readable = [ln for ln in _tail(logs / "stdout.log", 30) if not ln.startswith("Tanaka")]
        if readable:  # fsl_anat prints its own stage names; they say most
            return readable[-1][:120], [_shorten(x) for x in (lines or readable)[-8:]]
    if not lines:
        lines = _tail(logs / "stdout.log") + _tail(logs / "stderr.log", 4)
    short = [_shorten(ln) for ln in lines if ln.strip()][-8:]
    return _phrase(lines), short


def _utc(moment: datetime) -> datetime:
    """SQLite hands back stored UTC times without a timezone."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _slug(step_id: str) -> str:
    return step_id.split("__", 1)[1] if "__" in step_id else ""


def _matches(step: PipelineStep, job: Job) -> bool:
    if step.step != job.step_name:
        return False
    slug = _slug(step.id)
    # A fieldmap belongs to the session, not to one recording, so its folder has no recording name.
    # A slug without "-" is the default name of a file with no BIDS entities ("dwi", "bold"):
    # its step folders carry no recording suffix either, so such steps are told apart by order.
    return (
        not slug
        or "-" not in slug
        or step.step == "fieldmap_prep"
        or (job.run_dir or "").endswith(f"_{slug}")
    )


def _state(job: Job) -> State:
    return {
        JobStatus.QUEUED.value: "waiting",
        JobStatus.RUNNING.value: "running",
        JobStatus.COMPLETED.value: "done",
        JobStatus.FAILED.value: "failed",
        JobStatus.WAITING.value: "review",  # waits for the researcher
    }.get(job.status, "stopped")  # type: ignore[return-value]


def _run_name(job: Job) -> str:
    folder = (job.run_dir or "").rsplit("/", 1)[-1]
    return folder.removeprefix(job.label or job.step_name).lstrip("_").replace("_", " ")


def _pipeline_steps(
    ws: Workspace,
    op: Operation,
    spec: PipelineSpec | None = None,
    finished_ok: bool | None = None,
) -> list[ProgressStep]:
    spec = spec or parse_pipeline(op.args["spec"])
    started = op.started or op.created
    with ws.session() as s:
        run = s.scalars(
            select(PipelineRun)
            .where(PipelineRun.name == spec.name)
            .order_by(PipelineRun.id.desc())
            .limit(5)
        ).all()
    began = _utc(started)
    mine = next((r for r in run if _utc(r.created) >= began), None)
    jobs = [j for j in list_jobs(ws) if mine is not None and j.pipeline_run_id == mine.id]
    steps: list[ProgressStep] = []
    cursor = 0
    if finished_ok is None:
        finished_ok = op.status == JobStatus.COMPLETED.value
    matched: list[tuple[PipelineStep, Job | None]] = []
    for st in spec.steps:
        job = None
        for k in range(cursor, len(jobs)):
            if _matches(st, jobs[k]):
                job, cursor = jobs[k], k + 1
                break
        matched.append((st, job))
    last_with_job = max((i for i, (_, j) in enumerate(matched) if j is not None), default=-1)
    for i, (st, job) in enumerate(matched):
        if job is not None:
            state = _state(job)
            now, live = live_info(ws, job) if state == "running" else (None, [])
            if job.status == JobStatus.QUEUED.value:
                now = job.error_message  # why it has not started (free capacity), if so
            steps.append(
                ProgressStep(
                    id=st.id,
                    step=st.step,
                    run="" if st.step == "fieldmap_prep" else _run_name(job),
                    state=state,
                    job_id=job.id,
                    started=job.started,
                    finished=job.finished,
                    now=now,
                    live=live,
                )
            )
        else:
            skipped = i < last_with_job or (finished_ok and i > last_with_job)
            steps.append(
                ProgressStep(
                    id=st.id,
                    step=st.step,
                    run="" if st.step == "fieldmap_prep" else _slug(st.id).replace("_", " "),
                    state="reused" if skipped else "waiting",
                )
            )
    return steps


def _subject_state(steps: list[ProgressStep]) -> str:
    states = {s.state for s in steps}
    if "running" in states:
        return "running"
    if states & {"failed", "stopped"}:
        return "failed"
    if "review" in states:
        return "review"
    if states <= {"done", "reused"}:
        return "done"
    return "queued" if "done" not in states and "reused" not in states else "waiting"


def _batch_subjects(ws: Workspace, op: Operation) -> list[SubjectProgress]:
    out: list[SubjectProgress] = []
    specs: list[Any] = list(op.args.get("specs", []))  # type: ignore[call-overload]
    results: dict[str, str] = {}
    for r in (op.result or {}).get("subjects", []):  # type: ignore[attr-defined]
        results[str(r.get("subject"))] = str(r.get("status"))
    for raw in specs:
        spec = parse_pipeline(raw)
        # Steps that have no job were already done: certain once the subject finished fine,
        # even if another subject of the batch failed.
        steps = _pipeline_steps(ws, op, spec, results.get(spec.subject or spec.name) == "done")
        running = next((s for s in steps if s.state == "running"), None)
        out.append(
            SubjectProgress(
                subject=spec.subject or spec.name,
                state=_subject_state(steps),  # type: ignore[arg-type]
                steps=steps,
                done=sum(1 for s in steps if s.state in ("done", "reused")),
                total=len(steps),
                now=(f"{running.step}: {running.now}" if running and running.now else None),
            )
        )
    return out


def operation_progress(ws: Workspace, op: Operation) -> OperationProgress:
    steps: list[ProgressStep] = []
    subjects: list[SubjectProgress] = []
    if op.kind == "pipeline" and isinstance(op.args.get("spec"), dict):
        steps = _pipeline_steps(ws, op)
    elif op.kind == "batch" and isinstance(op.args.get("specs"), list):
        subjects = _batch_subjects(ws, op)
    current = next((i for i, s in enumerate(steps) if s.state == "running"), None)
    if current is None:
        current = next((i for i, s in enumerate(steps) if s.state == "review"), None)
    if current is None:
        current = next((i for i, s in enumerate(steps) if s.state == "waiting"), None)
    log_tail = _tail(ws.abspath(op.log), 12) if op.log else []
    return OperationProgress(
        id=op.id,
        title=op.title,
        status=op.status,
        started=op.started,
        finished=op.finished,
        started_by=op.started_by,
        steps=steps,
        current=current,
        done=(
            sum(1 for s in subjects if s.state == "done")
            if subjects
            else sum(1 for s in steps if s.state in ("done", "reused"))
        ),
        total=len(subjects) if subjects else len(steps),
        log_tail=log_tail,
        subjects=subjects,
    )
