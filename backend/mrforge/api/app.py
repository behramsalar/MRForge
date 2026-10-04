"""The FastAPI application. Routes are thin: they call the engine, import code and the
operation/job system, and translate plain-language StepErrors into JSON the UI can show."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from mrforge import __version__, accounts
from mrforge.api import schemas as S
from mrforge.config import load_config
from mrforge.datafiles import SubjectData, subject_data
from mrforge.engine import latest_pipeline_run
from mrforge.errors import StepError
from mrforge.fsl_env import find_fsl
from mrforge.functional import FunctionalOptions, Readiness, build_pipeline, check_ready
from mrforge.importing.bids_validate import find_validator
from mrforge.importing.classify import effective_all, load_rules, set_override
from mrforge.importing.manifest import list_manifests, load_manifest, save_manifest
from mrforge.importing.models import ImportManifest
from mrforge.importing.sourcedata import removal_plan
from mrforge.models import Job, JobStatus, Subject
from mrforge.operations import (
    cancel_operation,
    get_operation,
    list_operations,
    recover_stale_operations,
    start_operation,
)
from mrforge.overview import Overview, build_overview
from mrforge.pipeline import PipelineSpec, PipelineStep
from mrforge.provenance import read_provenance
from mrforge.runner.jobs import get_job, list_jobs, process_alive, recover_stale_jobs
from mrforge.viewerimages import find_images
from mrforge.workspace import Workspace, WorkspaceError

SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
HEARTBEAT_S = 5.0
SERVED_FOLDERS = ("rawbids", "derivatives", "reports")  # the viewer may read only these


def default_workspaces_root() -> Path:
    env = os.environ.get("MRFORGE_WORKSPACES")
    if env:
        return Path(env).expanduser()
    configured = load_config().get("workspaces_root")
    if isinstance(configured, str) and configured:
        return Path(configured).expanduser()
    return Path.home() / "Documents" / "mrforge-workspaces"


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    return slug or "workspace"


def _status_for(code: str) -> int:
    if code.startswith("UNKNOWN") or code in ("NO_IMPORT", "NOT_FOUND", "SOURCE_NOT_FOUND"):
        return 404
    if code in ("OPERATION_BUSY", "JOBS_RUNNING"):
        return 409
    return 400


def _error_body(err: StepError) -> S.ErrorBody:
    return S.ErrorBody(**err.to_dict())  # type: ignore[arg-type]


def _body(
    error: dict[str, Any] | None, fallback_code: str, message: str | None
) -> S.ErrorBody | None:
    if error:
        return S.ErrorBody(**error)
    if message:
        return S.ErrorBody(code=fallback_code or "ERROR", message=message)
    return None


def create_app(workspaces_root: Path | None = None) -> FastAPI:
    root = (workspaces_root or default_workspaces_root()).expanduser().resolve()
    app = FastAPI(title="MRForge API", version=__version__)
    opened: dict[str, Workspace] = {}

    # -- plumbing -----------------------------------------------------------------------------

    @app.exception_handler(StepError)
    async def step_error_handler(_: Request, err: StepError) -> JSONResponse:
        return JSONResponse(_error_body(err).model_dump(), status_code=_status_for(err.code))

    @app.exception_handler(WorkspaceError)
    async def workspace_error_handler(_: Request, err: WorkspaceError) -> JSONResponse:
        body = S.ErrorBody(
            code="WORKSPACE_ERROR",
            message=str(err),
            suggested_action="Pick another workspace or create a new one.",
        )
        return JSONResponse(body.model_dump(), status_code=400)

    def ws_of(ws_id: str) -> Workspace:
        if not SAFE_NAME.fullmatch(ws_id):
            raise StepError("UNKNOWN_WORKSPACE", "There is no such workspace.")
        folder = root / ws_id
        if not (folder / "workspace.json").is_file():
            raise StepError(
                "UNKNOWN_WORKSPACE",
                "There is no such workspace.",
                suggested_action="Go back to the workspace list and pick one.",
            )
        if ws_id not in opened:
            opened[ws_id] = Workspace.open(folder)
        return opened[ws_id]

    def refresh(ws: Workspace) -> None:
        """Mark work whose process vanished (killed, rebooted) as Interrupted."""
        recover_stale_jobs(ws)
        recover_stale_operations(ws)

    def import_summary(m: ImportManifest, ws: Workspace) -> S.ImportSummary:
        plan = effective_all(m, load_rules(ws)).values()
        return S.ImportSummary(
            id=m.id,
            kind=m.source.kind,
            source_name=m.source.name,
            subject=m.subject,
            session=m.session,
            n_series=len(m.series),
            to_import=sum(1 for c in plan if c.action == "import"),
            skipped=sum(1 for c in plan if c.action == "skip"),
            needs_input=sum(1 for c in plan if c.action == "ask"),
            organized=len(m.organized),
            dicom_removed=m.dicom_removed is not None,
            created=m.created,
            created_by=m.created_by,
        )

    def job_info(job: Job, subject: str | None) -> S.JobInfo:
        folder = (job.run_dir or "").rsplit("/", 1)[-1]
        run = folder.removeprefix(job.label or job.step_name).lstrip("_").replace("_", " ")
        return S.JobInfo(
            id=job.id,
            step=job.step_name,
            label=job.label or job.step_name,
            run=run,
            subject=subject,
            status=job.status,
            pipeline_run_id=job.pipeline_run_id,
            created=job.created,
            started=job.started,
            finished=job.finished,
            error=_body(job.error, job.error_code or "", job.error_message),
            started_by=job.started_by,
        )

    def all_jobs(ws: Workspace) -> list[S.JobInfo]:
        with ws.session() as s:
            labels = dict(s.execute(select(Subject.id, Subject.label)).tuples().all())
        return [job_info(j, labels.get(j.subject_id or -1)) for j in list_jobs(ws)]

    def op_info(op: Any) -> S.OperationInfo:
        return S.OperationInfo(
            id=op.id,
            kind=op.kind,
            title=op.title,
            status=op.status,
            created=op.created,
            started=op.started,
            finished=op.finished,
            result=op.result,
            error=_body(op.error, "", None),
            started_by=op.started_by,
        )

    # -- researcher profiles ------------------------------------------------------------------

    def current_researcher(request: Request) -> accounts.Researcher | None:
        """The researcher this request is for, from the profile the page picked (header
        ``X-MRForge-User``). This is the ONE place that decides who is acting: a login system
        would replace this function with a session check and nothing else would change."""
        raw = request.headers.get("x-mrforge-user", "")
        if not raw.isdigit():
            return None
        return accounts.get_researcher(int(raw))

    Researcher = Depends(current_researcher)

    @app.get("/api/researchers", response_model=list[S.ResearcherInfo])
    def list_researchers() -> list[S.ResearcherInfo]:
        return [
            S.ResearcherInfo(id=r.id, name=r.name, last_seen=r.last_seen)
            for r in accounts.list_researchers()
        ]

    @app.post("/api/researchers", response_model=S.ResearcherInfo)
    def create_researcher(req: S.ResearcherCreate) -> S.ResearcherInfo:
        r = accounts.create_researcher(req.name)
        return S.ResearcherInfo(id=r.id, name=r.name, last_seen=r.last_seen)

    @app.get("/api/me", response_model=S.ResearcherInfo | None)
    def me(researcher: accounts.Researcher | None = Researcher) -> S.ResearcherInfo | None:
        if researcher is None:
            return None
        accounts.touch(researcher.id)
        return S.ResearcherInfo(
            id=researcher.id, name=researcher.name, last_seen=researcher.last_seen
        )

    # -- health and workspaces ----------------------------------------------------------------

    @app.get("/api/health", response_model=S.Health)
    def health() -> S.Health:
        tools: dict[str, str | None] = {}
        try:
            tools["fsl"] = find_fsl().version
        except StepError:
            tools["fsl"] = None
        tools["dcm2niix"] = shutil.which("dcm2niix") and "installed"
        try:
            find_validator()
            tools["bids-validator"] = "installed"
        except StepError:
            tools["bids-validator"] = None
        return S.Health(version=__version__, workspaces_root=str(root), tools=tools)

    @app.get("/api/workspaces", response_model=list[S.WorkspaceInfo])
    def list_workspaces() -> list[S.WorkspaceInfo]:
        found: list[S.WorkspaceInfo] = []
        for meta in sorted(root.glob("*/workspace.json")) if root.is_dir() else []:
            try:
                data = json.loads(meta.read_text())
                ws = ws_of(meta.parent.name)
                with ws.session() as s:
                    n_subjects = len(list(s.scalars(select(Subject.id))))
                found.append(
                    S.WorkspaceInfo(
                        id=meta.parent.name,
                        name=data.get("name", meta.parent.name),
                        created=data.get("created"),
                        subjects=n_subjects,
                        imports=len(list_manifests(ws)),
                        created_by=ws.created_by,
                    )
                )
            except (OSError, ValueError, StepError, WorkspaceError):
                continue  # an unreadable folder is left out rather than breaking the list
        return found

    @app.post("/api/workspaces", response_model=S.WorkspaceInfo)
    def create_workspace(
        req: S.WorkspaceCreate, who: accounts.Researcher | None = Researcher
    ) -> S.WorkspaceInfo:
        root.mkdir(parents=True, exist_ok=True)
        slug = _slug(req.name)
        folder, n = root / slug, 2
        while folder.exists():
            folder, n = root / f"{slug}-{n}", n + 1
        ws = Workspace.create(folder, req.name.strip(), who.name if who else None)
        opened[folder.name] = ws
        return S.WorkspaceInfo(id=folder.name, name=ws.name, created_by=ws.created_by)

    @app.get("/api/workspaces/{ws_id}", response_model=S.WorkspaceInfo)
    def get_workspace(ws_id: str) -> S.WorkspaceInfo:
        ws = ws_of(ws_id)
        with ws.session() as s:
            n_subjects = len(list(s.scalars(select(Subject.id))))
        return S.WorkspaceInfo(
            id=ws_id,
            name=ws.name,
            subjects=n_subjects,
            imports=len(list_manifests(ws)),
            created_by=ws.created_by,
        )

    @app.get("/api/workspaces/{ws_id}/subjects/{label}/data", response_model=SubjectData)
    def subject_files(ws_id: str, label: str) -> SubjectData:
        """The raw images of a subject, for the Data page."""
        ws = ws_of(ws_id)
        if not SAFE_NAME.fullmatch(label):
            raise StepError("UNKNOWN_SUBJECT", "There is no such subject.")
        return subject_data(ws, label)

    @app.get("/api/workspaces/{ws_id}/overview", response_model=Overview)
    def overview(ws_id: str) -> Overview:
        """Where every subject stands, for the dashboard."""
        ws = ws_of(ws_id)
        refresh(ws)
        return build_overview(ws)

    @app.get("/api/workspaces/{ws_id}/subjects", response_model=list[S.SubjectInfo])
    def list_subjects(ws_id: str) -> list[S.SubjectInfo]:
        from mrforge.models import File

        ws = ws_of(ws_id)
        out: list[S.SubjectInfo] = []
        with ws.session() as s:
            for sub in s.scalars(select(Subject).order_by(Subject.label)):
                files = list(s.scalars(select(File).where(File.subject_id == sub.id)))
                anat = ws.derivatives_dir / sub.label
                out.append(
                    S.SubjectInfo(
                        label=sub.label,
                        files=[
                            S.SubjectFile(relpath=f.relpath, kind=f.kind)
                            for f in sorted(files, key=lambda f: f.relpath)
                            if f.relpath.endswith(".nii.gz") and f.relpath.startswith("rawbids/")
                        ],
                        has_anat_result=any(anat.glob("**/anat/*_desc-brain_T1w.nii.gz")),
                    )
                )
        return out

    # -- importing ----------------------------------------------------------------------------

    @app.get("/api/workspaces/{ws_id}/imports", response_model=list[S.ImportSummary])
    def list_imports(ws_id: str) -> list[S.ImportSummary]:
        ws = ws_of(ws_id)
        return [import_summary(m, ws) for m in list_manifests(ws)]

    def import_detail(ws: Workspace, m: ImportManifest) -> S.ImportDetail:
        rules = load_rules(ws)
        plan = effective_all(m, rules)
        rows: list[S.SeriesRow] = []
        for s in m.series:
            c = plan[s.uid]
            conv = m.conversions.get(s.uid)
            override = m.overrides.get(s.uid)
            rows.append(
                S.SeriesRow(
                    number=s.number,
                    uid=s.uid,
                    label=s.label,
                    description=s.description,
                    matrix=s.matrix,
                    volumes=s.volumes,
                    n_files=s.n_files,
                    repetition_time_s=s.repetition_time_s,
                    echo_time_s=s.echo_time_s,
                    kind=c.kind,
                    action=c.action,
                    confidence=c.confidence,
                    datatype=c.datatype,
                    suffix=c.suffix,
                    entities=c.entities,
                    needs=c.needs,
                    reasons=c.reasons,
                    decided_by=c.source,
                    fieldmap=override.fieldmap if override else None,
                    converted=conv.status if conv else None,
                    organized=s.uid in m.organized,
                    warnings=s.warnings,
                )
            )
        kinds = [
            S.ImportKind(kind=k, datatype=r.datatype, needs=list(r.needs))
            for k, r in sorted(rules.import_kinds().items())
        ]
        return S.ImportDetail(
            **import_summary(m, ws).model_dump(),
            series=rows,
            kinds=kinds,
            warnings=m.warnings,
        )

    @app.get("/api/workspaces/{ws_id}/imports/{import_id}", response_model=S.ImportDetail)
    def get_import(ws_id: str, import_id: str) -> S.ImportDetail:
        ws = ws_of(ws_id)
        return import_detail(ws, load_manifest(ws, import_id))

    @app.patch(
        "/api/workspaces/{ws_id}/imports/{import_id}/series/{number}",
        response_model=S.ImportDetail,
    )
    def decide_series(
        ws_id: str, import_id: str, number: int, decision: S.SeriesDecision
    ) -> S.ImportDetail:
        ws = ws_of(ws_id)
        m = load_manifest(ws, import_id)
        labels = {k: v for k, v in (("task", decision.task), ("acq", decision.acq)) if v}
        set_override(
            m, load_rules(ws), number, decision.kind, decision.skip, labels, decision.fieldmap
        )
        save_manifest(ws, m)
        return import_detail(ws, m)

    @app.post("/api/workspaces/{ws_id}/imports/scan", response_model=S.OperationStarted)
    def scan(
        ws_id: str, req: S.ScanRequest, who: accounts.Researcher | None = Researcher
    ) -> S.OperationStarted:
        ws = ws_of(ws_id)
        source = _inside_home(req.source)
        if not source.exists():
            raise StepError(
                "SOURCE_NOT_FOUND",
                "That folder or file could not be found.",
                suggested_action="Pick the folder or ZIP again.",
            )
        op = start_operation(
            ws,
            "scan",
            f"Reading scanner files from {source.name}",
            {"source": str(source), "subject": req.subject, "session": req.session},
            started_by=who.name if who else None,
        )
        return S.OperationStarted(operation_id=op)

    @app.post("/api/workspaces/{ws_id}/imports/{import_id}/run", response_model=S.OperationStarted)
    def run_import(
        ws_id: str,
        import_id: str,
        req: S.ImportRunRequest,
        who: accounts.Researcher | None = Researcher,
    ) -> S.OperationStarted:
        ws = ws_of(ws_id)
        m = load_manifest(ws, import_id)
        op = start_operation(
            ws,
            "import_run",
            f"Importing {m.id} into {m.subject}",
            {"import_id": m.id, "remove_dicom": req.remove_dicom},
            started_by=who.name if who else None,
        )
        return S.OperationStarted(operation_id=op)

    @app.get(
        "/api/workspaces/{ws_id}/imports/{import_id}/removal-plan",
        response_model=S.RemovalPlanInfo,
    )
    def get_removal_plan(ws_id: str, import_id: str) -> S.RemovalPlanInfo:
        ws = ws_of(ws_id)
        plan = removal_plan(ws, load_manifest(ws, import_id), load_rules(ws))
        return S.RemovalPlanInfo(
            path=plan.path,
            size_bytes=plan.size_bytes,
            not_safe=plan.not_safe,
            only_in_dicom=plan.only_in_dicom,
        )

    @app.post(
        "/api/workspaces/{ws_id}/imports/{import_id}/remove-dicom",
        response_model=S.OperationStarted,
    )
    def remove_dicom_copy(
        ws_id: str, import_id: str, who: accounts.Researcher | None = Researcher
    ) -> S.OperationStarted:
        ws = ws_of(ws_id)
        m = load_manifest(ws, import_id)
        op = start_operation(
            ws,
            "remove_dicom",
            f"Removing the DICOM copy of {m.id}",
            {"import_id": m.id},
            started_by=who.name if who else None,
        )
        return S.OperationStarted(operation_id=op)

    # -- file browser (the computer running MRForge, home folder only) ------------------------

    def _inside_home(path: str) -> Path:
        home = Path.home().resolve()
        resolved = Path(path).expanduser().resolve()
        if resolved != home and home not in resolved.parents:
            raise StepError(
                "OUTSIDE_HOME",
                "MRForge can only open files inside your home folder.",
                probable_cause="The chosen location is outside it.",
                suggested_action="Copy the scanner files into your home folder, then pick them.",
            )
        return resolved

    @app.get("/api/fs", response_model=S.FsListing)
    def browse(path: str | None = None) -> S.FsListing:
        home = Path.home().resolve()
        here = _inside_home(path or str(home))
        if not here.is_dir():
            raise StepError("NOT_FOUND", "That folder does not exist.")
        entries: list[S.FsEntry] = []
        try:
            children = sorted(here.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError as err:
            raise StepError(
                "NOT_ALLOWED", "MRForge may not open that folder.", suggested_action="Pick another."
            ) from err
        for child in children:
            if child.name.startswith("."):
                continue
            if child.is_dir():
                entries.append(S.FsEntry(name=child.name, path=str(child), kind="dir"))
            elif child.suffix.lower() == ".zip":
                entries.append(S.FsEntry(name=child.name, path=str(child), kind="zip"))
        parent = str(here.parent) if here != home else None
        return S.FsListing(path=str(here), parent=parent, home=str(home), entries=entries)

    # -- operations ---------------------------------------------------------------------------

    @app.get("/api/workspaces/{ws_id}/operations", response_model=list[S.OperationInfo])
    def operations(ws_id: str) -> list[S.OperationInfo]:
        ws = ws_of(ws_id)
        refresh(ws)
        return [op_info(o) for o in list_operations(ws)]

    @app.get("/api/workspaces/{ws_id}/operations/{op_id}", response_model=S.OperationInfo)
    def operation(ws_id: str, op_id: int) -> S.OperationInfo:
        ws = ws_of(ws_id)
        refresh(ws)
        return op_info(get_operation(ws, op_id))

    @app.get("/api/workspaces/{ws_id}/operations/{op_id}/log", response_model=S.LogText)
    def operation_log(ws_id: str, op_id: int) -> S.LogText:
        ws = ws_of(ws_id)
        op = get_operation(ws, op_id)
        return S.LogText(name=op.log or "", text=_read_text(ws.abspath(op.log)) if op.log else "")

    @app.post("/api/workspaces/{ws_id}/operations/{op_id}/cancel", status_code=204)
    def cancel(ws_id: str, op_id: int) -> None:
        cancel_operation(ws_of(ws_id), op_id)

    # -- jobs ---------------------------------------------------------------------------------

    @app.get("/api/workspaces/{ws_id}/jobs", response_model=list[S.JobInfo])
    def jobs(ws_id: str) -> list[S.JobInfo]:
        ws = ws_of(ws_id)
        refresh(ws)
        return all_jobs(ws)

    @app.get("/api/workspaces/{ws_id}/jobs/{job_id}/log", response_model=list[S.LogText])
    def job_log(ws_id: str, job_id: int) -> list[S.LogText]:
        ws = ws_of(ws_id)
        job = get_job(ws, job_id)
        log_dir = ws.abspath(job.run_dir or "") / "logs"
        return [
            S.LogText(name=name, text=_read_text(log_dir / name))
            for name in ("stdout.log", "stderr.log", "worker.log")
        ]

    @app.post("/api/workspaces/{ws_id}/jobs/{job_id}/cancel", status_code=204)
    def cancel_job(ws_id: str, job_id: int) -> None:
        ws = ws_of(ws_id)
        job = get_job(ws, job_id)
        if job.status == JobStatus.RUNNING.value and process_alive(job.pid, job.pid_start_time):
            assert job.pid is not None
            os.kill(job.pid, signal.SIGTERM)

    # -- anatomical preprocessing -------------------------------------------------------------

    def _start_pipeline(
        ws: Workspace,
        spec: PipelineSpec,
        title: str,
        who: accounts.Researcher | None = None,
    ) -> S.OperationStarted:
        refresh(ws)
        if any(j.status == JobStatus.RUNNING.value for j in list_jobs(ws)):
            raise StepError(
                "JOBS_RUNNING",
                "A processing step is still running in this workspace.",
                probable_cause="It was started earlier and has not finished yet.",
                suggested_action="Wait for it to finish, or cancel it, then try again.",
            )
        op = start_operation(
            ws,
            "pipeline",
            title,
            {"spec": spec.model_dump(mode="json")},
            started_by=who.name if who else None,
        )
        return S.OperationStarted(operation_id=op)

    @app.post("/api/workspaces/{ws_id}/anat", response_model=S.OperationStarted)
    def run_anat(
        ws_id: str, req: S.AnatRequest, who: accounts.Researcher | None = Researcher
    ) -> S.OperationStarted:
        ws = ws_of(ws_id)
        if not (ws.abspath(req.t1)).is_file() or not req.t1.startswith("rawbids/"):
            raise StepError(
                "UNKNOWN_FILE",
                "That T1 image was not found in the workspace.",
                suggested_action="Import the scan first, then choose the T1 again.",
            )
        steps: list[PipelineStep] = []
        if req.bet:
            steps.append(PipelineStep(id="bet", step="bet", inputs={"t1": req.t1}))
        steps.append(
            PipelineStep(
                id="fsl_anat",
                step="fsl_anat",
                inputs={"t1": req.t1},
                params={
                    "strong_bias": req.strong_bias,
                    "subcortical_segmentation": req.subcortical_segmentation,
                },
            )
        )
        for st in steps:
            st.session = req.session
        spec = PipelineSpec(name=f"anatomical-{req.subject}", subject=req.subject, steps=steps)
        return _start_pipeline(ws, spec, f"Anatomical preprocessing of {req.subject}", who)

    @app.post("/api/workspaces/{ws_id}/resume", response_model=S.OperationStarted)
    def resume(ws_id: str, who: accounts.Researcher | None = Researcher) -> S.OperationStarted:
        """Continue the latest pipeline where it stopped; finished steps are not repeated."""
        from mrforge.pipeline import parse_pipeline

        ws = ws_of(ws_id)
        last = latest_pipeline_run(ws)
        if last is None:
            raise StepError(
                "NOTHING_TO_RESUME",
                "There is nothing to resume yet.",
                suggested_action="Start the processing first.",
            )
        return _start_pipeline(ws, parse_pipeline(last.spec), f"Resuming {last.name}", who)

    # -- functional preprocessing -------------------------------------------------------------

    @app.get("/api/workspaces/{ws_id}/subjects/{label}/functional", response_model=Readiness)
    def functional_readiness(ws_id: str, label: str, session: str | None = None) -> Readiness:
        """What can be run for this subject, and why something is not possible."""
        ws = ws_of(ws_id)
        if not SAFE_NAME.fullmatch(label):
            raise StepError("UNKNOWN_SUBJECT", "There is no such subject.")
        return check_ready(ws, label, session)

    @app.post("/api/workspaces/{ws_id}/functional", response_model=S.OperationStarted)
    def run_functional(
        ws_id: str, req: FunctionalOptions, who: accounts.Researcher | None = Researcher
    ) -> S.OperationStarted:
        ws = ws_of(ws_id)
        spec = build_pipeline(ws, req)
        run = Path(req.bold).name.removesuffix("_bold.nii.gz").split("_", 1)[-1]
        return _start_pipeline(ws, spec, f"Functional preprocessing of {req.subject} ({run})", who)

    @app.get("/api/workspaces/{ws_id}/subjects/{label}/qc", response_model=list[S.QcGroup])
    def subject_qc(ws_id: str, label: str) -> list[S.QcGroup]:
        """QC results recorded by the latest completed functional QC steps of a subject."""
        ws = ws_of(ws_id)
        if not SAFE_NAME.fullmatch(label):
            raise StepError("UNKNOWN_SUBJECT", "There is no such subject.")
        titles = {
            "func_qc": "Head motion and registration",
            "func_to_mni": "Alignment to standard space",
        }
        latest: dict[str, Job] = {}
        with ws.session() as s:
            subject_id = s.scalar(select(Subject.id).where(Subject.label == label))
            jobs = list(
                s.scalars(
                    select(Job)
                    .where(Job.subject_id == subject_id)
                    .where(Job.step_name.in_(list(titles)))
                    .where(Job.status == JobStatus.COMPLETED.value)
                    .order_by(Job.id)
                )
            )
        for job in jobs:
            latest[job.run_dir or ""] = job
        groups: list[S.QcGroup] = []
        for job in latest.values():
            prov = read_provenance(ws.abspath(job.run_dir or ""))
            if prov is None or not prov.qc:
                continue
            entries: list[S.QcEntry] = []
            for item in prov.qc:
                url = None
                if item.path:
                    rel = ws.relpath(ws.abspath(job.output_dir or "") / item.path)
                    url = f"/api/workspaces/{ws_id}/file/{rel}"
                entries.append(
                    S.QcEntry(
                        name=item.name,
                        kind=item.kind,
                        value=None if item.value is None else str(item.value),
                        image_url=url,
                        warning=item.warning,
                    )
                )
            folder = (job.run_dir or "").rsplit("/", 1)[-1]
            run = folder.removeprefix(job.label or job.step_name).lstrip("_").replace("_", " ")
            groups.append(
                S.QcGroup(run=run, step=job.step_name, title=titles[job.step_name], items=entries)
            )
        return groups

    # -- viewer -------------------------------------------------------------------------------

    @app.get("/api/workspaces/{ws_id}/subjects/{label}/images", response_model=list[S.ViewerImage])
    def viewer_images(ws_id: str, label: str) -> list[S.ViewerImage]:
        """Every raw image and result of a subject that the viewer can show."""
        ws = ws_of(ws_id)
        if not SAFE_NAME.fullmatch(label):
            raise StepError("UNKNOWN_SUBJECT", "There is no such subject.")
        out: list[S.ViewerImage] = []
        for f in find_images(ws, label):
            rel = ws.relpath(f.path)
            out.append(
                S.ViewerImage(
                    name=f.described.name,
                    group=f.described.group,
                    role=f.described.role,  # type: ignore[arg-type]
                    relpath=rel,
                    url=f"/api/workspaces/{ws_id}/file/{rel}",
                    colormap=f.described.colormap,
                    volumes=f.volumes,
                    size_bytes=f.size_bytes,
                )
            )
        return out

    @app.get("/api/workspaces/{ws_id}/file/{relpath:path}")
    def serve_file(ws_id: str, relpath: str) -> FileResponse:
        """Image files for the viewer. Supports byte ranges; only data folders are served."""
        ws = ws_of(ws_id)
        target = (ws.root / relpath).resolve()
        top = target.relative_to(ws.root).parts[:1] if ws.root in target.parents else ()
        if not top or top[0] not in SERVED_FOLDERS or not target.is_file():
            raise StepError(
                "NOT_FOUND", "That file is not available.", suggested_action="Reload the page."
            )
        return FileResponse(target)

    # -- live updates -------------------------------------------------------------------------

    def snapshot(ws: Workspace) -> S.WorkspaceState:
        refresh(ws)
        with ws.session() as s:
            subjects = [r for r in s.scalars(select(Subject.label).order_by(Subject.label))]
        return S.WorkspaceState(
            jobs=all_jobs(ws),
            operations=[op_info(o) for o in list_operations(ws)],
            imports=[import_summary(m, ws) for m in list_manifests(ws)],
            subjects=subjects,
        )

    @app.get("/api/workspaces/{ws_id}/state", response_model=S.WorkspaceState)
    def state(ws_id: str) -> S.WorkspaceState:
        return snapshot(ws_of(ws_id))

    @app.get("/api/workspaces/{ws_id}/events")
    async def events(ws_id: str, request: Request) -> EventSourceResponse:
        """Server-sent events: the full state whenever something changes. A page that opens
        mid-job gets the current state immediately, so refreshing never shows stale status."""
        ws = ws_of(ws_id)

        async def stream() -> AsyncIterator[dict[str, str]]:
            last, last_sent = "", 0.0
            while not await request.is_disconnected():
                current = await asyncio.to_thread(lambda: snapshot(ws).model_dump_json())
                # Also resend an unchanged state every few seconds: it is the heartbeat that
                # lets the page notice a dead connection (proxies can hide a closed one).
                if current != last or time.monotonic() - last_sent > HEARTBEAT_S:
                    last, last_sent = current, time.monotonic()
                    yield {"event": "state", "data": current}
                await asyncio.sleep(1.0)

        return EventSourceResponse(stream(), ping=15)

    _mount_frontend(app)
    return app


def frontend_dist() -> Path | None:
    """The built frontend (``npm run build`` in frontend/), if present."""
    env = os.environ.get("MRFORGE_FRONTEND")
    dist = Path(env) if env else Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return dist if (dist / "index.html").is_file() else None


def _mount_frontend(app: FastAPI) -> None:
    """Serve the web interface from the same address as the API, after all API routes."""
    dist = frontend_dist()
    if dist is not None:
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    text = data[-limit:].decode("utf-8", errors="replace")
    return ("(earlier output left out)\n" + text) if len(data) > limit else text
