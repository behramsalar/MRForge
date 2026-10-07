"""Operations: long-running actions that are not processing steps (importing a DICOM session,
running a pipeline, removing a DICOM copy).

Each runs in its own detached worker process (``python -m mrforge.operations``), like a job,
so closing the browser or restarting the server never stops it. Progress lines go to a log
file; the outcome (result or structured error) is stored on the Operation row.
Only one operation runs per workspace at a time: they all write to rawbids/ or the database.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

import psutil
from sqlalchemy import select

from mrforge.analysis_ready import refresh as refresh_analysis_ready
from mrforge.batch import run_batch
from mrforge.engine import Action, run_pipeline
from mrforge.errors import StepError
from mrforge.importing.bids_validate import format_report, validate_dataset
from mrforge.importing.classify import load_rules
from mrforge.importing.convert import convert_import
from mrforge.importing.manifest import load_manifest, save_manifest
from mrforge.importing.organize import organize
from mrforge.importing.scan import scan_group
from mrforge.importing.sourcedata import remove_dicom
from mrforge.importing.undo import undo_import
from mrforge.models import Job, JobStatus, Operation
from mrforge.pipeline import parse_pipeline
from mrforge.runner.jobs import get_job, kill_orphans, list_jobs, now, process_alive
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401  (registers built-in steps)
from mrforge.workspace import Workspace

Log = Callable[[str], None]
Handler = Callable[[Workspace, dict[str, Any], Log], dict[str, Any]]
ACTIVE = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


# -- handlers ---------------------------------------------------------------


def _scan(ws: Workspace, args: dict[str, Any], log: Log) -> dict[str, Any]:
    log("Reading the scanner files...")
    manifests, is_new = scan_group(
        ws, Path(args["source"]), args.get("subject"), args.get("session"), progress=log
    )
    if is_new and args.get("started_by"):
        for manifest in manifests:
            manifest.created_by = args["started_by"]
            save_manifest(ws, manifest)
    return {
        "import_id": manifests[0].id,  # the first (the only one for a single scan)
        "import_ids": [m.id for m in manifests],
        "group_size": len(manifests),
        "is_new": is_new,
    }


def _import_run(ws: Workspace, args: dict[str, Any], log: Log) -> dict[str, Any]:
    manifest = load_manifest(ws, args.get("import_id"))
    rules = load_rules(ws)
    summary = convert_import(ws, manifest, rules, args.get("jobs", 4), False, log)
    if summary.failed:
        raise StepError(
            code="CONVERSION_FAILED",
            message="Some series could not be converted: "
            + ", ".join(map(str, summary.failed))
            + ". Nothing was written to rawbids/.",
            probable_cause="The scanner files of those series are incomplete or unusual.",
            suggested_action="Leave those series out (set them to skip) and import again; "
            "series that already converted are not converted twice.",
        )
    log("Writing the BIDS dataset...")
    written = organize(ws, manifest, rules)
    result: dict[str, Any] = {
        "import_id": manifest.id,
        "written": len(written.written),
        "in_place": len(written.in_place),
    }
    try:
        report = validate_dataset(ws)
        result["bids_ok"] = report.ok
        result["bids_report"] = format_report(report)
    except StepError as err:  # the check is a bonus: its absence must not undo the import
        result["bids_ok"] = None
        result["bids_report"] = f"BIDS check skipped: {err.message} {err.suggested_action}"
    if args.get("remove_dicom"):
        remove_dicom(ws, manifest, rules)
        result["dicom_removed"] = True
    return result


def _remove_dicom(ws: Workspace, args: dict[str, Any], log: Log) -> dict[str, Any]:
    manifest = load_manifest(ws, args.get("import_id"))
    plan = remove_dicom(ws, manifest, load_rules(ws))
    return {"import_id": manifest.id, "freed_bytes": plan.size_bytes}


def _undo_import(ws: Workspace, args: dict[str, Any], log: Log) -> dict[str, Any]:
    manifest = load_manifest(ws, args.get("import_id"))
    log("Removing the files this import wrote into the data folder...")
    plan = undo_import(ws, manifest, args.get("started_by"))
    return {"import_id": manifest.id, "files_removed": len(plan.files)}


def _pipeline(ws: Workspace, args: dict[str, Any], log: Log) -> dict[str, Any]:
    spec = parse_pipeline(args["spec"])
    queue = LocalJobQueue(ws, max_concurrency=args.get("max_concurrency", 2))
    log(f"Running pipeline '{spec.name}'...")
    outcomes = run_pipeline(ws, queue, spec, args.get("started_by"))
    for o in outcomes:
        log(f"{o.step_id}: {o.action.value}")
    failed = [o for o in outcomes if o.action == Action.FAILED]
    if failed:
        # The failing job already holds the structured error; point the user at it.
        raise StepError(
            code="PIPELINE_STEP_FAILED",
            message=f"The step '{failed[0].step_id}' did not finish.",
            probable_cause="See the step's own explanation.",
            suggested_action="Fix the cause, then resume: finished steps are not repeated.",
        )
    refresh_analysis_ready(ws)  # the folder for group analysis follows what is finished
    return {
        "steps": [
            {"id": o.step_id, "action": o.action.value, "job_id": o.job_id} for o in outcomes
        ],
        # Steps that need the researcher: the operation ends as "Waiting"; nothing keeps running.
        "waiting": [o.step_id for o in outcomes if o.action == Action.WAITING],
    }


def _batch(ws: Workspace, args: dict[str, Any], log: Log) -> dict[str, Any]:
    specs = [parse_pipeline(d) for d in args["specs"]]
    log(f"Processing {len(specs)} subjects, {args.get('max_subjects', 2)} at a time...")
    results = run_batch(ws, specs, int(args.get("max_subjects", 2)), args.get("started_by"), log)
    refresh_analysis_ready(ws)
    failed = [r for r in results if r.status == "failed"]
    if failed:
        err = StepError(
            code="BATCH_SUBJECTS_FAILED",
            message=f"{len(failed)} of {len(results)} subjects did not finish "
            f"({', '.join(r.subject for r in failed[:5])}{'...' if len(failed) > 5 else ''}).",
            probable_cause="See each subject's own explanation; the others are not affected.",
            suggested_action="Fix the cause, then resume: finished work is not repeated.",
        )
        err.result = {"subjects": [r.as_dict() for r in results], "waiting": []}  # type: ignore[attr-defined]
        raise err
    return {
        "subjects": [r.as_dict() for r in results],
        "waiting": [r.subject for r in results if r.status == "waiting"],
    }


HANDLERS: dict[str, Handler] = {
    "scan": _scan,
    "import_run": _import_run,
    "remove_dicom": _remove_dicom,
    "undo_import": _undo_import,
    "pipeline": _pipeline,
    "batch": _batch,
}


# -- lifecycle ----------------------------------------------------------------


def get_operation(ws: Workspace, op_id: int) -> Operation:
    with ws.session() as s:
        op = s.get(Operation, op_id)
        if op is None:
            raise StepError(
                code="UNKNOWN_OPERATION",
                message=f"There is no operation number {op_id}.",
                suggested_action="Reload the page to see the current list.",
            )
        return op


def list_operations(ws: Workspace) -> list[Operation]:
    with ws.session() as s:
        return list(s.scalars(select(Operation).order_by(Operation.id)))


def _update(ws: Workspace, op_id: int, **fields: Any) -> None:
    with ws.session() as s:
        op = s.get(Operation, op_id)
        assert op is not None
        for key, value in fields.items():
            setattr(op, key, value)


def active_operation(ws: Workspace) -> Operation | None:
    recover_stale_operations(ws)
    for op in list_operations(ws):
        if op.status in ACTIVE:
            return op
    return None


def start_operation(
    ws: Workspace, kind: str, title: str, args: dict[str, Any], started_by: str | None = None
) -> int:
    """Create an operation and start its worker. Refuses while another one is running."""
    if kind not in HANDLERS:
        raise StepError(
            code="UNKNOWN_OPERATION_KIND",
            message=f"MRForge does not know the action '{kind}'.",
            suggested_action="Reload the page; if this keeps happening, update MRForge.",
        )
    busy = active_operation(ws)
    if busy is not None:
        raise StepError(
            code="OPERATION_BUSY",
            message=f"Something else is still running in this workspace: {busy.title}.",
            probable_cause="Imports and pipelines change the same data, so they run one at a time.",
            suggested_action="Wait for it to finish (or cancel it), then try again.",
        )
    with ws.session() as s:
        op = Operation(
            kind=kind,
            title=title,
            args=args,
            status=JobStatus.QUEUED.value,
            started_by=started_by,
        )
        s.add(op)
        s.flush()
        op_id = op.id
    log_rel = f"operations/op-{op_id:04d}.log"
    log_path = ws.abspath(log_rel)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _update(ws, op_id, log=log_rel)
    with log_path.open("ab") as log:
        subprocess.Popen(
            [sys.executable, "-m", "mrforge.operations", str(ws.root), str(op_id)],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    return op_id


def cancel_operation(ws: Workspace, op_id: int) -> None:
    """Stop an operation. Its running jobs are cancelled first (so they are recorded as
    Cancelled, not as crashed), then the operation's own worker."""
    op = get_operation(ws, op_id)
    if op.status != JobStatus.RUNNING.value or not process_alive(op.pid, op.pid_start_time):
        return
    assert op.pid is not None
    running = [
        j for j in list_jobs(ws) if j.status == JobStatus.RUNNING.value and j.pid is not None
    ]
    for job in running:
        if process_alive(job.pid, job.pid_start_time):
            os.kill(job.pid, signal.SIGTERM)  # type: ignore[arg-type]
    deadline = time.monotonic() + 10
    while running and time.monotonic() < deadline:
        if all(get_job(ws, j.id).status != JobStatus.RUNNING.value for j in running):
            break
        time.sleep(0.2)
    if process_alive(op.pid, op.pid_start_time):
        os.kill(op.pid, signal.SIGTERM)
        for _ in range(50):  # the worker needs a moment to finish
            if not process_alive(op.pid, op.pid_start_time):
                break
            time.sleep(0.1)
    drop_orphan_jobs(ws, JobStatus.CANCELLED, "The step was cancelled before it started.")


