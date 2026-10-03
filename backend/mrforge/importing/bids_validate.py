"""Run the BIDS validator on rawbids/ and explain its findings in plain language.

The validator (npm ``bids-validator``) reports problems with numeric codes and technical text.
``bids_messages.yaml`` turns the codes that can occur for MRI data into "what happened, why,
what to do". Codes without a translation are still shown, with the validator's own wording and
a note that no plain-language version exists yet.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from mrforge.config import load_config
from mrforge.errors import StepError
from mrforge.workspace import Workspace

MESSAGES_FILE = Path(__file__).with_name("bids_messages.yaml")
REPORT_FILE = "imports/bids-validation.json"
MAX_FILES_SHOWN = 5
TIMEOUT_S = 600
NVM_PATTERN = ".nvm/versions/node/*/bin/bids-validator"
FALLBACK_LOCATIONS = ("/opt/homebrew/bin/bids-validator", "/usr/local/bin/bids-validator")


class Message(BaseModel):
    key: str
    what: str
    why: str
    action: str


class ValidationIssue(BaseModel):
    code: int
    key: str
    severity: Literal["error", "warning"]
    what: str
    why: str
    action: str
    files: list[str] = []  # dataset-relative paths (at most a few)
    n_files: int = 0  # how many files the validator counted in total
    details: list[str] = []  # the validator's evidence for the listed files
    translated: bool = True
    original: str = ""  # the validator's own wording
    help_url: str | None = None


class ValidationReport(BaseModel):
    validator: str
    version: str
    dataset: str  # workspace-relative, e.g. "rawbids"
    ran: datetime = Field(default_factory=lambda: datetime.now(UTC))
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    summary: dict[str, Any] = {}

    @property
    def ok(self) -> bool:
        return not self.errors


# -- messages -----------------------------------------------------------------------------


def load_messages(path: Path = MESSAGES_FILE) -> dict[int, Message]:
    try:
        data = yaml.safe_load(path.read_text())
        return {int(code): Message(**entry) for code, entry in data["messages"].items()}
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
        raise StepError(
            code="MESSAGES_INVALID",
            message=f"The BIDS message file could not be used: {path.name}",
            probable_cause=f"{exc}",
            suggested_action="Restore the file from MRForge, or report the problem.",
        ) from exc


# -- finding and running the validator ----------------------------------------------------


def find_validator(setting: str | None = None) -> Path:
    """Order: app setting (``mrforge config bids-validator``), PATH, nvm installs, common places."""
    configured = setting if setting is not None else load_config().get("bids_validator")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(str(configured)).expanduser())
    on_path = shutil.which("bids-validator")
    if on_path:
        candidates.append(Path(on_path))
    candidates += sorted(Path.home().glob(NVM_PATTERN), reverse=True)
    candidates += [Path(p) for p in FALLBACK_LOCATIONS]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise StepError(
        code="VALIDATOR_NOT_FOUND",
        message="The BIDS validator (the program that checks a dataset against the BIDS standard) "
        "could not be found.",
        probable_cause="It is not installed, or MRForge does not know where it is.",
        suggested_action="Install it with 'npm install -g bids-validator', or tell MRForge where "
        "it is with 'mrforge config bids-validator /path/to/bids-validator'.",
    )


def _run_env(exe: Path) -> dict[str, str]:
    """The validator is a node script; make sure the node next to it can be found."""
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(exe.parent), env.get("PATH", "")])
    return env


def validator_version(exe: Path) -> str:
    try:
        out = subprocess.run(
            [str(exe), "--version"], capture_output=True, text=True, env=_run_env(exe), timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    return lines[-1] if lines else "unknown"


def _relative(path: str | None) -> str | None:
    return None if not path else path.lstrip("/")


def parse_validator_json(
    data: dict[str, Any], messages: dict[int, Message]
) -> tuple[list[ValidationIssue], list[ValidationIssue], dict[str, Any]]:
    """Turn the validator's JSON into translated issues (errors first, then warnings)."""

    def convert(raw: dict[str, Any], severity: Literal["error", "warning"]) -> ValidationIssue:
        code = int(raw.get("code", 0))
        msg = messages.get(code)
        files: list[str] = []
        details: list[str] = []
        for entry in raw.get("files", []):
            name = _relative((entry.get("file") or {}).get("relativePath"))
            if name and name not in files:
                files.append(name)
            evidence = entry.get("evidence")
            if evidence and name:
                details.append(f"{name}: {evidence}")
        original = str(raw.get("reason", "")).strip()
        with_file = [e for e in raw.get("files", []) if e.get("file")]
        total = len(with_file) + int(raw.get("additionalFileCount", 0))
        if msg is not None:
            what, why, action = msg.what, msg.why, msg.action
        else:
            what = original or f"The validator reported problem {raw.get('key', code)}."
            why = "MRForge has no plain-language explanation for this message yet."
            help_url = raw.get("helpUrl")
            action = (
                f"See {help_url} for details, or ask whoever maintains the dataset."
                if help_url
                else "Ask whoever maintains the dataset."
            )
        return ValidationIssue(
            code=code,
            key=str(raw.get("key", "")),
            severity=severity,
            what=what,
            why=why,
            action=action,
            files=files[:MAX_FILES_SHOWN],
            n_files=total if files else 0,
            details=details[:MAX_FILES_SHOWN],
            translated=msg is not None,
            original=original,
            help_url=raw.get("helpUrl"),
        )

    issues = data.get("issues", {})
    errors = [convert(r, "error") for r in issues.get("errors", [])]
    warnings = [convert(r, "warning") for r in issues.get("warnings", [])]
    s = data.get("summary", {})
    summary = {
        "subjects": len(s.get("subjects", [])),
        "sessions": len(s.get("sessions", [])),
        "tasks": s.get("tasks", []),
        "files": s.get("totalFiles"),
        "size_bytes": s.get("size"),
        "data_types": s.get("dataTypes", []),
    }
    return errors, warnings, summary


