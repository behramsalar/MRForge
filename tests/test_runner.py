"""Runner tests use real worker processes and really kill them (no mocks)."""

import os
import signal
import time
from collections.abc import Callable
from pathlib import Path

import psutil
import pytest

from mrforge.errors import StepError
from mrforge.models import JobStatus
from mrforge.runner.jobs import (
    create_job,
    get_job,
    list_jobs,
    param_hash,
    process_alive,
    recover_stale_jobs,
)
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.workspace import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def wait_for(cond: Callable[[], bool], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def gone(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def status(ws: Workspace, job_id: int) -> str:
    return get_job(ws, job_id).status


def running_with_tool(ws: Workspace, job_id: int) -> tuple[int, psutil.Process]:
    """Wait until the job is Running and its tool (sleeping child) exists."""
    wait_for(lambda: status(ws, job_id) == "Running" and get_job(ws, job_id).pid is not None)
    pid = get_job(ws, job_id).pid
    assert pid is not None
    wait_for(lambda: len(psutil.Process(pid).children(recursive=True)) > 0)
    return pid, psutil.Process(pid).children(recursive=True)[0]


def test_job_completes(ws: Workspace) -> None:
    q = LocalJobQueue(ws)
    jid = create_job(ws, "fake", "sub-001", params={"content": "hi"})
    q.submit(jid)
    assert q.wait(timeout=30)
    job = get_job(ws, jid)
    assert job.status == "Completed" and job.return_code == 0
    assert job.started and job.finished and job.pid
    assert (
        (ws.abspath(job.output_dir or "") / "sub-001_desc-fake_fake.txt")
        .read_text()
        .startswith("hi:")
    )


def test_failure_is_recorded_in_plain_language(ws: Workspace) -> None:
    q = LocalJobQueue(ws)
    jid = create_job(ws, "fake", "sub-001", params={"fail_at": "start"})
    q.submit(jid)
    assert q.wait(timeout=30)
    job = get_job(ws, jid)
    assert job.status == "Failed" and job.error_code == "FAKE_FAILURE"
    assert job.error_message and "What to do:" in job.error_message


def test_invalid_params_rejected_before_queueing(ws: Workspace) -> None:
    with pytest.raises(StepError) as info:
        create_job(ws, "fake", "sub-001", params={"fail_at": "sometimes"})
    assert info.value.code == "PARAMS_INVALID"
    assert list_jobs(ws) == []


def test_param_hash_is_order_independent() -> None:
    assert param_hash({"a": 1, "b": 2}) == param_hash({"b": 2, "a": 1})
    assert param_hash({"a": 1}) != param_hash({"a": 2})


def test_kill_worker_is_interrupted_and_orphans_cleaned(ws: Workspace) -> None:
    q = LocalJobQueue(ws)
    jid = create_job(ws, "fake", "sub-001", params={"duration": 60})
    q.submit(jid)
    worker_pid, tool = running_with_tool(ws, jid)
    tool_pid = tool.pid

    os.kill(worker_pid, signal.SIGKILL)  # the worker dies without recording anything
    wait_for(lambda: not process_alive(worker_pid, get_job(ws, jid).pid_start_time))
    assert status(ws, jid) == "Running"  # the database still lies, as after a crash

    # A fresh start (new queue object, as after restarting the app) must repair it.
    LocalJobQueue(ws)
    job = get_job(ws, jid)
    assert job.status == "Interrupted" and job.error_code == "INTERRUPTED"
    wait_for(
        lambda: not psutil.pid_exists(tool_pid) or psutil.Process(tool_pid).status() == "zombie"
    )


def test_kill_tool_is_interrupted_not_failed(ws: Workspace) -> None:
    q = LocalJobQueue(ws)
    jid = create_job(ws, "fake", "sub-001", params={"duration": 60})
    q.submit(jid)
    _, tool = running_with_tool(ws, jid)
    tool.kill()
    assert q.wait(timeout=30)
    job = get_job(ws, jid)
    assert job.status == "Interrupted" and job.error_code == "COMMAND_KILLED"


def test_cancel_running_job(ws: Workspace) -> None:
    q = LocalJobQueue(ws)
    jid = create_job(ws, "fake", "sub-001", params={"duration": 60})
    q.submit(jid)
    worker_pid, tool = running_with_tool(ws, jid)
    q.cancel(jid)
    assert q.wait(timeout=30)
    assert status(ws, jid) == "Cancelled"
    wait_for(
        lambda: not psutil.pid_exists(tool.pid) or psutil.Process(tool.pid).status() == "zombie"
    )


def test_cancel_queued_job(ws: Workspace) -> None:
    q = LocalJobQueue(ws, max_concurrency=1)
    first = create_job(ws, "fake", "sub-001", params={"duration": 60})
    second = create_job(ws, "fake", "sub-002")
    q.submit(first)
    q.submit(second)  # waits behind the first
    assert status(ws, second) == "Queued"
    q.cancel(second)
    assert status(ws, second) == "Cancelled"
    running_with_tool(ws, first)
    q.cancel(first)
    assert q.wait(timeout=30)


def test_max_concurrency_is_respected(ws: Workspace) -> None:
    q = LocalJobQueue(ws, max_concurrency=2)
    ids = [create_job(ws, "fake", f"sub-00{i}", params={"duration": 1.0}) for i in range(4)]
    for jid in ids:
        q.submit(jid)
    peak = 0
    while not q.wait(timeout=0.1):
        peak = max(peak, sum(1 for j in list_jobs(ws) if j.status == "Running"))
    assert peak == 2
    assert all(status(ws, i) == "Completed" for i in ids)


def test_process_alive_checks_start_time() -> None:
    me = psutil.Process()
    assert process_alive(me.pid, me.create_time())
    assert not process_alive(me.pid, me.create_time() - 100)  # reused-PID look-alike
    assert not process_alive(None, None)


def test_recover_ignores_live_jobs(ws: Workspace) -> None:
    q = LocalJobQueue(ws)
    jid = create_job(ws, "fake", "sub-001", params={"duration": 60})
    q.submit(jid)
    running_with_tool(ws, jid)
    assert recover_stale_jobs(ws) == []
    q.cancel(jid)
    assert q.wait(timeout=30)
    assert JobStatus.CANCELLED.value == status(ws, jid)


def test_new_queue_adopts_queued_jobs(ws: Workspace) -> None:
    """A restarted server picks up jobs that were Queued but never started."""
    jid = create_job(ws, "fake", "sub-001", params={"duration": 0.2})
    q = LocalJobQueue(ws)  # a fresh queue that never saw submit()
    assert q.adopt_queued() == [jid]
    assert q.adopt_queued() == []  # not adopted twice
    q.tick()
    assert q.wait(timeout=30)
    assert status(ws, jid) == "Completed"


def test_live_worker_of_earlier_server_counts_against_limit(ws: Workspace) -> None:
    """Workers outlive the server; a new server must not oversubscribe the machine."""
    old = LocalJobQueue(ws, max_concurrency=1)
    first = create_job(ws, "fake", "sub-001", params={"duration": 60})
    old.submit(first)
    running_with_tool(ws, first)
    new = LocalJobQueue(ws, max_concurrency=1)  # "restarted server"
    second = create_job(ws, "fake", "sub-002", params={"duration": 0.2})
    new.submit(second)
    time.sleep(0.5)
    assert status(ws, second) == "Queued"
    old.cancel(first)
    wait_for(lambda: status(ws, first) == "Cancelled")
    new.tick()
    assert new.wait(timeout=30)
    assert status(ws, second) == "Completed"