def drop_orphan_jobs(ws: Workspace, status: JobStatus, message: str) -> list[int]:
    """Jobs still Queued although no operation is active can never start (their queue is gone,
    for example the worker was killed or cancelled). They would make a later run look as if it
    had not completed, so they are closed."""
    if any(
        op.status in ACTIVE and process_alive(op.pid, op.pid_start_time)
        for op in list_operations(ws)
    ):
        return []
    closed: list[int] = []
    for job in list_jobs(ws):
        if job.status != JobStatus.QUEUED.value:
            continue
        error = StepError(status.name, message, suggested_action="Resume the pipeline.").to_dict()
        with ws.session() as s:
            row = s.get(Job, job.id)
            assert row is not None
            row.status = status.value
            row.finished = now()
            row.error_code = status.name
            row.error_message = message
            row.error = error
        closed.append(job.id)
    return closed


def _age_s(created: datetime) -> float:
    """Seconds since ``created`` (SQLite returns stored UTC times without a timezone)."""
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (now() - created).total_seconds()


def recover_stale_operations(ws: Workspace) -> list[int]:
    """Operations whose worker is gone become Interrupted (also never-started ones)."""
    recovered: list[int] = []
    for op in list_operations(ws):
        if op.status not in ACTIVE or process_alive(op.pid, op.pid_start_time):
            continue
        # A just-created operation has no PID yet: give its worker a moment to start.
        if op.status == JobStatus.QUEUED.value and _age_s(op.created) < 10:
            continue
        if op.pid:
            kill_orphans(op.pid)
        _update(
            ws,
            op.id,
            status=JobStatus.INTERRUPTED.value,
            finished=now(),
            error=StepError(
                "INTERRUPTED",
                "This action was stopped before it finished.",
                probable_cause="The program was killed or the computer restarted.",
                suggested_action="Start it again; anything already finished is kept.",
            ).to_dict(),
        )
        recovered.append(op.id)
    if recovered:
        drop_orphan_jobs(ws, JobStatus.INTERRUPTED, "This step was stopped before it started.")
    return recovered


