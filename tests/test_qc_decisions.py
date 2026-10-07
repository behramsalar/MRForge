"""Stage 7c: the researcher's quality decision, the head-motion flag, and what exclusion changes."""

import json
from pathlib import Path

import pytest
from test_analysis_ready import processed
from test_overview import add_job, anat_done, subject, workspace

from mrforge import qc_decisions
from mrforge.analysis_ready import FOLDER, refresh
from mrforge.errors import StepError
from mrforge.overview import build_overview
from mrforge.qc_decisions import MotionThresholds, motion_flag


def test_a_decision_needs_a_reason(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    with pytest.raises(StepError) as err:
        qc_decisions.record(ws, "sub-001", "exclude", "   ", "Jane")
    assert err.value.code == "REASON_REQUIRED" and err.value.suggested_action


def test_history_is_kept_and_the_newest_decision_counts(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    qc_decisions.record(ws, "sub-001", "review", "motion looks high", "Jane", {"fd_mean_mm": 0.41})
    qc_decisions.record(ws, "sub-001", "accept", "checked the plots, fine", "Ali")
    entries = qc_decisions.history(ws, "sub-001")
    assert [e.decision for e in entries] == ["review", "accept"]
    assert entries[0].motion == {"fd_mean_mm": 0.41} and entries[1].who == "Ali"
    current = qc_decisions.current(ws, "sub-001")
    assert current is not None and current.reason == "checked the plots, fine"


def test_decisions_survive_reopening_the_workspace(tmp_path: Path) -> None:
    from mrforge.workspace import Workspace

    ws = workspace(tmp_path)
    qc_decisions.record(ws, "sub-001", "exclude", "scanner artefact", "Jane")
    again = Workspace.open(ws.root)  # like restarting the program
    current = qc_decisions.current(again, "sub-001")
    assert (
        current is not None
        and current.decision == "exclude"
        and current.reason == "scanner artefact"
    )


def test_the_motion_flag_names_the_reason_and_decides_nothing() -> None:
    t = MotionThresholds(mean_fd_mm=0.3, fraction_above=0.2)
    assert motion_flag(0.12, 3, 355, 0.5, t) is None
    assert "mean FD 0.41" in (motion_flag(0.41, 3, 355, 0.5, t) or "")
    assert "25% of volumes above 0.5 mm" in (motion_flag(0.1, 89, 355, 0.5, t) or "")
    both = motion_flag(0.5, 200, 355, 0.5, t) or ""
    assert "mean FD" in both and "volumes" in both


def test_the_thresholds_can_be_changed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MRFORGE_CONFIG", str(tmp_path / "config.json"))
    assert qc_decisions.load_thresholds().mean_fd_mm == 0.3
    qc_decisions.save_thresholds(MotionThresholds(mean_fd_mm=0.2, fraction_above=0.1))
    assert motion_flag(0.25, 0, 100, 0.5) is not None  # now flagged under the stricter rule


def write_metrics(ws, mean: float, above: int) -> None:  # type: ignore[no-untyped-def]
    folder = ws.derivatives_dir / "sub-001" / "func"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sub-001_task-rest_desc-metrics_qc.json").write_text(
        json.dumps(
            {
                "fd_mean_mm": mean,
                "fd_median_mm": mean,
                "fd_max_mm": 1.0,
                "fd_above_threshold": above,
                "n_volumes": 100,
                "fd_threshold_mm": 0.5,
            }
        )  # fmt: skip
    )


def test_a_high_motion_subject_is_flagged_but_not_excluded(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    anat_done(ws)
    write_metrics(ws, mean=0.6, above=40)
    row = subject(ws)
    assert row.motion_flag and "check motion" in row.motion_flag
    assert (
        row.qc_decision is None and not row.needs_review
    )  # nothing was decided for the researcher


def test_the_overview_counts_failed_review_and_excluded(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    ws.get_or_create_subject("sub-002")
    ws.get_or_create_subject("sub-003")
    qc_decisions.record(ws, "sub-001", "review", "look again", None)
    qc_decisions.record(ws, "sub-002", "exclude", "bad scan", "Jane")
    add_job(ws, "fsl_anat", "Failed")  # belongs to sub-001
    o = build_overview(ws)
    assert (o.needs_review, o.excluded, o.failed) == (1, 1, 1)
    rows = {r.label: r for r in o.subjects}
    assert rows["sub-002"].qc_reason == "bad scan" and rows["sub-001"].needs_review


def test_an_excluded_subject_leaves_the_analysis_ready_folder_and_is_listed_with_its_reason(
    tmp_path: Path,
) -> None:
    from mrforge.workspace import Workspace

    ws = Workspace.create(tmp_path / "ws")
    processed(ws, "sub-001")
    processed(ws, "sub-002")
    qc_decisions.record(ws, "sub-002", "exclude", "too much motion", "Jane")
    report = refresh(ws)
    by = {r.subject: r for r in report.rows}
    assert by["sub-001"].file and not by["sub-001"].excluded
    assert (
        by["sub-002"].excluded
        and by["sub-002"].file == ""
        and by["sub-002"].qc_reason == "too much motion"
    )
    assert not any("sub-002" in p.name for p in (ws.derivatives_dir / FOLDER).glob("*.nii.gz"))
    text = (ws.derivatives_dir / FOLDER / "analysis-ready.tsv").read_text()
    assert "excluded" in text and "too much motion" in text
    # Changing the decision brings the subject back.
    qc_decisions.record(ws, "sub-002", "accept", "re-checked, fine", "Jane")
    assert all(not r.excluded for r in refresh(ws).rows)


def test_an_excluded_subject_is_not_part_of_the_settings_comparison(tmp_path: Path) -> None:
    from mrforge.workspace import Workspace

    ws = Workspace.create(tmp_path / "ws")
    processed(ws, "sub-001", smoothing=5.0)
    processed(ws, "sub-002", smoothing=6.0)
    assert refresh(ws).differences  # different smoothing
    qc_decisions.record(ws, "sub-002", "exclude", "bad", None)
    assert refresh(ws).differences == []
