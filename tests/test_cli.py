"""CLI tests: a fast in-process set, plus real subprocess runs of the `mrforge` command."""

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mrforge.cli import app, parse_pairs
from mrforge.runner.jobs import list_jobs
from mrforge.steps.fake import FakeInput, FakeParams
from mrforge.workspace import Workspace

EXAMPLE = Path(__file__).parent.parent / "examples" / "fake_pipeline.yaml"
runner = CliRunner()


def mrforge(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrforge.cli", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )


@pytest.fixture
def wsdir(tmp_path: Path) -> Path:
    path = tmp_path / "demo"
    assert runner.invoke(app, ["workspace", "create", str(path)]).exit_code == 0
    return path


# -- in-process --------------------------------------------------------------


def test_parse_pairs() -> None:
    p = parse_pairs(["duration=0.5", "content=hello", "fail_at=never"], FakeParams)
    assert p == {"duration": 0.5, "content": "hello", "fail_at": "never"}
    # a single value for a list field is wrapped; repeats build a list
    assert parse_pairs(["sources=a.txt"], FakeInput) == {"sources": ["a.txt"]}
    assert parse_pairs(["sources=a", "sources=b"], FakeInput) == {"sources": ["a", "b"]}


def test_workspace_create_and_errors(tmp_path: Path) -> None:
    r = runner.invoke(app, ["workspace", "create", str(tmp_path / "w")])
    assert r.exit_code == 0 and "Created workspace" in r.output
    again = runner.invoke(app, ["workspace", "create", str(tmp_path / "w")])
    assert again.exit_code == 1 and "already exists" in again.output
    missing = runner.invoke(app, ["status", "-w", str(tmp_path / "nowhere")])
    assert missing.exit_code == 1 and "No workspace found" in missing.output
    assert "Traceback" not in missing.output


def test_steps_lists_fake() -> None:
    r = runner.invoke(app, ["steps"])
    assert r.exit_code == 0 and "fake (version 1)" in r.output


def test_bad_inputs_are_plain_language(wsdir: Path) -> None:
    unknown = runner.invoke(app, ["run", "nope", "-s", "sub-001", "-w", str(wsdir)])
    assert unknown.exit_code == 1 and "UNKNOWN_STEP" in unknown.output
    bad = runner.invoke(
        app, ["run", "fake", "-s", "sub-001", "-w", str(wsdir), "-p", "fail_at=sometimes"]
    )
    assert bad.exit_code == 1 and "not valid" in bad.output and "What to do" in bad.output
    notkv = runner.invoke(app, ["run", "fake", "-s", "sub-001", "-w", str(wsdir), "-p", "oops"])
    assert notkv.exit_code == 1 and "name=value" in notkv.output
    assert list_jobs(Workspace.open(wsdir)) == []


def test_resume_without_pipeline(wsdir: Path) -> None:
    r = runner.invoke(app, ["resume", "-w", str(wsdir)])
    assert r.exit_code == 1 and "no pipeline to resume" in r.output.lower()


# -- real command-line runs ---------------------------------------------------


def test_run_skip_force_and_log(wsdir: Path) -> None:
    w = str(wsdir)
    first = mrforge("run", "fake", "-s", "sub-001", "-w", w, "-p", "content=hi")
    assert first.returncode == 0 and "Ran" in first.stdout and "job 1" in first.stdout
    second = mrforge("run", "fake", "-s", "sub-001", "-w", w, "-p", "content=hi")
    assert second.returncode == 0 and "Already completed" in second.stdout
    forced = mrforge("run", "fake", "-s", "sub-001", "-w", w, "-p", "content=hi", "--force")
    assert forced.returncode == 0 and "Ran. Running because --force" in forced.stdout
    log = mrforge("log", "1", "-w", w)
    assert log.returncode == 0 and "stdout.log" in log.stdout and "Completed" in log.stdout
    status = mrforge("status", "-w", w)
    assert "Completed" in status.stdout and status.stdout.count("Completed") == 2


def test_failure_message_and_log_link(wsdir: Path) -> None:
    w = str(wsdir)
    r = mrforge("run", "fake", "-s", "sub-001", "-w", w, "-p", "fail_at=command")
    assert r.returncode == 1
    assert "exit code 1" in r.stdout and "What to do:" in r.stdout and "Raw log:" in r.stdout
    log = mrforge("log", "1", "-w", w)
    assert "Failed" in log.stdout and "$ " in log.stdout  # raw tool log is one command away


def test_pipeline_fails_then_resume_skips_finished_steps(wsdir: Path) -> None:
    w = str(wsdir)
    first = mrforge("pipeline", "run", str(EXAMPLE), "-w", w)
    assert first.returncode == 1
    out = first.stdout
    assert "a: Ran" in out and "b: Ran" in out and "c: Failed" in out
    assert "mrforge resume" in out
    assert "Interrupted" not in mrforge("status", "-w", w).stdout
    resumed = mrforge("resume", "-w", w)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert "a: Already completed" in resumed.stdout
    assert "b: Already completed" in resumed.stdout
    assert "c: Ran" in resumed.stdout and "Pipeline finished" in resumed.stdout
    labels = sorted(j.label or "" for j in list_jobs(Workspace.open(wsdir)))
    assert labels == ["a", "b", "c", "c"]


def test_ctrl_c_cancels_the_running_job(wsdir: Path) -> None:
    ws = Workspace.open(wsdir)
    proc = subprocess.Popen(
        [sys.executable, "-m", "mrforge.cli", "run", "fake", "-s", "sub-001",
         "-w", str(wsdir), "-p", "duration=60"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # A test run started in the background inherits "ignore Ctrl-C"; Python then never
        # installs its own handler. Restore the default so this test means the same everywhere.
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
    )  # fmt: skip
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        jobs = list_jobs(ws)
        if jobs and jobs[0].status == "Running":
            break
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("job never started")
    time.sleep(0.5)
    proc.send_signal(signal.SIGINT)
    proc.communicate(timeout=60)
    assert proc.returncode == 130
    assert list_jobs(ws)[0].status == "Cancelled"


def test_status_shows_local_time_not_utc(wsdir: Path) -> None:
    from datetime import UTC, datetime

    from mrforge.cli import _local_time

    naive_utc = datetime(2026, 1, 1, 12, 0, 0)  # how SQLite hands back a stored UTC time
    expected = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert _local_time(naive_utc) == expected
