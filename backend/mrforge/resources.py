"""How much of the computer MRForge may use.

The policy is a small set of numbers kept with the other per-computer settings
(``config.json``): how many subjects are processed at once, how many threads each processing
job may use, an overall cap on busy cores, and how much memory must stay free. Presets
(Balanced, Max performance, Low impact) are computed from this machine's cores and memory.
A job only starts when the cap and the memory reserve allow it; otherwise it waits.

REVIEW(domain): the preset numbers are proposals; the thread settings reach FSL tools only
through the usual environment variables (OMP_NUM_THREADS and friends), which not every tool
honours.
"""

from __future__ import annotations

import os
from typing import Literal

import psutil
from pydantic import BaseModel, Field

from mrforge.config import load_config, save_config

Preset = Literal["balanced", "max", "low", "custom"]
WORKER_MARK = "mrforge.runner.worker"  # command-line mark of a processing job


class ResourcePolicy(BaseModel):
    preset: Preset = "balanced"
    max_subjects: int = Field(default=2, ge=1)  # subjects processed at the same time
    threads_per_job: int = Field(default=2, ge=1)
    cpu_cap: int = Field(default=4, ge=1)  # busy cores MRForge may use in total
    memory_reserve_gb: float = Field(default=4.0, ge=0)  # kept free for everything else


class Machine(BaseModel):
    cores: int
    ram_gb: float
    free_ram_gb: float
    jobs_running: int  # MRForge processing jobs running right now (all workspaces)


def machine() -> Machine:
    mem = psutil.virtual_memory()
    return Machine(
        cores=os.cpu_count() or 1,
        ram_gb=round(mem.total / 1e9, 1),
        free_ram_gb=round(mem.available / 1e9, 1),
        jobs_running=worker_count(),
    )


def preset_policy(
    name: Preset, cores: int | None = None, ram_gb: float | None = None
) -> ResourcePolicy:
    c = cores or os.cpu_count() or 1
    ram = ram_gb or psutil.virtual_memory().total / 1e9
    threads = 2 if c >= 4 else 1
    if name == "max":
        cap = c
        return ResourcePolicy(
            preset="max",
            max_subjects=max(1, cap // threads),
            threads_per_job=threads,
            cpu_cap=cap,
            memory_reserve_gb=round(max(2.0, 0.1 * ram), 1),
        )
    if name == "low":
        return ResourcePolicy(
            preset="low",
            max_subjects=1,
            threads_per_job=1,
            cpu_cap=1,
            memory_reserve_gb=round(max(6.0, 0.3 * ram), 1),
        )
    cap = max(1, c // 2)
    return ResourcePolicy(
        preset="balanced",
        max_subjects=max(1, cap // threads),
        threads_per_job=threads,
        cpu_cap=cap,
        memory_reserve_gb=round(max(4.0, 0.2 * ram), 1),
    )


def load_policy() -> ResourcePolicy:
    saved = load_config().get("resources")
    if isinstance(saved, dict):
        try:
            return ResourcePolicy.model_validate(saved)
        except ValueError:
            pass
    return preset_policy("balanced")


def save_policy(policy: ResourcePolicy) -> ResourcePolicy:
    config = load_config()
    config["resources"] = policy.model_dump()
    save_config(config)
    return policy


def thread_env(policy: ResourcePolicy) -> dict[str, str]:
    n = str(policy.threads_per_job)
    return {
        "OMP_NUM_THREADS": n,
        "OPENBLAS_NUM_THREADS": n,
        "MKL_NUM_THREADS": n,
        "VECLIB_MAXIMUM_THREADS": n,
        "NUMEXPR_NUM_THREADS": n,
    }


def worker_pids() -> set[int]:
    """Process ids of the processing jobs running on this computer now (every workspace)."""
    found: set[int] = set()
    for proc in psutil.process_iter(["cmdline"]):
        try:
            if WORKER_MARK in " ".join(proc.info["cmdline"] or []):
                found.add(proc.pid)
        except psutil.Error:
            continue
    return found


def worker_count() -> int:
    return len(worker_pids())


def max_jobs(policy: ResourcePolicy) -> int:
    return max(1, policy.cpu_cap // policy.threads_per_job)


def why_not_now(policy: ResourcePolicy, running: int | None = None) -> str | None:
    """None if one more job may start; else the reason, in plain words. ``running`` is the
    number of jobs known to be running (including ones started a moment ago that the process
    list may not show yet); by default it is read from the process list."""
    if (worker_count() if running is None else running) >= max_jobs(policy):
        return "the limit for parallel work on this computer is reached"
    free = psutil.virtual_memory().available / 1e9
    if free < policy.memory_reserve_gb:
        return f"free memory ({free:.1f} GB) is below the reserve ({policy.memory_reserve_gb:g} GB)"
    return None
