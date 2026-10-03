"""Create and open workspaces (folder layout from docs/architecture.md section 2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from mrforge.models import Base, Subject
from mrforge.models import Workspace as WorkspaceRow

SCHEMA_VERSION = 1
APP_DIRNAME = "mrforge"  # derivatives/<appname>/

SUBDIRS = ("sourcedata/dicom", "rawbids", f"derivatives/{APP_DIRNAME}", "reports")


class WorkspaceError(Exception):
    """A workspace could not be created or opened (message is plain language)."""


class Workspace:
    def __init__(self, root: Path, engine: Engine, name: str) -> None:
        self.root = root
        self.engine = engine
        self.name = name

    # -- creation / opening -------------------------------------------------

    @classmethod
    def create(cls, root: Path, name: str | None = None) -> Workspace:
        root = root.resolve()
        if (root / "workspace.json").exists():
            raise WorkspaceError(f"A workspace already exists in {root}. Open it instead.")
        if root.exists() and any(root.iterdir()):
            raise WorkspaceError(
                f"{root} is not empty. Choose a new or empty folder for the workspace."
            )
        name = name or root.name
        for sub in SUBDIRS:
            (root / sub).mkdir(parents=True, exist_ok=True)
        created = datetime.now(UTC)
        (root / "workspace.json").write_text(
            json.dumps(
                {"name": name, "created": created.isoformat(), "schema_version": SCHEMA_VERSION},
                indent=2,
            )
            + "\n"
        )
        ws = cls(root, _engine(root), name)
        Base.metadata.create_all(ws.engine)
        with ws.session() as s:
            s.add(WorkspaceRow(name=name, schema_version=SCHEMA_VERSION, created=created))
        return ws

    @classmethod
    def open(cls, root: Path) -> Workspace:
        root = root.resolve()
        meta_path = root / "workspace.json"
        if not meta_path.is_file():
            raise WorkspaceError(
                f"No workspace found in {root}. Create one with 'mrforge workspace create'."
            )
        meta = json.loads(meta_path.read_text())
        if meta.get("schema_version") != SCHEMA_VERSION:
            raise WorkspaceError(
                f"This workspace uses schema version {meta.get('schema_version')}, "
                f"but this MRForge expects {SCHEMA_VERSION}."
            )
        engine = _engine(root)
        Base.metadata.create_all(engine)  # adds tables introduced later; never drops
        return cls(root, engine, meta["name"])

    # -- helpers ------------------------------------------------------------

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A transaction: commits on success, rolls back on error."""
        with Session(self.engine) as s, s.begin():
            yield s

    @property
    def derivatives_dir(self) -> Path:
        return self.root / "derivatives" / APP_DIRNAME

    def relpath(self, path: Path) -> str:
        """Path relative to the workspace root (what is stored in the database/provenance)."""
        return path.resolve().relative_to(self.root).as_posix()

    def abspath(self, relpath: str) -> Path:
        return self.root / relpath

    def get_or_create_subject(self, label: str) -> int:
        with self.session() as s:
            subject = s.scalar(select(Subject).where(Subject.label == label))
            if subject is None:
                subject = Subject(label=label)
                s.add(subject)
                s.flush()
            return subject.id


def _engine(root: Path) -> Engine:
    return create_engine(f"sqlite:///{root / 'db.sqlite'}")
