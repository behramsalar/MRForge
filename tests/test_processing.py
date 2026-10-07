"""Full processing: the stages are planned from one place and become one pipeline."""

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from mrforge.api.app import create_app
from mrforge.functional import ANAT_FILES
from mrforge.models import File
from mrforge.pipeline import PipelineSpec, parse_pipeline
from mrforge.processing import (
    STAGES,
    FullOptions,
    FunctionalOptions,
    plan_full_processing,
    recording_slug,
)
from mrforge.runner.jobs import build_context
from mrforge.steps import builtin  # noqa: F401
from mrforge.workspace import Workspace

T1 = "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
BOLD = "rawbids/sub-001/func/sub-001_task-rest_bold.nii.gz"
BOLD2 = "rawbids/sub-001/func/sub-001_task-other_run-2_bold.nii.gz"
FACTS = {
    "RepetitionTime": 2.0,
    "EchoTime": 0.03,
    "PhaseEncodingDirection": "j-",
    "EffectiveEchoSpacing": 0.0003,
}


def image(path: Path, shape: tuple[int, ...] = (4, 4, 4)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.ones(shape, dtype="float32"), np.eye(4)), path)


def workspace(
    tmp_path: Path,
    *,
    t1: bool = True,
    runs: tuple[str, ...] = (BOLD,),
    fieldmap: bool = True,
    anat_done: bool = False,
    volumes: int = 8,
) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    sid = ws.get_or_create_subject("sub-001")
    with ws.session() as s:
        if t1:
            image(ws.root / T1)
            s.add(File(subject_id=sid, relpath=T1, kind="T1w"))
        for run in runs:
            image(ws.root / run, (4, 4, 4, volumes))
            (ws.root / run.replace(".nii.gz", ".json")).write_text(json.dumps(FACTS))
            s.add(File(subject_id=sid, relpath=run, kind="bold"))
    if fieldmap and runs:
        for name in ("magnitude1", "magnitude2", "phasediff"):
            image(ws.root / f"rawbids/sub-001/fmap/sub-001_{name}.nii.gz")
        side = {
            "EchoTime1": 0.00492,
            "EchoTime2": 0.00738,
            "IntendedFor": [f"func/{Path(r).name}" for r in runs],
        }
        (ws.root / "rawbids/sub-001/fmap/sub-001_phasediff.json").write_text(json.dumps(side))
    if anat_done:
        for ending in ANAT_FILES.values():
            image(ws.derivatives_dir / "sub-001" / "anat" / f"sub-001{ending}")
    return ws


def plan(ws: Workspace, **kw: object):  # type: ignore[no-untyped-def]
    return plan_full_processing(ws, FullOptions(subject="sub-001", **kw))  # type: ignore[arg-type]


def ids(spec: PipelineSpec | None) -> list[str]:
    assert spec is not None
    return [s.id for s in spec.steps]


def test_the_standard_stages_in_order() -> None:
    assert [s.id for s in STAGES] == [
        "anatomical",
        "functional",
        "artifact_rejection",
        "standard_space",
    ]


def test_default_plan_covers_everything_and_is_a_valid_pipeline(tmp_path: Path) -> None:
    p, spec = plan(workspace(tmp_path))
    assert p.can_start and p.steps == 5
    assert [(s.id, s.enabled, s.can_run) for s in p.stages] == [
        ("anatomical", True, True),
        ("functional", True, True),
        ("artifact_rejection", False, False),  # off by default; this 8-volume run is too short
        ("standard_space", True, True),
    ]
    assert ids(spec)[0] == "fsl_anat" and ids(spec)[-1].startswith("func_to_mni__")
    parse_pipeline(spec.model_dump(mode="json"))  # references only point at earlier steps
    assert [s.step for s in spec.steps] == [
        "fsl_anat", "fieldmap_prep", "feat_preproc", "func_qc", "func_to_mni",
    ]  # fmt: skip


def test_steps_keep_clean_labels_so_result_names_stay_tidy(tmp_path: Path) -> None:
    _, spec = plan(workspace(tmp_path))
    assert spec is not None and all(s.label in (None, s.step) for s in spec.steps)
    run_steps = {s.step: s for s in spec.steps}
    assert run_steps["feat_preproc"].label == "feat_preproc"


