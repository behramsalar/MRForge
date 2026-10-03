"""provenance.json: the durable record of one step run (docs/architecture.md section 6).

It is written next to the step's outputs so it travels with them. Paths are relative to
the workspace root.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from mrforge.steps.base import CommandRecord

PROVENANCE_FILENAME = "provenance.json"
SCHEMA_VERSION = 1


class StepRef(BaseModel):
    name: str
    version: str


class FileRecord(BaseModel):
    path: str
    sha256: str


class Provenance(BaseModel):
    schema_version: int = SCHEMA_VERSION
    step: StepRef
    job_id: int
    subject: str
    session: str | None = None
    parameters: dict[str, object]
    parameter_hash: str
    inputs: list[FileRecord]
    outputs: list[FileRecord]
    commands: list[CommandRecord]
    tool_versions: dict[str, str]
    started: datetime | None
    finished: datetime | None
    status: str
    return_code: int | None = None
    error_code: str | None = None
    error_message: str | None = None


def write_provenance(output_dir: Path, prov: Provenance) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / PROVENANCE_FILENAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(prov.model_dump_json(indent=2) + "\n")
    tmp.replace(path)  # atomic: never leaves a half-written record
    return path


def read_provenance(output_dir: Path) -> Provenance | None:
    path = output_dir / PROVENANCE_FILENAME
    if not path.is_file():
        return None
    try:
        return Provenance.model_validate_json(path.read_text())
    except ValueError:
        return None  # unreadable record: treated as "never ran", so the step reruns


def remove_provenance(output_dir: Path) -> None:
    (output_dir / PROVENANCE_FILENAME).unlink(missing_ok=True)
