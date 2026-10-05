"""The Step contract (docs/architecture.md section 4).

Only Step subclasses know command lines. A step declares typed inputs, parameters and
outputs (pydantic models); paths in specs are relative (inputs: to the workspace root,
outputs: to the step's output directory, a BIDS datatype folder such as
``derivatives/mrforge/sub-001/anat/``). Provenance and logs of a run live in ``run_dir``
(``<output_dir>/_runs/<label>/``).
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Generic, Literal, TypeVar

from pydantic import BaseModel
from sqlalchemy import select

from mrforge.bids import bids_name, inherited_entities
from mrforge.errors import StepError
from mrforge.models import File
from mrforge.workspace import Workspace


class Problem(BaseModel):
    """Something wrong (error) or worth knowing (warning) found while validating."""

    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    probable_cause: str = ""
    suggested_action: str = ""


class QCItem(BaseModel):
    """A QC artifact for human review. QC flags; it never decides (CLAUDE.md principle 6)."""

    name: str
    kind: Literal["image", "plot", "metric"]
    path: str | None = None  # relative to the step output directory
    value: float | str | None = None
    warning: str | None = None


class CommandRecord(BaseModel):
    argv: list[str]
    return_code: int
    stdout_log: str  # relative to the workspace
    stderr_log: str


class StepResult(BaseModel):
    commands: list[CommandRecord] = []
    warnings: list[Problem] = []
    qc: list[QCItem] = []


I = TypeVar("I", bound=BaseModel)  # noqa: E741  (input spec)
P = TypeVar("P", bound=BaseModel)  # parameter spec
O = TypeVar("O", bound=BaseModel)  # noqa: E741  (output spec)


@dataclass
class StepContext(Generic[I, P]):
    workspace: Workspace
    subject: str  # e.g. "sub-001"
    inputs: I
    params: P
    output_dir: Path  # absolute; derivatives/<app>/<sub>/[<ses>/]<datatype>/ (BIDS-named results)
    run_dir: Path  # absolute; <output_dir>/_runs/<label>/ (provenance.json and logs/)
    label: str  # names this run; the step name unless a pipeline gives the step an id
    session: str | None = None
    env: dict[str, str] | None = None  # subprocess environment (FSL etc.); None = inherit
    commands: list[CommandRecord] = field(default_factory=list)

    @property
    def log_dir(self) -> Path:
        return self.run_dir / "logs"

    def bids_name(self, suffix: str, ext: str = ".nii.gz", **entities: str) -> str:
        """A BIDS file name for a result of this run, e.g. ``sub-001_desc-brain_mask.nii.gz``.
        sub/ses come from the workspace; acq/run/... are carried over from the first input."""
        paths = input_relpaths(self.inputs)
        base = inherited_entities(self.subject, self.session, paths[0] if paths else None)
        return bids_name({**base, **entities}, suffix, ext)

    def input_path(self, relpath: str) -> Path:
        return self.workspace.abspath(relpath)

    def run_command(self, argv: list[str], *, check: bool = True) -> CommandRecord:
        """Run a command, append its output to logs/stdout.log and logs/stderr.log, record it."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.log_dir / "stdout.log"
        err_path = self.log_dir / "stderr.log"
        header = "$ " + " ".join(argv) + "\n"
        with out_path.open("a") as out, err_path.open("a") as err:
            out.write(header)
            err.write(header)
            out.flush()
            err.flush()
            try:
                proc = subprocess.run(
                    argv, stdout=out, stderr=err, env=self.env or os.environ.copy(), check=False
                )
            except FileNotFoundError as exc:
                raise StepError(
                    code="TOOL_NOT_FOUND",
                    message=f"The program '{argv[0]}' could not be found.",
                    probable_cause="The required software is not installed or not on the path.",
                    suggested_action="Run 'python scripts/check_env.py' to see what is missing.",
                    log_path=err_path,
                ) from exc
        record = CommandRecord(
            argv=argv,
            return_code=proc.returncode,
            stdout_log=self.workspace.relpath(out_path),
            stderr_log=self.workspace.relpath(err_path),
        )
        self.commands.append(record)
        if check and proc.returncode < 0:
            raise StepError(
                code="COMMAND_KILLED",
                message=f"'{argv[0]}' was stopped before it finished (signal {-proc.returncode}).",
                probable_cause="The process was killed, for example by a user or the system.",
                suggested_action="Resume the pipeline to run this step again.",
                log_path=err_path,
            )
        if check and proc.returncode != 0:
            raise StepError(
                code="COMMAND_FAILED",
                message=f"'{argv[0]}' stopped with an error (exit code {proc.returncode}).",
                probable_cause="The input data may be unsuitable, or the tool hit a problem.",
                suggested_action="Open the raw log for details, then fix the input and retry.",
                log_path=err_path,
            )
        return record


