import sys
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from mrforge.errors import StepError
from mrforge.models import File
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult, execute_step
from mrforge.steps.registry import get_step, list_steps, register_step
from mrforge.workspace import Workspace


class In(BaseModel):
    source: str


class Params(BaseModel):
    text: str = "hello"
    fail_command: bool = False
    crash: bool = False
    skip_output: bool = False
    warn: bool = False


class Out(BaseModel):
    result: str = "result.txt"


class CopyStep(Step[In, Params, Out]):
    """Copies the input file to result.txt through a real subprocess."""

    name = "copy-test"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = In, Params, Out

    def __init__(self) -> None:
        self.calls: list[str] = []

    def expected_outputs(self, ctx: StepContext[In, Params]) -> Out:
        return Out()

    def validate_inputs(self, ctx: StepContext[In, Params]) -> list[Problem]:
        self.calls.append("validate_inputs")
        return super().validate_inputs(ctx)

    def prepare(self, ctx: StepContext[In, Params]) -> None:
        self.calls.append("prepare")
        super().prepare(ctx)

    def run(self, ctx: StepContext[In, Params]) -> StepResult:
        self.calls.append("run")
        if ctx.params.crash:
            raise RuntimeError("boom")
        code = (
            "import sys; sys.exit(3)"
            if ctx.params.fail_command
            else "import shutil,sys; shutil.copy(sys.argv[1], sys.argv[2])"
        )
        target = ctx.output_dir / ("other.txt" if ctx.params.skip_output else "result.txt")
        ctx.run_command(
            [sys.executable, "-c", code, str(ctx.input_path(ctx.inputs.source)), str(target)]
        )
        return StepResult()

    def validate_outputs(self, ctx: StepContext[In, Params]) -> list[Problem]:
        self.calls.append("validate_outputs")
        problems = super().validate_outputs(ctx)
        if ctx.params.warn:
            problems.append(Problem(code="ODD", message="Looks odd", severity="warning"))
        return problems

    def register_outputs(self, ctx: StepContext[In, Params]) -> None:
        self.calls.append("register_outputs")
        super().register_outputs(ctx)

    def generate_qc(self, ctx: StepContext[In, Params]) -> list[QCItem]:
        self.calls.append("generate_qc")
        return [QCItem(name="size", kind="metric", value=1.0)]


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    w = Workspace.create(tmp_path / "ws")
    (w.root / "rawbids").mkdir(exist_ok=True)
    (w.root / "rawbids" / "in.txt").write_text("data")
    return w


def make_ctx(
    ws: Workspace, source: str = "rawbids/in.txt", **params: object
) -> StepContext[In, Params]:
    return StepContext(
        workspace=ws,
        subject="sub-001",
        inputs=In(source=source),
        params=Params(**params),  # type: ignore[arg-type]
        output_dir=ws.derivatives_dir / "sub-001" / "copy-test",
    )


def test_lifecycle_order_and_outputs(ws: Workspace) -> None:
    step, ctx = CopyStep(), make_ctx(ws)
    result = execute_step(step, ctx)
    assert step.calls == [
        "validate_inputs",
        "prepare",
        "run",
        "validate_outputs",
        "register_outputs",
        "generate_qc",
    ]
    assert (ctx.output_dir / "result.txt").read_text() == "data"
    assert result.qc[0].name == "size"
    assert result.commands[0].return_code == 0
    assert (ctx.log_dir / "stdout.log").read_text().startswith("$ ")
    with ws.session() as s:
        rel = s.scalar(select(File.relpath))
    assert rel == "derivatives/mrforge/sub-001/copy-test/result.txt"


def test_missing_input_stops_before_run(ws: Workspace) -> None:
    step = CopyStep()
    with pytest.raises(StepError) as info:
        execute_step(step, make_ctx(ws, source="rawbids/nope.txt"))
    assert info.value.code == "INPUT_MISSING"
    assert info.value.suggested_action
    assert step.calls == ["validate_inputs"]


def test_command_failure_is_plain_language_with_log(ws: Workspace) -> None:
    ctx = make_ctx(ws, fail_command=True)
    with pytest.raises(StepError) as info:
        execute_step(CopyStep(), ctx)
    err = info.value
    assert err.code == "COMMAND_FAILED" and "exit code 3" in err.message
    assert err.log_path == ctx.log_dir / "stderr.log" and err.log_path.is_file()
    assert "Raw log:" in err.format()


def test_missing_output_is_detected(ws: Workspace) -> None:
    step = CopyStep()
    with pytest.raises(StepError) as info:
        execute_step(step, make_ctx(ws, skip_output=True))
    assert info.value.code == "OUTPUT_MISSING"
    assert "register_outputs" not in step.calls


def test_unexpected_exception_is_wrapped(ws: Workspace) -> None:
    with pytest.raises(StepError) as info:
        execute_step(CopyStep(), make_ctx(ws, crash=True))
    assert info.value.code == "UNEXPECTED_ERROR" and "boom" in info.value.message


def test_tool_not_found(ws: Workspace) -> None:
    ctx = make_ctx(ws)
    ctx.output_dir.mkdir(parents=True)
    with pytest.raises(StepError) as info:
        ctx.run_command(["definitely-not-a-real-tool"])
    assert info.value.code == "TOOL_NOT_FOUND"


def test_warnings_do_not_block(ws: Workspace) -> None:
    result = execute_step(CopyStep(), make_ctx(ws, warn=True))
    assert [w.code for w in result.warnings] == ["ODD"]


def test_registry(ws: Workspace) -> None:
    register_step(CopyStep)
    register_step(CopyStep)  # same class twice is fine
    assert "copy-test" in list_steps()
    assert isinstance(get_step("copy-test"), CopyStep)
    with pytest.raises(StepError) as info:
        get_step("nope")
    assert info.value.code == "UNKNOWN_STEP" and "copy-test" in info.value.suggested_action
