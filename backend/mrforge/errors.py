"""Structured, plain-language errors. Codes are catalogued in docs/errors.md."""

from __future__ import annotations

from pathlib import Path


class StepError(Exception):
    """A step failed. Every field is meant to be shown to a non-expert user.

    The raw tool log is never the only thing shown; ``log_path`` keeps it one click away.
    """

    def __init__(
        self,
        code: str,
        message: str,
        probable_cause: str = "",
        suggested_action: str = "",
        log_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.probable_cause = probable_cause
        self.suggested_action = suggested_action
        self.log_path = log_path

    def format(self) -> str:
        lines = [f"[{self.code}] {self.message}"]
        if self.probable_cause:
            lines.append(f"Why: {self.probable_cause}")
        if self.suggested_action:
            lines.append(f"What to do: {self.suggested_action}")
        if self.log_path:
            lines.append(f"Raw log: {self.log_path}")
        return "\n".join(lines)