def validate_path(root: Path, label: str, setting: str | None = None) -> ValidationReport:
    """Run the validator on any dataset folder (nothing is saved)."""
    exe = find_validator(setting)
    try:
        proc = subprocess.run(
            [str(exe), "--json", str(root)],
            capture_output=True,
            text=True,
            env=_run_env(exe),
            timeout=TIMEOUT_S,
        )
        raw = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise StepError(
            code="VALIDATOR_FAILED",
            message="The BIDS validator did not give a usable answer.",
            probable_cause=f"{type(exc).__name__}: it may have crashed, or node is missing.",
            suggested_action="Run 'bids-validator <dataset folder>' yourself to see why, or "
            "reinstall it with 'npm install -g bids-validator'.",
        ) from exc
    errors, warnings, summary = parse_validator_json(raw, load_messages())
    return ValidationReport(
        validator=str(exe.name),
        version=validator_version(exe),
        dataset=label,
        errors=errors,
        warnings=warnings,
        summary=summary,
    )


def validate_dataset(
    ws: Workspace, setting: str | None = None, dataset: str = "rawbids"
) -> ValidationReport:
    """Run the validator on a dataset folder of the workspace and save the report."""
    root = ws.root / dataset
    if not root.is_dir():
        raise StepError(
            code="NOTHING_TO_VALIDATE",
            message=f"There is no '{dataset}' folder in this workspace yet.",
            suggested_action="Import data first with 'mrforge import run'.",
        )
    report = validate_path(root, dataset, setting)
    save_report(ws, report)
    return report


def save_report(ws: Workspace, report: ValidationReport) -> Path:
    path = ws.root / REPORT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(report.model_dump_json(indent=2) + "\n")
    tmp.replace(path)
    return path


# -- text for people ----------------------------------------------------------------------


def format_issue(issue: ValidationIssue, number: int) -> str:
    lines = [f"{number}. {issue.what}"]
    lines.append(f"   Why: {issue.why}")
    lines.append(f"   What to do: {issue.action}")
    if issue.files:
        more = issue.n_files - len(issue.files)
        shown = ", ".join(issue.files) + (f" and {more} more" if more > 0 else "")
        lines.append(f"   Affects: {shown}")
    for detail in issue.details:
        lines.append(f"   Detail: {detail}")
    if not issue.translated:
        lines.append(
            f"   (BIDS validator message {issue.code}, not yet explained in plain language)"
        )
    else:
        lines.append(f"   (BIDS validator code {issue.code}: {issue.key})")
    return "\n".join(lines)


def format_report(report: ValidationReport) -> str:
    s = report.summary
    head = (
        f"BIDS check of {report.dataset}/ with {report.validator} {report.version}: "
        f"{s.get('subjects', 0)} subject(s), {s.get('files', '?')} files."
    )
    lines = [head, ""]
    if report.ok and not report.warnings:
        lines.append("The dataset follows the BIDS standard. No problems found.")
        return "\n".join(lines)
    if report.errors:
        lines.append(f"Problems that need fixing ({len(report.errors)}):")
        for i, issue in enumerate(report.errors, start=1):
            lines += [format_issue(issue, i), ""]
    else:
        lines += ["No errors: the dataset follows the BIDS standard.", ""]
    if report.warnings:
        lines.append(f"Worth knowing ({len(report.warnings)}):")
        for i, issue in enumerate(report.warnings, start=1):
            lines += [format_issue(issue, i), ""]
    return "\n".join(lines).rstrip()