# -- worker process -----------------------------------------------------------


class Cancelled(BaseException):
    pass


def _on_sigterm(signum: int, frame: FrameType | None) -> None:
    for child in psutil.Process().children(recursive=True):
        try:
            child.kill()
        except psutil.Error:
            pass
    raise Cancelled


def run_operation(ws: Workspace, op_id: int) -> JobStatus:
    op = get_operation(ws, op_id)
    me = psutil.Process()
    _update(
        ws,
        op_id,
        status=JobStatus.RUNNING.value,
        pid=me.pid,
        pid_start_time=me.create_time(),
        started=now(),
    )

    def log(line: str) -> None:
        print(line, flush=True)

    status = JobStatus.COMPLETED
    result: dict[str, Any] | None = None
    error: StepError | None = None
    try:
        result = HANDLERS[op.kind](ws, {**op.args, "started_by": op.started_by}, log)
        if result.get("waiting"):
            status = JobStatus.WAITING
    except Cancelled:
        status, error = JobStatus.CANCELLED, StepError("CANCELLED", "The action was cancelled.")
    except StepError as err:
        status = JobStatus.INTERRUPTED if err.code == "COMMAND_KILLED" else JobStatus.FAILED
        error = err
        result = getattr(err, "result", None)  # a batch keeps what each subject did
    except Exception as exc:  # last resort: still give the user something readable
        status = JobStatus.FAILED
        error = StepError(
            "UNEXPECTED_ERROR",
            "Something unexpected went wrong.",
            probable_cause=f"{type(exc).__name__}: {exc}",
            suggested_action="Open the log and report the problem.",
            log_path=Path(op.log) if op.log else None,
        )
        import traceback

        traceback.print_exc()
    finally:
        kill_orphans(me.pid)
    _update(
        ws,
        op_id,
        status=status.value,
        finished=now(),
        result=result,
        error=error.to_dict() if error else None,
    )
    return status


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGTERM, _on_sigterm)
    ws = Workspace.open(Path(argv[0]))
    try:
        status = run_operation(ws, int(argv[1]))
    except Cancelled:
        _update(
            ws,
            int(argv[1]),
            status=JobStatus.CANCELLED.value,
            finished=now(),
            error=StepError("CANCELLED", "The action was cancelled.").to_dict(),
        )
        return 1
    return 0 if status in (JobStatus.COMPLETED, JobStatus.WAITING) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
