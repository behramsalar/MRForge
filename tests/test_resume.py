"""Provenance, resume and downstream invalidation, with real worker processes."""

import json
import threading
import time
from pathlib import Path

import psutil
import pytest

from mrforge import hashing
from mrforge.engine import Action, run_pipeline, run_step
from mrforge.errors import StepError
from mrforge.pipeline import load_pipeline, parse_pipeline
from mrforge.provenance import read_provenance
from mrforge.resume import check_reusable
from mrforge.runner.jobs import get_job, list_jobs
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.fake import FakeStep
from mrforge.workspace import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


@pytest.fixture
def queue(ws: Workspace) -> LocalJobQueue:
    return LocalJobQueue(ws)


def out_dir(ws: Workspace, label: str = "fake", subject: str = "sub-001") -> Path:
    return ws.derivatives_dir / subject / label


def chain(c_params: dict[str, object] | None = None, a_params: dict[str, object] | None = None):
    return parse_pipeline(
        {
            "name": "chain",
            "subject": "sub-001",
            "steps": [
                {"id": "a", "step": "fake", "params": a_params or {}},
                {"id": "b", "step": "fake", "inputs": {"sources": ["${a.result}"]}},
                {
                    "id": "c",
                    "step": "fake",
                    "inputs": {"sources": ["${b.result}"]},
                    "params": c_params or {},
                },
            ],
        }
    )


def actions(outcomes) -> list[str]:  # type: ignore[no-untyped-def]
    return [o.action.value for o in outcomes]


# -- provenance ---------------------------------------------------------------


def test_provenance_records_everything(ws: Workspace, queue: LocalJobQueue) -> None:
    src = ws.root / "rawbids" / "in.txt"
    src.write_text("data")
    o = run_step(ws, queue, "fake", "sub-001", {"sources": ["rawbids/in.txt"]}, {"duration": 0.2})
    assert o.action == Action.RAN
    prov = read_provenance(out_dir(ws))
    assert prov is not None
    assert prov.status == "Completed" and prov.return_code == 0
    assert prov.step.name == "fake" and prov.step.version == "1"
    assert prov.parameters["duration"] == 0.2 and prov.parameter_hash.startswith("sha256:")
    assert [f.path for f in prov.inputs] == ["rawbids/in.txt"]
    assert prov.inputs[0].sha256 == hashing.sha256_of(src)
    assert [f.path for f in prov.outputs] == ["derivatives/mrforge/sub-001/fake/result.txt"]
    assert prov.commands and prov.commands[0].return_code == 0
    assert "mrforge" in prov.tool_versions
    assert prov.started and prov.finished and prov.job_id == o.job_id
    raw = json.loads((out_dir(ws) / "provenance.json").read_text())
    assert raw["schema_version"] == 1


def test_failed_run_still_has_provenance(ws: Workspace, queue: LocalJobQueue) -> None:
    o = run_step(ws, queue, "fake", "sub-001", params={"fail_at": "command"})
    assert o.action == Action.FAILED
    prov = read_provenance(out_dir(ws))
    assert prov and prov.status == "Failed" and prov.error_code == "COMMAND_FAILED"
    assert prov.commands[-1].return_code == 1 and prov.outputs == []


# -- resume rule ----------------------------------------------------------------


def test_unchanged_rerun_is_skipped(ws: Workspace, queue: LocalJobQueue) -> None:
    first = run_step(ws, queue, "fake", "sub-001")
    second = run_step(ws, queue, "fake", "sub-001")
    assert (first.action, second.action) == (Action.RAN, Action.REUSED)
    assert "already completed" in second.reason and second.job_id == first.job_id
    assert len(list_jobs(ws)) == 1


def test_parameter_change_reruns(ws: Workspace, queue: LocalJobQueue) -> None:
    run_step(ws, queue, "fake", "sub-001", params={"content": "a"})
    o = run_step(ws, queue, "fake", "sub-001", params={"content": "b"})
    assert o.action == Action.RAN and "settings changed" in o.reason


def test_input_change_reruns(ws: Workspace, queue: LocalJobQueue) -> None:
    src = ws.root / "rawbids" / "in.txt"
    src.write_text("one")
    inputs = {"sources": ["rawbids/in.txt"]}
    run_step(ws, queue, "fake", "sub-001", inputs)
    src.write_text("two")
    o = run_step(ws, queue, "fake", "sub-001", inputs)
    assert o.action == Action.RAN and "input data changed" in o.reason


def test_deleted_output_reruns(ws: Workspace, queue: LocalJobQueue) -> None:
    run_step(ws, queue, "fake", "sub-001")
    (out_dir(ws) / "result.txt").unlink()
    r = check_reusable(ws, "fake", "sub-001")
    assert not r.reusable and "missing or invalid" in r.reason
    assert run_step(ws, queue, "fake", "sub-001").action == Action.RAN
    assert (out_dir(ws) / "result.txt").is_file()


def test_modified_output_reruns(ws: Workspace, queue: LocalJobQueue) -> None:
    run_step(ws, queue, "fake", "sub-001")
    (out_dir(ws) / "result.txt").write_text("tampered\n")
    r = check_reusable(ws, "fake", "sub-001")
    assert not r.reusable and "modified" in r.reason


