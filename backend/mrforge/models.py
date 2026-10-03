"""SQLAlchemy models: the state index of a workspace.

The durable record of what ran is provenance.json next to each step's outputs; this
database is a rebuildable index (see docs/DECISIONS.md). All stored paths are
relative to the workspace root.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class JobStatus(enum.StrEnum):
    QUEUED = "Queued"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    INTERRUPTED = "Interrupted"


class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    schema_version: Mapped[int] = mapped_column(Integer)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Subject(Base):
    __tablename__ = "subject"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. "sub-001"
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    files: Mapped[list[File]] = relationship(back_populates="subject")


class File(Base):
    __tablename__ = "file"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subject.id"), nullable=True)
    relpath: Mapped[str] = mapped_column(String(1000), unique=True)
    kind: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. "T1w", "bold"
    # Hash cache, valid only while size and mtime_ns are unchanged (see DECISIONS.md).
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size: Mapped[int | None] = mapped_column(nullable=True)
    mtime_ns: Mapped[int | None] = mapped_column(nullable=True)

    subject: Mapped[Subject | None] = relationship(back_populates="files")


class Job(Base):
    """One execution of one step for one subject (a "step run")."""

    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    step_name: Mapped[str] = mapped_column(String(100))
    step_version: Mapped[str] = mapped_column(String(50))
    # Name of the output folder; defaults to the step name. Pipelines use the step id so the
    # same step can appear twice for one subject.
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subject.id"), nullable=True)
    session: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inputs: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    params: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    param_hash: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED.value)
    pipeline_run_id: Mapped[int | None] = mapped_column(nullable=True)

    # Liveness: PID plus process start time, so a reused PID is not mistaken for our worker.
    pid: Mapped[int | None] = mapped_column(nullable=True)
    pid_start_time: Mapped[float | None] = mapped_column(nullable=True)

    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    return_code: Mapped[int | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # relative


class PipelineRun(Base):
    """One execution of a pipeline spec. ``resume`` creates a new run from the same spec."""

    __tablename__ = "pipeline_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    spec: Mapped[dict[str, object]] = mapped_column(JSON)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
