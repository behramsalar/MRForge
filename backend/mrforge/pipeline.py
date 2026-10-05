"""Pipeline specs: an ordered list of steps whose inputs may refer to earlier outputs.

YAML example::

    name: demo
    subject: sub-001
    steps:
      - id: a
        step: fake
        params: {duration: 0.2}
      - id: b
        step: fake
        inputs: {sources: ["${a.result}"]}   # output field 'result' of step 'a'
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from mrforge.errors import StepError

REF = re.compile(r"\$\{([A-Za-z0-9_-]+)\.([A-Za-z0-9_]+)\}")


class PipelineStep(BaseModel):
    id: str  # what later steps refer to; unique in the pipeline
    # Names the step's run folder and result descriptions (default: the id). Several steps
    # can share one label when their inputs differ (for example one per recording).
    label: str | None = None
    step: str
    subject: str | None = None
    session: str | None = None
    inputs: dict[str, Any] = {}
    params: dict[str, Any] = {}


class PipelineSpec(BaseModel):
    name: str
    subject: str | None = None
    steps: list[PipelineStep]


def _invalid(message: str) -> StepError:
    return StepError(
        code="PIPELINE_INVALID",
        message=message,
        probable_cause="The pipeline file has a mistake.",
        suggested_action="Correct the pipeline file and run again.",
    )


def parse_pipeline(data: Any) -> PipelineSpec:
    try:
        spec = PipelineSpec.model_validate(data)
    except ValidationError as exc:
        raise _invalid(f"The pipeline file is not valid: {exc.errors()[0]['msg']}") from exc
    seen: set[str] = set()
    for st in spec.steps:
        if st.id in seen:
            raise _invalid(f"Two steps share the id '{st.id}'.")
        if st.subject is None and spec.subject is None:
            raise _invalid(f"Step '{st.id}' has no subject (set one on the step or the pipeline).")
        for ref_id, _ in references(st.inputs):
            if ref_id not in seen:
                raise _invalid(
                    f"Step '{st.id}' uses the result of '{ref_id}', which must be listed before it."
                )
        seen.add(st.id)
    return spec


def load_pipeline(path: Path) -> PipelineSpec:
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise StepError(
            code="PIPELINE_UNREADABLE",
            message=f"The pipeline file could not be read: {path}",
            probable_cause=str(exc),
            suggested_action="Check the path and that the file is valid YAML.",
        ) from exc
    return parse_pipeline(data)


def references(value: Any) -> list[tuple[str, str]]:
    """All (step id, output field) references found in a nested value."""
    if isinstance(value, str):
        return [(m.group(1), m.group(2)) for m in REF.finditer(value)]
    if isinstance(value, list):
        return [r for v in value for r in references(v)]
    if isinstance(value, dict):
        return [r for v in value.values() for r in references(v)]
    return []


def resolve_references(value: Any, outputs: dict[str, dict[str, str]]) -> Any:
    """Replace ``${id.field}`` by the workspace-relative path of that output."""
    if isinstance(value, str):

        def sub(m: re.Match[str]) -> str:
            try:
                return outputs[m.group(1)][m.group(2)]
            except KeyError:
                raise _invalid(
                    f"'{m.group(0)}' does not match any output of step '{m.group(1)}'."
                ) from None

        return REF.sub(sub, value)
    if isinstance(value, list):
        return [resolve_references(v, outputs) for v in value]
    if isinstance(value, dict):
        return {k: resolve_references(v, outputs) for k, v in value.items()}
    return value
