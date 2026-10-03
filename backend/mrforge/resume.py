"""The resume rule (docs/architecture.md section 7).

A previous run is reusable only if all hold: status Completed (and it is the latest run),
same step version, same parameter hash, same input file hashes, and all registered outputs
exist, pass validate_outputs and are unchanged since they were recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from mrforge.hashing import file_sha256
from mrforge.models import Job, JobStatus
from mrforge.provenance import read_provenance
from mrforge.runner.jobs import build_context, normalise_specs, param_hash
from mrforge.steps.base import input_relpaths
from mrforge.workspace import Workspace


@dataclass(frozen=True)
class Reuse:
    reusable: bool
    reason: str  # plain language: why it can be skipped, or why it must run
    job_id: int | None = None


def check_reusable(
    ws: Workspace,
    step_name: str,
    subject: str,
    inputs: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    session: str | None = None,
    label: str | None = None,
) -> Reuse:
    step, inputs_d, params_d = normalise_specs(step_name, inputs, params)
    _, ctx = build_context(ws, step_name, subject, session, inputs_d, params_d, label)

    prov = read_provenance(ctx.output_dir)
    if prov is None:
        return Reuse(False, "it has not been run yet")
    if prov.status != JobStatus.COMPLETED.value:
        return Reuse(False, f"its last run ended as {prov.status}")

    out_rel = ws.relpath(ctx.output_dir)
    with ws.session() as s:
        latest = s.scalar(select(Job).where(Job.output_dir == out_rel).order_by(Job.id.desc()))
    if latest is None or latest.id != prov.job_id or latest.status != JobStatus.COMPLETED.value:
        return Reuse(False, "its latest run did not complete")

    if prov.step.version != step.version:
        return Reuse(False, f"the step was updated (version {prov.step.version} to {step.version})")
    if prov.parameter_hash != param_hash(params_d):
        return Reuse(False, "its settings changed")

    recorded_in = {f.path: f.sha256 for f in prov.inputs}
    current_in: dict[str, str] = {}
    for rel in input_relpaths(ctx.inputs):
        if not ws.abspath(rel).is_file():
            return Reuse(False, f"an input file is missing: {rel}")
        current_in[rel] = file_sha256(ws, rel)
    if current_in != recorded_in:
        changed = sorted(k for k in current_in if recorded_in.get(k) != current_in[k])
        return Reuse(False, f"input data changed: {', '.join(changed) or 'inputs differ'}")

    problems = [p for p in step.validate_outputs(ctx) if p.severity == "error"]
    if problems:
        return Reuse(False, f"a result is missing or invalid: {problems[0].message}")
    recorded_out = {f.path: f.sha256 for f in prov.outputs}
    expected = step.output_relpaths(ctx)
    if set(expected) != set(recorded_out):
        return Reuse(False, "the expected results differ from those recorded")
    for rel in expected:
        if file_sha256(ws, rel) != recorded_out[rel]:
            return Reuse(False, f"a result was modified after it was made: {rel}")

    return Reuse(True, "already completed with the same settings and inputs", prov.job_id)
