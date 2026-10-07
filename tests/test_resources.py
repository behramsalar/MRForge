"""Stage 7b: how much of the computer MRForge may use."""

import json
from pathlib import Path

import pytest
from test_batch import fake_spec, overlap

from mrforge import resources
from mrforge.batch import run_batch
from mrforge.models import Job
from mrforge.resources import ResourcePolicy, preset_policy
from mrforge.runner.local import LocalJobQueue
from mrforge.workspace import Workspace


def use_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **values: object) -> None:
    path = tmp_path / "test-config.json"
    path.write_text(
        json.dumps({"resources": ResourcePolicy(preset="custom", **values).model_dump()})
    )  # type: ignore[arg-type]
    monkeypatch.setenv("MRFORGE_CONFIG", str(path))


def test_presets_follow_the_size_of_the_machine() -> None:
    balanced = preset_policy("balanced", cores=8, ram_gb=16)
    assert (balanced.cpu_cap, balanced.threads_per_job, balanced.max_subjects) == (4, 2, 2)
    maximum = preset_policy("max", cores=8, ram_gb=16)
    assert (maximum.cpu_cap, maximum.max_subjects) == (8, 4)
    low = preset_policy("low", cores=8, ram_gb=16)
    assert (low.cpu_cap, low.threads_per_job, low.max_subjects) == (1, 1, 1)
    assert low.memory_reserve_gb > balanced.memory_reserve_gb > maximum.memory_reserve_gb
    small = preset_policy("balanced", cores=2, ram_gb=8)
    assert small.threads_per_job == 1 and small.max_subjects >= 1


def test_a_saved_policy_is_found_again(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MRFORGE_CONFIG", str(tmp_path / "config.json"))
    assert resources.load_policy().preset == "balanced"  # nothing saved yet
    resources.save_policy(
        ResourcePolicy(
            preset="custom", max_subjects=3, threads_per_job=1, cpu_cap=3, memory_reserve_gb=2.5
        )
    )
    again = resources.load_policy()
    assert (again.preset, again.max_subjects, again.cpu_cap, again.memory_reserve_gb) == (
        "custom",
        3,
        3,
        2.5,
    )


def test_every_job_is_told_how_many_threads_to_use() -> None:
    env = resources.thread_env(ResourcePolicy(threads_per_job=3))
    assert (
        env["OMP_NUM_THREADS"] == "3"
        and env["VECLIB_MAXIMUM_THREADS"] == "3"
        and env["OPENBLAS_NUM_THREADS"] == "3"
    )


def test_a_job_waits_when_the_cap_is_reached_or_memory_is_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = ResourcePolicy(cpu_cap=4, threads_per_job=2, memory_reserve_gb=4.0)
    monkeypatch.setattr(resources, "worker_count", lambda: 2)  # 2 jobs x 2 threads = the cap
    assert "limit" in (resources.why_not_now(policy) or "")
    monkeypatch.setattr(resources, "worker_count", lambda: 1)
    monkeypatch.setattr(
        resources.psutil,
        "virtual_memory",
        lambda: type("M", (), {"available": 2e9, "total": 16e9})(),
    )
    assert "memory" in (resources.why_not_now(policy) or "")
    monkeypatch.setattr(
        resources.psutil,
        "virtual_memory",
        lambda: type("M", (), {"available": 8e9, "total": 16e9})(),
    )
    assert resources.why_not_now(policy) is None


def test_the_cap_holds_even_when_many_subjects_run_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use_policy(
        monkeypatch, tmp_path, max_subjects=4, threads_per_job=1, cpu_cap=1, memory_reserve_gb=0
    )
    ws = Workspace.create(tmp_path / "ws")
    specs = [fake_spec(f"sub-{i:03d}", duration=0.8) for i in range(1, 4)]
    results = run_batch(ws, specs, max_subjects=3)  # three subjects asked for, one job allowed
    assert [r.status for r in results] == ["done"] * 3
    assert overlap(ws) == 1


def test_one_job_always_runs_but_more_wait_when_free_memory_is_short(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import time

    use_policy(
        monkeypatch, tmp_path, max_subjects=2, threads_per_job=1, cpu_cap=8, memory_reserve_gb=1e6
    )
    ws = Workspace.create(tmp_path / "ws")
    ws.get_or_create_subject("sub-001")
    from mrforge.runner.jobs import create_job

    first = create_job(ws, "fake", "sub-001", {}, {"duration": 3.0})
    second = create_job(
        ws, "fake", "sub-001", {"sources": []}, {"duration": 0.1, "content": "b"}, label="other"
    )
    queue = LocalJobQueue(ws)
    queue.submit(first)  # nothing runs yet: it starts although memory is "short"
    queue.submit(second)  # one is running: this one waits for memory
    time.sleep(1.0)
    with ws.session() as s:
        assert s.get(Job, first).status == "Running"  # type: ignore[union-attr]
        waiting = s.get(Job, second)
        assert waiting is not None and waiting.status == "Queued"
        assert waiting.error_message and "free memory" in waiting.error_message
    queue.cancel_all()


def test_a_waiting_step_says_why_in_the_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from datetime import UTC, datetime

    from test_batch import fake_spec

    from mrforge.models import Operation, PipelineRun
    from mrforge.progress import operation_progress

    ws = Workspace.create(tmp_path / "ws")
    spec = fake_spec("sub-001")
    sid = ws.get_or_create_subject("sub-001")
    with ws.session() as s:
        op = Operation(
            kind="pipeline",
            title="t",
            args={"spec": spec.model_dump(mode="json")},
            status="Running",
            started=datetime.now(UTC),
        )
        run = PipelineRun(
            name=spec.name, spec=spec.model_dump(mode="json"), created=datetime.now(UTC)
        )
        s.add_all([op, run])
        s.flush()
        s.add(Job(step_name="fake", step_version="1", subject_id=sid, param_hash="x", status="Queued", pipeline_run_id=run.id,
                  run_dir="derivatives/mrforge/sub-001/anat/_runs/work", label="work",
                  error_message="Waiting for free capacity: free memory (2.0 GB) is below the reserve (4 GB)."))  # fmt: skip
        s.flush()
        op_id = op.id
    with ws.session() as s:
        stored = s.get(Operation, op_id)
        assert stored is not None
        step = operation_progress(ws, stored).steps[0]
    assert step.state == "waiting" and "free capacity" in (step.now or "")


def test_a_running_job_really_gets_the_thread_limit_in_its_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Looks at the tool process of a real job (FakeStep runs a sleeping Python process)."""
    import time

    import psutil

    use_policy(
        monkeypatch, tmp_path, max_subjects=1, threads_per_job=3, cpu_cap=6, memory_reserve_gb=0
    )
    ws = Workspace.create(tmp_path / "ws")
    ws.get_or_create_subject("sub-001")
    from mrforge.runner.jobs import create_job

    job_id = create_job(ws, "fake", "sub-001", {}, {"duration": 4.0})
    queue = LocalJobQueue(ws)
    queue.submit(job_id)
    seen = None
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and seen is None:
        for proc in psutil.process_iter(["cmdline"]):
            try:
                if "time.sleep(" in " ".join(proc.info["cmdline"] or []):
                    seen = proc.environ().get("OMP_NUM_THREADS")
            except psutil.Error:
                continue
        time.sleep(0.2)
    queue.wait()
    assert seen == "3"
