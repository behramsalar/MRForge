"""Stage 8a: the subject report is built only from what was recorded."""

from pathlib import Path

import pytest

from mrforge import qc_decisions
from mrforge.engine import run_step
from mrforge.provenance import read_provenance, write_provenance
from mrforge.report import build_report
from mrforge.runner.jobs import list_jobs
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.base import QCItem
from mrforge.workspace import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def run_fake(ws: Workspace, **params: object) -> Path:
    run_step(ws, LocalJobQueue(ws), "fake", "sub-001", params=params)
    job = next(j for j in list_jobs(ws) if j.step_name == "fake")
    return ws.abspath(job.run_dir or "")


def test_every_number_in_the_report_is_the_recorded_one(ws: Workspace) -> None:
    run_dir = run_fake(ws, content="hello")
    prov = read_provenance(run_dir)
    assert prov is not None
    prov.qc = [QCItem(name="Mean FD", kind="metric", value=0.123, warning="check motion")]
    write_provenance(run_dir, prov)
    report = build_report(ws, "sub-001")
    run = next(r for s in report.sections for r in s.runs)
    assert run.parameters == prov.parameters
    assert run.step_version == prov.step.version
    assert run.commands == [] or run.commands[0].return_code == prov.commands[0].return_code
    assert (run.qc[0].name, run.qc[0].value) == ("Mean FD", "0.123")
    assert "check motion" in report.warnings[0]
    assert report.software["MRForge"] == report.mrforge_version


def test_steps_that_never_ran_are_listed_as_not_run(ws: Workspace) -> None:
    run_fake(ws)
    report = build_report(ws, "sub-001")
    by_id = {s.id: s for s in report.sections}
    assert by_id["functional"].runs == []
    assert "Head motion and registration" in by_id["functional"].not_run
    assert by_id["other"].runs  # the fake step is not in any named section


def test_a_run_whose_results_are_gone_is_not_reported(ws: Workspace) -> None:
    run_dir = run_fake(ws)
    prov = read_provenance(run_dir)
    assert prov is not None
    ws.abspath(prov.outputs[0].path).unlink()
    report = build_report(ws, "sub-001")
    assert all(not s.runs for s in report.sections)


def test_the_quality_decision_history_is_in_the_report_with_its_reason(ws: Workspace) -> None:
    run_fake(ws)
    qc_decisions.record(ws, "sub-001", "review", "look again", "Jane", {"mean_fd": 0.4})
    qc_decisions.record(ws, "sub-001", "exclude", "too much motion", "Jane")
    report = build_report(ws, "sub-001")
    assert [d.decision for d in report.decisions] == ["review", "exclude"]
    assert report.decisions[1].reason == "too much motion"
    assert report.decisions[0].motion == {"mean_fd": 0.4}


def test_acquisition_lists_only_what_was_imported_into_the_data_folder(ws: Workspace) -> None:
    from mrforge.importing.manifest import save_manifest
    from mrforge.importing.models import (
        DicomSeries,
        ImportManifest,
        OrganizedSeries,
        SourceInfo,
    )

    ws.get_or_create_subject("sub-001")
    t1 = DicomSeries(
        uid="1.1", number=5, description="sT1W_3D_TFE", modality="MR", rows=256, columns=256,
        slices=190, volumes=1, repetition_time_s=0.0067, echo_time_s=0.003, n_files=190,
    )  # fmt: skip
    other = DicomSeries(uid="1.2", number=6, description="scout", modality="MR", n_files=3)
    manifest = ImportManifest(
        id="import-001",
        source=SourceInfo(name="x", kind="folder", n_files=193, fingerprint="f"),
        subject="sub-001",
        series=[t1, other],
        organized={"1.1": OrganizedSeries(files={"rawbids/a.nii.gz": "00"})},
    )
    save_manifest(ws, manifest)
    rows = build_report(ws, "sub-001").acquisition
    assert [(r.number, r.matrix, r.echo_time_s) for r in rows] == [(5, "256x256x190", 0.003)]
