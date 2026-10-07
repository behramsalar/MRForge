"""Stage 6f: ICA-AROMA as an optional way to label the components.

Unit tests need neither FSL nor ICA-AROMA. The real test (marked ``fsl``, ``slow`` and
``realdata``) uses the finished full-processing copy ``mri-test-data/full-art`` and compares the
step with ICA-AROMA run by hand with the same inputs."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_ica_labels import SUMMARY, N, make_workspace
from test_processing import workspace as processing_workspace

from mrforge.aroma_env import AromaInstall, find_aroma
from mrforge.engine import Action, run_pipeline
from mrforge.icalabels import aroma_path, read_proposal
from mrforge.pipeline import parse_pipeline
from mrforge.processing import ArtifactOptions, FullOptions, plan_full_processing
from mrforge.runner.local import LocalJobQueue
from mrforge.workspace import Workspace

FAKE = AromaInstall(Path("/tools/ICA_AROMA.py"), "v-test")


def write_aroma(ws: Workspace, motion: list[int], mixing_hash: str = "aaa") -> None:
    data = {
        "motion_components": motion,
        "n_components": N,
        "mixing_sha256": mixing_hash,
        "tool": "ICA-AROMA",
        "tool_version": "v-test",
    }
    ws.abspath(aroma_path(SUMMARY)).write_text(json.dumps(data))


def test_the_install_is_found_through_the_environment_variable(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    script = tmp_path / "ICA_AROMA.py"
    script.write_text("# fake")
    monkeypatch.setenv("MRFORGE_AROMA", str(script))
    found = find_aroma()
    assert found is not None and found.script == script
    monkeypatch.setenv("MRFORGE_AROMA", str(tmp_path / "missing.py"))
    monkeypatch.setattr("mrforge.aroma_env.PROJECT", tmp_path)  # no tools/ folder here
    monkeypatch.setenv("PATH", str(tmp_path))
    assert find_aroma() is None


def test_the_proposal_labels_motion_components_as_noise_and_the_rest_as_signal(
    tmp_path: Path,
) -> None:
    ws = make_workspace(tmp_path)
    write_aroma(ws, [2, 4])
    assert read_proposal(ws, SUMMARY) == {"1": "signal", "2": "noise", "3": "signal", "4": "noise"}


def test_a_proposal_for_other_components_is_not_offered(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_aroma(ws, [2], mixing_hash="other")
    assert read_proposal(ws, SUMMARY) is None


def aroma_spec(mode: str) -> object:
    return parse_pipeline(
        {
            "name": "p",
            "subject": "sub-001",
            "steps": [
                {
                    "id": "labels",
                    "step": "ica_labels",
                    "inputs": {"melodic_summary": SUMMARY, "aroma": aroma_path(SUMMARY)},
                    "params": {"mode": mode},
                },
                {"id": "after", "step": "fake", "inputs": {"sources": ["${labels.labels}"]}},
            ],
        }
    )


def test_automatic_mode_uses_the_classification_without_waiting(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_aroma(ws, [1, 3])
    outcomes = {
        o.step_id: o.action for o in run_pipeline(ws, LocalJobQueue(ws), aroma_spec("aroma"))
    }  # type: ignore[arg-type]
    assert outcomes == {"labels": Action.RAN, "after": Action.RAN}
    result = json.loads(
        next((ws.root / "derivatives/mrforge/sub-001/func").glob("*_labels.json")).read_text()
    )
    assert result["noise_components"] == [1, 3] and result["source"] == "aroma"
    assert "ICA-AROMA" in result["decided_by"] and "automatic" in result["decided_by"]


def test_automatic_mode_refuses_a_classification_of_other_components(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_aroma(ws, [1], mixing_hash="other")
    outcomes = {
        o.step_id: o.action for o in run_pipeline(ws, LocalJobQueue(ws), aroma_spec("aroma"))
    }  # type: ignore[arg-type]
    assert outcomes["labels"] == Action.FAILED and outcomes["after"] == Action.NOT_RUN


def plan_with(tmp_path: Path, mode: str):  # type: ignore[no-untyped-def]
    ws = processing_workspace(tmp_path, volumes=45)
    opts = FullOptions(
        subject="sub-001", stages={"artifact_rejection": True}, artifact=ArtifactOptions(mode=mode)
    )  # type: ignore[arg-type]
    return plan_full_processing(ws, opts)


def steps_of(spec) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        s.step
        for s in spec.steps
        if s.step in ("melodic", "aroma_classify", "ica_labels", "regfilt")
    ]


def test_aroma_modes_add_the_classification_step_before_the_labelling(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("mrforge.processing.find_aroma", lambda: FAKE)
    _, manual = plan_with(tmp_path / "a", "manual")
    assert steps_of(manual) == ["melodic", "ica_labels", "regfilt"]
    _, review = plan_with(tmp_path / "b", "aroma_review")
    assert steps_of(review) == ["melodic", "aroma_classify", "ica_labels", "regfilt"]
    by = {s.id: s for s in review.steps}
    assert by["ica_labels__task-rest"].params["mode"] == "manual"  # you still confirm
    assert "decision" in by["ica_labels__task-rest"].inputs
    p, auto = plan_with(tmp_path / "c", "aroma_auto")
    labels = {s.id: s for s in auto.steps}["ica_labels__task-rest"]
    assert (
        labels.params["mode"] == "aroma"
        and labels.inputs["aroma"] == "${aroma_classify__task-rest.classification}"
    )
    parse_pipeline(auto.model_dump(mode="json"))  # references point at earlier steps
    stage = next(s for s in p.stages if s.id == "artifact_rejection")
    assert "no pause" in stage.items[0].settings[1].value


def test_without_an_install_the_aroma_modes_explain_why(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("mrforge.processing.find_aroma", lambda: None)
    p, spec = plan_with(tmp_path, "aroma_auto")
    stage = next(s for s in p.stages if s.id == "artifact_rejection")
    assert not stage.can_run and stage.reason and "install_aroma" in stage.reason
    assert "aroma_classify" not in steps_of(spec)
    manual, _ = plan_with(tmp_path / "m", "manual")
    assert next(s for s in manual.stages if s.id == "artifact_rejection").can_run


FULL = Path("~/Documents/mri-test-data/full-art").expanduser()


@pytest.mark.fsl
@pytest.mark.slow
@pytest.mark.realdata
@pytest.mark.skipif(
    find_aroma() is None or not FULL.is_dir(), reason="needs ICA-AROMA and the full-art copy"
)
def test_the_step_gives_the_same_classification_as_aroma_run_by_hand(tmp_path: Path) -> None:
    from mrforge.fsl_env import find_fsl

    ws = Workspace.open(FULL)
    f = "derivatives/mrforge/sub-ali/func/sub-ali_task-rest"
    a = "derivatives/mrforge/sub-ali/anat/sub-ali"
    summary = f"{f}_desc-melodic_components.json"
    inputs = {
        "melodic_summary": summary,
        "bold": f"{f}_desc-preproc_bold.nii.gz",
        "motion": f"{f}_desc-motion_timeseries.tsv",
        "to_t1_affine": f"{f}_from-boldref_to-T1w_mode-image_desc-affine_xfm.mat",
        "t1_to_mni_warp": f"{a}_from-T1w_to-MNI152NLin6Asym_mode-image_desc-fnirtcoeff_xfm.nii.gz",
        "brain_mask": f"{f}_desc-brain_mask.nii.gz",
    }
    # Work on a copy of the record so the finished example is not disturbed.
    from mrforge.engine import run_step

    result = run_step(ws, LocalJobQueue(ws), "aroma_classify", "sub-ali", inputs, {})
    assert result.action in (Action.RAN, Action.REUSED), result.reason
    ours = json.loads((ws.root / aroma_path(summary)).read_text())["motion_components"]

    aroma = find_aroma()
    assert aroma is not None
    rows = (ws.root / inputs["motion"]).read_text().splitlines()[1:]
    par = tmp_path / "mc.par"
    par.write_text("\n".join(" ".join(r.split()) for r in rows) + "\n")
    melodic_dir = json.loads((ws.root / summary).read_text())["melodic_folder"]
    out = tmp_path / "manual"
    subprocess.run(
        [sys.executable, str(aroma.script), "-o", str(out), "-i", str(ws.root / inputs["bold"]),
         "-mc", str(par), "-a", str(ws.root / inputs["to_t1_affine"]),
         "-w", str(ws.root / inputs["t1_to_mni_warp"]), "-m", str(ws.root / inputs["brain_mask"]),
         "-md", str(ws.root / melodic_dir), "-tr", "2", "-den", "no", "-np"],
        check=True, capture_output=True, env=find_fsl().env,
    )  # fmt: skip
    manual = [int(v) for v in (out / "classified_motion_ICs.txt").read_text().strip().split(",")]
    assert ours == manual
