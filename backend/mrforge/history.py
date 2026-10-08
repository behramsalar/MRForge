"""The full record of one step run, for the command history: what was run (the exact
commands, ready to copy), with which settings and files, by whom and when. Built from the
job row and its ``provenance.json``; nothing is run or guessed."""

from __future__ import annotations

import shlex
from typing import Any

from pydantic import BaseModel

from mrforge.provenance import read_provenance
from mrforge.runner.jobs import get_job
from mrforge.workspace import Workspace


class HistoryFile(BaseModel):
    path: str
    sha256: str


class HistoryCommand(BaseModel):
    command: str  # shell-quoted, ready to paste into a terminal that has FSL set up
    return_code: int
    stdout_log: str
    stderr_log: str


class JobRecord(BaseModel):
    id: int
    step: str
    step_version: str
    label: str
    subject: str | None
    session: str | None
    status: str
    started: str | None
    finished: str | None
    started_by: str | None
    parameters: dict[str, Any]
    inputs: list[HistoryFile]
    outputs: list[HistoryFile]
    commands: list[HistoryCommand]
    tool_versions: dict[str, str]
    error_message: str | None
    run_dir: str
    has_provenance: bool  # False for a run that stopped before writing its record


def job_record(ws: Workspace, job_id: int, subject: str | None) -> JobRecord:
    job = get_job(ws, job_id)
    prov = read_provenance(ws.abspath(job.run_dir or "")) if job.run_dir else None
    # The record is only about this run if it belongs to it (the folder is reused by reruns).
    if prov is not None and prov.job_id != job.id:
        prov = None
    return JobRecord(
        id=job.id,
        step=job.step_name,
        step_version=prov.step.version if prov else job.step_version,
        label=job.label or job.step_name,
        subject=subject,
        session=job.session,
        status=job.status,
        started=job.started.isoformat() if job.started else None,
        finished=job.finished.isoformat() if job.finished else None,
        started_by=job.started_by,
        parameters=prov.parameters if prov else dict(job.params),
        inputs=[HistoryFile(path=f.path, sha256=f.sha256) for f in prov.inputs] if prov else [],
        outputs=[HistoryFile(path=f.path, sha256=f.sha256) for f in prov.outputs] if prov else [],
        commands=[
            HistoryCommand(
                command=shlex.join(c.argv),
                return_code=c.return_code,
                stdout_log=c.stdout_log,
                stderr_log=c.stderr_log,
            )
            for c in (prov.commands if prov else [])
        ],
        tool_versions=prov.tool_versions if prov else {},
        error_message=job.error_message,
        run_dir=job.run_dir or "",
        has_provenance=prov is not None,
    )