def test_functional_results_use_the_new_anatomical_results_by_reference(tmp_path: Path) -> None:
    _, spec = plan(workspace(tmp_path))
    assert spec is not None
    feat = next(s for s in spec.steps if s.step == "feat_preproc")
    assert feat.inputs["t1_head"] == "${fsl_anat.biascorr}"
    mni = next(s for s in spec.steps if s.step == "func_to_mni")
    assert mni.inputs["t1_to_mni_warp"] == "${fsl_anat.to_mni_warp}"
    assert mni.inputs["bold"].startswith("${feat_preproc__")  # the data the previous stage made


def test_two_recordings_get_separate_steps_and_records(tmp_path: Path) -> None:
    ws = workspace(tmp_path, runs=(BOLD, BOLD2))
    p, spec = plan(ws)
    assert spec is not None
    assert sum(1 for s in spec.steps if s.step == "fieldmap_prep") == 1  # shared, made once
    assert sum(1 for s in spec.steps if s.step == "feat_preproc") == 2
    assert len({s.id for s in spec.steps}) == len(spec.steps)
    parse_pipeline(spec.model_dump(mode="json"))
    folders = set()
    for s in spec.steps:
        if s.step == "feat_preproc":
            _, ctx = build_context(
                ws, s.step, "sub-001", None, {"bold": s.inputs["bold"]}, {}, s.label
            )
            folders.add(ctx.run_dir.name)
    assert folders == {"feat_preproc_task-rest", "feat_preproc_task-other_run-2"}
    titles = [i.title for i in p.stages[1].items]
    assert any(t.startswith("Run task-other run-2") for t in titles) and len(titles) == 2


def test_existing_anatomical_results_can_be_used_instead_of_running_again(tmp_path: Path) -> None:
    ws = workspace(tmp_path, anat_done=True)
    p, spec = plan(ws, stages={"anatomical": False})
    assert spec is not None and "fsl_anat" not in ids(spec)
    feat = next(s for s in spec.steps if s.step == "feat_preproc")
    assert feat.inputs["t1_head"].endswith("_desc-biascorr_T1w.nii.gz")  # the earlier file
    assert not p.stages[0].enabled and p.stages[0].can_run


def test_earlier_results_without_a_record_are_made_again_and_the_user_is_told(
    tmp_path: Path,
) -> None:
    p, spec = plan(workspace(tmp_path, anat_done=True))  # files exist, but MRForge has no record
    anatomical = p.stages[0]
    assert not anatomical.already_done
    assert anatomical.items[0].note and "made again" in anatomical.items[0].note
    assert spec is not None and ids(spec)[0] == "fsl_anat"


def test_missing_anatomical_results_block_the_functional_stage(tmp_path: Path) -> None:
    p, spec = plan(workspace(tmp_path), stages={"anatomical": False})
    functional = p.stages[1]
    assert not functional.can_run and "Anatomical" in (functional.reason or "")
    assert spec is None or not any(s.step == "feat_preproc" for s in spec.steps)


def test_no_t1_is_explained(tmp_path: Path) -> None:
    p, _ = plan(workspace(tmp_path, t1=False))
    assert not p.stages[0].can_run and "no T1" in (p.stages[0].reason or "")
    assert not p.can_start


def test_no_functional_run_is_explained_and_anatomical_still_runs(tmp_path: Path) -> None:
    p, spec = plan(workspace(tmp_path, runs=()))
    assert not p.stages[1].can_run and "no functional run" in (p.stages[1].reason or "")
    assert ids(spec) == ["fsl_anat"] and p.can_start


def test_a_run_without_fieldmap_goes_ahead_without_distortion_correction(tmp_path: Path) -> None:
    p, spec = plan(workspace(tmp_path, fieldmap=False))
    item = p.stages[1].items[0]
    assert item.note and "No distortion correction" in item.note
    assert {s.name: s.value for s in item.settings}["Distortion correction"] == "no"
    assert spec is not None and "fieldmap_prep" not in [s.step for s in spec.steps]


def test_settings_chosen_in_the_dialog_end_up_in_the_steps(tmp_path: Path) -> None:
    opts = FunctionalOptions(delete_volumes=3, smoothing_fwhm_mm=6.0, highpass_cutoff_s=None)
    p, spec = plan(workspace(tmp_path), functional=opts)
    assert spec is not None
    feat = next(s for s in spec.steps if s.step == "feat_preproc")
    assert feat.params["delete_volumes"] == 3 and feat.params["highpass_cutoff_s"] is None
    shown = {s.name: s.value for s in p.stages[1].items[0].settings}
    assert shown["Volumes discarded"] == "3" and shown["Slow-drift filter"] == "off"
    assert shown["Smoothing"] == "6 mm"