def test_step_version_bump_reruns(
    ws: Workspace, queue: LocalJobQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_step(ws, queue, "fake", "sub-001")
    monkeypatch.setattr(FakeStep, "version", "2")
    r = check_reusable(ws, "fake", "sub-001")
    assert not r.reusable and "updated" in r.reason


def test_old_success_is_not_trusted_after_a_failed_rerun(
    ws: Workspace, queue: LocalJobQueue
) -> None:
    run_step(ws, queue, "fake", "sub-001", params={"content": "ok"})
    assert run_step(ws, queue, "fake", "sub-001", params={"fail_at": "start"}).action == (
        Action.FAILED
    )
    r = check_reusable(ws, "fake", "sub-001", params={"content": "ok"})
    assert not r.reusable  # the earlier result was overwritten or invalidated by the failed run


def test_hash_cache_avoids_rehashing(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    f = ws.root / "rawbids" / "big.bin"
    f.write_text("abc")
    calls = []
    real = hashing.sha256_of
    monkeypatch.setattr(hashing, "sha256_of", lambda p: (calls.append(p), real(p))[1])
    h1 = hashing.file_sha256(ws, "rawbids/big.bin")
    h2 = hashing.file_sha256(ws, "rawbids/big.bin")
    assert h1 == h2 and len(calls) == 1
    time.sleep(0.01)
    f.write_text("abcd")
    assert hashing.file_sha256(ws, "rawbids/big.bin") != h1 and len(calls) == 2


# -- pipelines --------------------------------------------------------------------


def test_pipeline_failure_then_resume_skips_finished_steps(
    ws: Workspace, queue: LocalJobQueue
) -> None:
    first = run_pipeline(ws, queue, chain(c_params={"fail_at": "start"}))
    assert actions(first) == ["Ran", "Ran", "Failed"]
    again = run_pipeline(ws, queue, chain(c_params={}))  # c fixed
    assert actions(again) == ["Already completed", "Already completed", "Ran"]
    jobs = [j for j in list_jobs(ws)]
    assert sorted(j.label or "" for j in jobs) == ["a", "b", "c", "c"]  # a and b ran once


def test_pipeline_stops_at_failure(ws: Workspace, queue: LocalJobQueue) -> None:
    out = run_pipeline(ws, queue, chain(a_params={"fail_at": "start"}))
    assert actions(out) == ["Failed", "Not run", "Not run"]


def test_upstream_rerun_invalidates_downstream(ws: Workspace, queue: LocalJobQueue) -> None:
    run_pipeline(ws, queue, chain())
    # 'duration' does not change a's output bytes, but a does rerun, so b and c must too.
    out = run_pipeline(ws, queue, chain(a_params={"duration": 0.1}))
    assert actions(out) == ["Ran", "Ran", "Ran"]
    assert "step 'a' ran again" in out[1].reason


def test_resume_after_killed_tool_starts_at_interrupted_step(
    ws: Workspace, queue: LocalJobQueue
) -> None:
    spec = chain(c_params={"duration": 4})
    result: list[list] = []  # type: ignore[type-arg]
    thread = threading.Thread(target=lambda: result.append(run_pipeline(ws, queue, spec)))
    thread.start()
    deadline = time.monotonic() + 30
    killed = False
    while time.monotonic() < deadline and not killed:
        running = [j for j in list_jobs(ws) if j.status == "Running" and j.label == "c"]
        if running and running[0].pid:
            kids = psutil.Process(running[0].pid).children(recursive=True)
            if kids:
                kids[0].kill()
                killed = True
        time.sleep(0.05)
    thread.join(timeout=30)
    assert killed and actions(result[0]) == ["Ran", "Ran", "Failed"]
    last = [j for j in list_jobs(ws) if j.label == "c"][-1]
    assert get_job(ws, last.id).status == "Interrupted"

    resumed = run_pipeline(ws, queue, spec)
    assert actions(resumed) == ["Already completed", "Already completed", "Ran"]


# -- pipeline files ----------------------------------------------------------------


def test_pipeline_validation_errors() -> None:
    with pytest.raises(StepError, match="share the id"):
        parse_pipeline({"name": "x", "subject": "s", "steps": [{"id": "a", "step": "fake"}] * 2})
    with pytest.raises(StepError, match="no subject"):
        parse_pipeline({"name": "x", "steps": [{"id": "a", "step": "fake"}]})
    with pytest.raises(StepError, match="must be listed before"):
        parse_pipeline(
            {
                "name": "x",
                "subject": "s",
                "steps": [{"id": "a", "step": "fake", "inputs": {"sources": ["${b.result}"]}}],
            }
        )


def test_load_pipeline_from_yaml(tmp_path: Path) -> None:
    p = tmp_path / "p.yaml"
    p.write_text(
        "name: demo\nsubject: sub-001\nsteps:\n"
        "  - {id: a, step: fake}\n"
        "  - {id: b, step: fake, inputs: {sources: ['${a.result}']}}\n"
    )
    spec = load_pipeline(p)
    assert [s.id for s in spec.steps] == ["a", "b"]
    with pytest.raises(StepError, match="could not be read"):
        load_pipeline(tmp_path / "missing.yaml")
