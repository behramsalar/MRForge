"""Request and response models. The OpenAPI schema made from these generates the typed
TypeScript client, so every field the UI can see is declared here."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """A plain-language error: what happened, why, and what to do next."""

    code: str
    message: str
    probable_cause: str = ""
    suggested_action: str = ""
    log_path: str | None = None


class Health(BaseModel):
    version: str
    workspaces_root: str
    tools: dict[str, str | None]  # tool name -> version, or None when not found


# -- workspaces -------------------------------------------------------------------------------


class WorkspaceInfo(BaseModel):
    id: str  # folder name under the workspaces folder
    name: str
    created: datetime | None = None
    subjects: int = 0
    imports: int = 0
    created_by: str | None = None  # researcher profile that created it


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class SubjectFile(BaseModel):
    relpath: str
    kind: str | None = None


class SubjectInfo(BaseModel):
    label: str
    files: list[SubjectFile]
    has_anat_result: bool = False


# -- importing ----------------------------------------------------------------------------------


class SeriesRow(BaseModel):
    number: int | None
    uid: str
    label: str
    description: str
    matrix: str
    volumes: int | None
    n_files: int
    repetition_time_s: float | None
    echo_time_s: float | None
    kind: str
    action: Literal["import", "skip", "ask"]
    confidence: Literal["High", "Medium", "Low"]
    datatype: str | None
    suffix: str | None
    entities: dict[str, str]
    needs: list[str]
    reasons: list[str]
    decided_by: Literal["rules", "user"]
    fieldmap: str | None = None
    converted: Literal["ok", "failed"] | None = None
    organized: bool = False
    warnings: list[str] = []


class ImportSummary(BaseModel):
    id: str
    kind: Literal["folder", "zip", "nifti", "bids"]
    source_name: str
    subject: str
    session: str | None
    n_series: int
    to_import: int
    skipped: int
    needs_input: int
    organized: int
    dicom_removed: bool
    created: datetime
    created_by: str | None = None


class ImportKind(BaseModel):
    kind: str
    datatype: str | None
    needs: list[str]


class ImportDetail(ImportSummary):
    series: list[SeriesRow]
    kinds: list[ImportKind]  # what a series may be set to
    warnings: list[str]


class SeriesDecision(BaseModel):
    """The user's decision for one series. Send only what changes."""

    kind: str | None = None
    skip: bool = False
    task: str | None = None
    acq: str | None = None
    fieldmap: str | None = None


class ScanRequest(BaseModel):
    source: str  # folder or .zip on the computer running MRForge
    subject: str | None = None
    session: str | None = None


class ImportRunRequest(BaseModel):
    remove_dicom: bool = False


class RemovalPlanInfo(BaseModel):
    path: str
    size_bytes: int
    not_safe: list[str]
    only_in_dicom: list[str]


# -- file browser -------------------------------------------------------------------------------


class FsEntry(BaseModel):
    name: str
    path: str
    kind: Literal["dir", "zip"]


class FsListing(BaseModel):
    path: str
    parent: str | None
    home: str
    entries: list[FsEntry]


# -- operations and jobs ----------------------------------------------------------------------


class OperationInfo(BaseModel):
    id: int
    kind: str
    title: str
    status: str
    created: datetime
    started: datetime | None
    finished: datetime | None
    result: dict[str, Any] | None
    error: ErrorBody | None
    started_by: str | None = None


class OperationStarted(BaseModel):
    operation_id: int


class JobInfo(BaseModel):
    id: int
    step: str
    label: str
    run: str = ""  # which recording, e.g. "task-rest run-1" (empty for anatomical steps)
    subject: str | None
    status: str
    pipeline_run_id: int | None
    created: datetime
    started: datetime | None
    finished: datetime | None
    error: ErrorBody | None
    started_by: str | None = None


class LogText(BaseModel):
    name: str
    text: str


class AnatRequest(BaseModel):
    subject: str
    t1: str  # workspace-relative path of the T1 image in rawbids/
    session: str | None = None
    bet: bool = False  # also run FSL bet (optional, independent of fsl_anat)
    strong_bias: bool = False
    subcortical_segmentation: bool = False


class ViewerImage(BaseModel):
    name: str  # plain-language name
    group: str  # "Raw data", "Anatomical results", "Functional results", "Fieldmap results"
    role: Literal["underlay", "overlay"]  # what it is usually shown as
    relpath: str
    url: str
    colormap: str | None = None
    volumes: int | None = None  # for time series
    size_bytes: int = 0


class WorkspaceState(BaseModel):
    """Everything the live view shows; sent again whenever any part changes."""

    jobs: list[JobInfo]
    operations: list[OperationInfo]
    imports: list[ImportSummary]
    subjects: list[str]


class QcEntry(BaseModel):
    name: str  # plain-language title, e.g. "Mean framewise displacement (mm)"
    kind: Literal["image", "plot", "metric"]
    value: str | None = None  # for metrics
    image_url: str | None = None  # for pictures and plots
    warning: str | None = None


class QcGroup(BaseModel):
    """The QC results of one step on one recording (for example the motion and registration
    results of the 'task-rest' run)."""

    run: str
    step: str
    title: str
    items: list[QcEntry]


class ResearcherInfo(BaseModel):
    id: int
    name: str
    last_seen: datetime | None = None


class ResearcherCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
