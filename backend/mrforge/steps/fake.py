"""FakeStep: a configurable stand-in step for testing the engine without FSL.

It runs real subprocesses (so killing and failing behave like real tools), can fail at a
chosen point, and writes a dummy output whose content depends on its inputs, so downstream
invalidation can be observed.
"""

from __future__ import annotations

import hashlib
import sys
from typing import Literal

from pydantic import BaseModel

from mrforge.errors import StepError
from mrforge.steps.base import Step, StepContext, StepResult
from mrforge.steps.registry import register_step


class FakeInput(BaseModel):
    sources: list[str] = []  # workspace-relative files this step "consumes"


class FakeParams(BaseModel):
    duration: float = 0.0  # seconds of fake work
    fail_at: Literal["never", "start", "middle", "end", "command"] = "never"
    content: str = "x"
    # Fail the first time only: creates this file (relative to the workspace) and fails if
    # it did not exist yet. Lets tests and demos show "fail, then resume".
    fail_once_marker: str | None = None


class FakeOutput(BaseModel):
    result: str = "result.txt"


@register_step
class FakeStep(Step[FakeInput, FakeParams, FakeOutput]):
    name = "fake"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = FakeInput, FakeParams, FakeOutput

    def expected_outputs(self, ctx: StepContext[FakeInput, FakeParams]) -> FakeOutput:
        # e.g. sub-001_desc-a_fake.txt: the run's label keeps repeated fake steps apart
        return FakeOutput(result=ctx.bids_name("fake", ".txt", desc=ctx.label))

    def _sleep(self, ctx: StepContext[FakeInput, FakeParams], seconds: float) -> None:
        if seconds > 0:
            ctx.run_command([sys.executable, "-c", f"import time; time.sleep({seconds})"])

    def _fail(self, where: str) -> StepError:
        return StepError(
            code="FAKE_FAILURE",
            message=f"The fake step was told to fail at '{where}'.",
            probable_cause="This is a test step configured to fail.",
            suggested_action="Change the 'fail_at' parameter and run again.",
        )

    def run(self, ctx: StepContext[FakeInput, FakeParams]) -> StepResult:
        p = ctx.params
        if p.fail_at == "start":
            raise self._fail("start")
        if p.fail_once_marker:
            marker = ctx.workspace.root / p.fail_once_marker
            if not marker.exists():
                marker.write_text("failed once\n")
                raise self._fail("first attempt")
        self._sleep(ctx, p.duration / 2)
        if p.fail_at == "middle":
            raise self._fail("middle")
        if p.fail_at == "command":
            ctx.run_command([sys.executable, "-c", "import sys; sys.exit(1)"])
        self._sleep(ctx, p.duration / 2)
        if p.fail_at == "end":
            raise self._fail("end")
        digest = hashlib.sha256()
        for src in ctx.inputs.sources:
            digest.update(ctx.input_path(src).read_bytes())
        (ctx.output_dir / self.expected_outputs(ctx).result).write_text(
            f"{p.content}:{digest.hexdigest()[:12]}\n"
        )
        return StepResult()