class Step(ABC, Generic[I, P, O]):
    """One operation with declared inputs, parameters, outputs, validation and QC."""

    name: ClassVar[str]
    version: ClassVar[str]  # bump when behavior changes; part of the resume hash
    InputSpec: ClassVar[type[BaseModel]]
    ParamSpec: ClassVar[type[BaseModel]]
    OutputSpec: ClassVar[type[BaseModel]]
    depends_on: ClassVar[tuple[str, ...]] = ()  # names of upstream steps
    requires_fsl: ClassVar[bool] = False  # runner supplies the FSL environment when True
    datatype: ClassVar[str] = "anat"  # BIDS datatype folder the results go in (anat, func, ...)

    # -- the contract -------------------------------------------------------

    @abstractmethod
    def expected_outputs(self, ctx: StepContext[I, P]) -> O:
        """The output spec for this run: file names relative to ``ctx.output_dir``."""

    @abstractmethod
    def run(self, ctx: StepContext[I, P]) -> StepResult:
        """Build and execute commands. Raise StepError on failure."""

    def validate_inputs(self, ctx: StepContext[I, P]) -> list[Problem]:
        """Default: every input path must exist as a non-empty file."""
        return [
            Problem(
                code="INPUT_MISSING",
                message=f"Input file was not found or is empty: {rel}",
                probable_cause="The file was moved, deleted or never created.",
                suggested_action="Check the file exists, or rerun the step that makes it.",
            )
            for rel in input_relpaths(ctx.inputs)
            if not _is_nonempty_file(ctx.input_path(rel))
        ]

    def ready(self, ctx: StepContext[I, P]) -> Problem | None:
        """Is everything this step needs from the researcher there? ``None`` means go ahead.
        A problem returned here is not a failure: the pipeline stops at this step in the state
        "Waiting for you" and carries on when the decision has been made."""
        return None

    def desc(self, ctx: StepContext[I, P], base: str) -> str:
        """The ``desc-`` value for this run's results: ``base``, plus the run's label when a
        pipeline gave the step another id, so repeated steps never overwrite each other."""
        return base if ctx.label == self.name else base + ctx.label

    def tool_versions(self, ctx: StepContext[I, P]) -> dict[str, str]:
        """Versions of external tools used (recorded in provenance). Default: none."""
        return {}

    def output_relpaths(self, ctx: StepContext[I, P]) -> list[str]:
        """Workspace-relative paths of the expected outputs."""
        return [
            ctx.workspace.relpath(ctx.output_dir / value)
            for _, value in self.expected_outputs(ctx)
            if isinstance(value, str)
        ]

    def prepare(self, ctx: StepContext[I, P]) -> None:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        ctx.log_dir.mkdir(parents=True, exist_ok=True)

    def validate_outputs(self, ctx: StepContext[I, P]) -> list[Problem]:
        """Default: every path field of the output spec must exist as a non-empty file."""
        problems: list[Problem] = []
        for field_name, value in self.expected_outputs(ctx):
            if isinstance(value, str) and not _is_nonempty_file(ctx.output_dir / value):
                problems.append(
                    Problem(
                        code="OUTPUT_MISSING",
                        message=f"Expected result '{field_name}' was not produced: {value}",
                        probable_cause="The tool finished without writing this file.",
                        suggested_action="Open the raw log for details, then retry the step.",
                    )
                )
        return problems

    def generate_qc(self, ctx: StepContext[I, P]) -> list[QCItem]:
        return []

    def register_outputs(self, ctx: StepContext[I, P]) -> None:
        """Default: record each output file in the workspace database."""
        subject_id = ctx.workspace.get_or_create_subject(ctx.subject)
        with ctx.workspace.session() as s:
            for _, value in self.expected_outputs(ctx):
                if not isinstance(value, str):
                    continue
                rel = ctx.workspace.relpath(ctx.output_dir / value)
                existing = s.scalar(select(File).where(File.relpath == rel))
                if existing is None:
                    s.add(File(subject_id=subject_id, relpath=rel, kind=self.name))
                else:
                    # File changed: drop the cached hash.
                    existing.sha256 = existing.size = existing.mtime_ns = None


def input_relpaths(inputs: BaseModel) -> list[str]:
    """Input specs are file paths: every ``str`` or ``list[str]`` field is a workspace-relative
    path. (Non-path settings belong in the parameter spec.)"""
    paths: list[str] = []
    for _, value in inputs:
        if isinstance(value, str):
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(v for v in value if isinstance(v, str))
    return paths


def _is_nonempty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def execute_step(step: Step[I, P, O], ctx: StepContext[I, P]) -> StepResult:
    """Run the full lifecycle: validate_inputs, prepare, run, validate_outputs,
    register_outputs, generate_qc. Raises StepError on any error-level problem."""
    try:
        input_problems = step.validate_inputs(ctx)
        _raise_on_errors(input_problems)
        step.prepare(ctx)
        result = step.run(ctx)
        outcome = step.validate_outputs(ctx)
        _raise_on_errors(outcome)
        step.register_outputs(ctx)
        result.qc = step.generate_qc(ctx)
        result.warnings = [p for p in input_problems + outcome if p.severity == "warning"]
        if not result.commands:
            result.commands = list(ctx.commands)
        return result
    except StepError:
        raise
    except Exception as exc:
        raise StepError(
            code="UNEXPECTED_ERROR",
            message=f"Step '{step.name}' failed unexpectedly: {type(exc).__name__}: {exc}",
            probable_cause="This is probably a bug in MRForge, not a problem with your data.",
            suggested_action="Open the raw log and report the problem together with this message.",
            log_path=ctx.log_dir / "stderr.log",
        ) from exc


def _raise_on_errors(problems: list[Problem]) -> None:
    errors = [p for p in problems if p.severity == "error"]
    if errors:
        first = errors[0]
        extra = f" (and {len(errors) - 1} more problem(s))" if len(errors) > 1 else ""
        raise StepError(
            code=first.code,
            message=first.message + extra,
            probable_cause=first.probable_cause,
            suggested_action=first.suggested_action,
        )
