"""The JobQueue interface. The API/CLI depend on this, not on a concrete queue, so an
RQ/Redis implementation can be added later without touching callers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class JobQueue(ABC):
    @abstractmethod
    def submit(self, job_id: int) -> None:
        """Queue a job (status Queued). Returns immediately."""

    @abstractmethod
    def cancel(self, job_id: int) -> None:
        """Cancel a queued job, or stop a running one."""

    @abstractmethod
    def cancel_all(self) -> None:
        """Cancel every queued and running job (used when the user presses Ctrl-C)."""

    @abstractmethod
    def wait(self, timeout: float | None = None) -> bool:
        """Block until no queued or running jobs remain. Returns False on timeout."""