def test_standard_space_needs_the_functional_stage(tmp_path: Path) -> None:
    p, spec = plan(workspace(tmp_path), stages={"functional": False})
    assert not p.stages[3].can_run
    assert spec is not None and [s.step for s in spec.steps] == ["fsl_anat"]
    p2, spec2 = plan(workspace(tmp_path / "b"), stages={"standard_space": False})
    assert spec2 is not None and "func_to_mni" not in [s.step for s in spec2.steps]
    assert p2.stages[3].enabled is False


def test_everything_switched_off_cannot_start(tmp_path: Path) -> None:
    p, spec = plan(
        workspace(tmp_path),
        stages={"anatomical": False, "functional": False, "standard_space": False},
    )
    assert not p.can_start and spec is None


def test_recording_names_for_step_ids() -> None:
    assert (
        recording_slug("rawbids/sub-001/func/sub-001_task-rest_run-1_bold.nii.gz")
        == "task-rest_run-1"
    )
    assert recording_slug("x/sub-001_bold.nii.gz") == "bold"


# -- API and the engine ---------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path))
    return TestClient(create_app(tmp_path / "workspaces"))


def test_the_plan_route_and_a_refusal_when_nothing_can_run(client: TestClient) -> None:
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    plan_body = client.post(
        f"/api/workspaces/{ws_id}/process/plan", json={"subject": "sub-001"}
    ).json()
    assert plan_body["can_start"] is False
    assert [s["id"] for s in plan_body["stages"]] == [
        "anatomical",
        "functional",
        "artifact_rejection",
        "standard_space",
    ]
    refused = client.post(f"/api/workspaces/{ws_id}/process", json={"subject": "sub-001"})
    assert refused.status_code == 400 and refused.json()["code"] == "NOTHING_TO_RUN"
    assert client.post(
        f"/api/workspaces/{ws_id}/process/plan", json={"subject": "../x"}
    ).status_code in (400, 404)


def test_pipeline_steps_can_share_a_label(tmp_path: Path) -> None:
    from mrforge.engine import run_pipeline
    from mrforge.runner.jobs import list_jobs
    from mrforge.runner.local import LocalJobQueue

    ws = Workspace.create(tmp_path / "ws")
    spec = parse_pipeline(
        {
            "name": "labels",
            "subject": "sub-001",
            "steps": [
                {"id": "one__a", "label": "fake", "step": "fake", "params": {"duration": 0.1}}
            ],
        }
    )
    run_pipeline(ws, LocalJobQueue(ws), spec)
    [job] = list_jobs(ws)
    assert job.label == "fake" and job.run_dir is not None and job.run_dir.endswith("_runs/fake")


def test_discarding_more_volumes_than_a_run_has_is_explained_not_rejected(tmp_path: Path) -> None:
    p, spec = plan(workspace(tmp_path), functional=FunctionalOptions(delete_volumes=5000))
    func = p.stages[1]
    assert not func.can_run and func.reason and "too few" in func.reason
    assert spec is None or "feat_preproc" not in [s.step for s in spec.steps]


def test_a_rejected_value_comes_back_as_a_plain_error(client: TestClient) -> None:
    r = client.post(
        "/api/workspaces/x/process/plan",
        json={"subject": "s", "functional": {"delete_volumes": -1}},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "INVALID_VALUE" and "delete volumes" in body["message"]


def artifact_plan(tmp_path: Path, **kw: object):  # type: ignore[no-untyped-def]
    ws = workspace(tmp_path, volumes=45)
    stages = {"artifact_rejection": True}
    return ws, plan(ws, stages=stages, **kw)


def test_artifact_rejection_is_off_unless_chosen(tmp_path: Path) -> None:
    p, spec = plan(workspace(tmp_path, volumes=45))
    stage = next(s for s in p.stages if s.id == "artifact_rejection")
    assert not stage.enabled and stage.can_run
    assert not any(s.step in ("melodic", "ica_labels", "regfilt") for s in spec.steps)  # type: ignore[union-attr]


def test_the_artifact_stage_sits_between_functional_and_standard_space(tmp_path: Path) -> None:
    _, (p, spec) = artifact_plan(tmp_path)
    assert [s.step for s in spec.steps] == [  # type: ignore[union-attr]
        "fsl_anat", "fieldmap_prep", "feat_preproc", "func_qc",
        "melodic", "ica_labels", "regfilt", "func_to_mni",
    ]  # fmt: skip
    parse_pipeline(spec.model_dump(mode="json"))  # type: ignore[union-attr]
    assert "Labelling" in {
        s.name for s in next(s for s in p.stages if s.id == "artifact_rejection").items[0].settings
    }


def test_standard_space_uses_the_cleaned_data(tmp_path: Path) -> None:
    _, (_, spec) = artifact_plan(tmp_path)
    mni = next(s for s in spec.steps if s.step == "func_to_mni")  # type: ignore[union-attr]
    assert mni.inputs["bold"] == "${regfilt__task-rest.cleaned_bold}"
    # Without the stage it still takes the FEAT result.
    _, spec2 = plan(workspace(tmp_path / "plain", volumes=45))
    mni2 = next(s for s in spec2.steps if s.step == "func_to_mni")  # type: ignore[union-attr]
    assert mni2.inputs["bold"] == "${feat_preproc__task-rest.preproc_bold}"


def test_the_steps_are_wired_to_each_others_results(tmp_path: Path) -> None:
    _, (_, spec) = artifact_plan(tmp_path)
    by = {s.id: s for s in spec.steps}  # type: ignore[union-attr]
    mel = by["melodic__task-rest"]
    assert mel.inputs["bold"] == "${feat_preproc__task-rest.preproc_bold}"
    assert mel.inputs["to_t1_affine"] == "${feat_preproc__task-rest.to_t1_affine}"
    assert mel.inputs["t1_brain"] == "${fsl_anat.brain}"
    assert by["ica_labels__task-rest"].inputs["melodic_summary"] == "${melodic__task-rest.summary}"
    reg = by["regfilt__task-rest"]
    assert reg.inputs["mixing"] == "${melodic__task-rest.mixing}"
    assert reg.inputs["labels"] == "${ica_labels__task-rest.labels}"


def test_the_decision_file_is_where_the_real_step_will_put_its_result(tmp_path: Path) -> None:
    """The plan names the decision file before MELODIC has run, from the raw file's name; it
    must be the place next to the real summary the step will write."""
    ws, (_, spec) = artifact_plan(tmp_path)
    labels = next(s for s in spec.steps if s.step == "ica_labels")  # type: ignore[union-attr]
    feat_bold = "derivatives/mrforge/sub-001/func/sub-001_task-rest_desc-preproc_bold.nii.gz"
    step, ctx = build_context(
        ws, "melodic", "sub-001", None, {"bold": feat_bold, "brain_mask": feat_bold}, {}, "melodic"
    )
    real = ws.relpath(ctx.output_dir / step.expected_outputs(ctx).summary)
    assert labels.inputs["decision"] == real.replace(
        "_desc-melodic_components.json", "_desc-icalabels_decision.json"
    )


def test_a_run_too_short_for_component_analysis_is_explained(tmp_path: Path) -> None:
    p, spec = plan(workspace(tmp_path, volumes=20), stages={"artifact_rejection": True})
    stage = next(s for s in p.stages if s.id == "artifact_rejection")
    assert not stage.can_run and stage.reason and "at least" in stage.reason
    assert not any(s.step == "melodic" for s in spec.steps)  # type: ignore[union-attr]


def test_artifact_settings_reach_the_steps(tmp_path: Path) -> None:
    from mrforge.processing import ArtifactOptions

    _, (_, spec) = artifact_plan(
        tmp_path, artifact=ArtifactOptions(uncertain_as="noise", aggressive=True)
    )
    by = {s.id: s for s in spec.steps}  # type: ignore[union-attr]
    assert by["ica_labels__task-rest"].params == {"uncertain_as": "noise", "mode": "manual"}
    assert by["regfilt__task-rest"].params == {"aggressive": True}


def test_every_recording_is_analysed_before_the_first_pause(tmp_path: Path) -> None:
    ws = workspace(tmp_path, runs=(BOLD, BOLD2), volumes=45)
    _, spec = plan(ws, stages={"artifact_rejection": True})
    order = [s.id for s in spec.steps if s.step in ("melodic", "ica_labels", "regfilt")]  # type: ignore[union-attr]
    runs = [i.removeprefix("melodic__") for i in order if i.startswith("melodic__")]
    assert len(runs) == 2
    first, second = runs
    assert order == [
        f"melodic__{first}", f"melodic__{second}",
        f"ica_labels__{first}", f"ica_labels__{second}",
        f"regfilt__{first}", f"regfilt__{second}",
    ]  # fmt: skip
