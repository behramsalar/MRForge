"""The connectivity stage: what it plans, and the pipeline it turns into (no FSL needed)."""

from pathlib import Path

import pytest
from test_processing import BOLD, BOLD2, make_earlier_results, only, plan, workspace

from mrforge.connectivity import ConnectivityOptions
from mrforge.pipeline import parse_pipeline
from mrforge.processing import STAGES
from mrforge.results import _outputs, existing_cleaned, existing_standard
from mrforge.workspace import Workspace


def conn(p):  # type: ignore[no-untyped-def]
    return next(s for s in p.stages if s.id == "connectivity")


def with_connectivity(**options: object) -> dict[str, object]:
    return {
        "stages": {"connectivity": True},
        "connectivity": ConnectivityOptions(**options),  # type: ignore[arg-type]
    }


def make_standard_results(ws: Workspace, bold_rel: str, mask_rel: str, cleaned: bool = False):
    """Pretend the standard-space step ran on ``bold_rel``: create its files."""
    dummy = {
        "bold": bold_rel,
        "to_t1_affine": bold_rel,
        "t1_to_mni_warp": bold_rel,
        "brain_mask": mask_rel,
    }
    out, folder = _outputs(ws, "func_to_mni", "sub-001", dummy, "func_to_mni")
    for name in (out.bold_mni, out.brain_mask_mni):
        (ws.root / folder / name).write_text("x")
    return f"{folder}/{out.bold_mni}", f"{folder}/{out.brain_mask_mni}"


def feat_paths(ws: Workspace, slug_bold: str = BOLD) -> tuple[str, str]:
    dummy = {k: slug_bold for k in ("bold", "t1_head", "t1_brain", "t1_seg")}
    out, folder = _outputs(ws, "feat_preproc", "sub-001", dummy, "feat_preproc")
    return f"{folder}/{out.preproc_bold}", f"{folder}/{out.brain_mask}"


def test_it_is_off_by_default_and_adds_no_steps(tmp_path: Path) -> None:
    p, spec = plan(workspace(tmp_path))
    stage = conn(p)
    assert not stage.enabled and stage.can_run  # can be ticked: standard space is in the plan
    assert not any(s.step.startswith("roi_") for s in spec.steps)  # type: ignore[union-attr]


def test_it_sits_after_standard_space_and_before_diffusion() -> None:
    order = [s.id for s in STAGES]
    assert order.index("standard_space") < order.index("connectivity") < order.index("diffusion")


def test_in_a_full_run_it_follows_standard_space_and_is_wired_to_its_results(
    tmp_path: Path,
) -> None:
    ws = workspace(tmp_path, volumes=45)
    p, spec = plan(ws, **with_connectivity())
    assert p.can_start and conn(p).can_run and conn(p).enabled
    assert [s.step for s in spec.steps][-3:] == [  # type: ignore[union-attr]
        "func_to_mni", "roi_timeseries", "roi_correlation",
    ]  # fmt: skip
    by = {s.id: s for s in spec.steps}  # type: ignore[union-attr]
    ts = by["roi_timeseries_schaefer100n7__task-rest"]
    assert ts.inputs == {
        "bold": "${func_to_mni__task-rest.bold_mni}",
        "brain_mask": "${func_to_mni__task-rest.brain_mask_mni}",
    }
    assert ts.params == {"atlas": "schaefer100n7", "only_voxels_with_signal": True}
    assert ts.label == "roi_timeseries_schaefer100n7"
    corr = by["roi_correlation_schaefer100n7__task-rest"]
    assert corr.inputs == {"timeseries": "${roi_timeseries_schaefer100n7__task-rest.timeseries}"}
    parse_pipeline(spec.model_dump(mode="json"))  # type: ignore[union-attr]


def test_the_cleaned_data_flows_through_standard_space_into_connectivity(tmp_path: Path) -> None:
    ws = workspace(tmp_path, volumes=45)
    p, spec = plan(ws, stages={"artifact_rejection": True, "connectivity": True})
    by = {s.id: s for s in spec.steps}  # type: ignore[union-attr]
    assert by["func_to_mni__task-rest"].inputs["bold"] == "${regfilt__task-rest.cleaned_bold}"
    assert (
        by["roi_timeseries_schaefer100n7__task-rest"].inputs["bold"].startswith("${func_to_mni__")
    )
    assert "denoised data" in {s.name: s.value for s in conn(p).items[0].settings}["Data"]


def test_every_atlas_and_every_run_gets_its_own_pair_of_steps(tmp_path: Path) -> None:
    ws = workspace(tmp_path, runs=(BOLD, BOLD2), volumes=45)
    p, spec = plan(ws, **with_connectivity(atlases=["schaefer100n7", "aal3v2"]))
    mine = [s for s in spec.steps if s.step.startswith("roi_")]  # type: ignore[union-attr]
    assert len(mine) == 2 * 2 * 2 and len({s.id for s in mine}) == 8
    assert {s.label for s in mine} == {
        "roi_timeseries_schaefer100n7", "roi_correlation_schaefer100n7",
        "roi_timeseries_aal3v2", "roi_correlation_aal3v2",
    }  # fmt: skip
    assert len(conn(p).items) == 2  # one line per run
    # the id keeps "<step>__<run>" so progress can tell runs apart (see progress._slug)
    assert all(s.id.split("__", 1)[1] in ("task-rest", "task-other_run-2") for s in mine)


def test_the_averaging_choice_is_passed_on(tmp_path: Path) -> None:
    ws = workspace(tmp_path, volumes=45)
    _, spec = plan(ws, **with_connectivity(only_voxels_with_signal=False))
    ts = next(s for s in spec.steps if s.step == "roi_timeseries")  # type: ignore[union-attr]
    assert ts.params["only_voxels_with_signal"] is False


def test_alone_without_standard_space_it_explains_what_is_missing(tmp_path: Path) -> None:
    ws = workspace(tmp_path, volumes=45, anat_done=True)
    make_earlier_results(ws)  # FEAT ran, standard space did not
    p, spec = plan(ws, stages={**only("connectivity")})
    stage = conn(p)
    assert not stage.can_run and "standard space" in (stage.reason or "").lower()
    assert spec is None


def test_alone_it_uses_an_earlier_standard_space_result(tmp_path: Path) -> None:
    ws = workspace(tmp_path, volumes=45, anat_done=True)
    make_earlier_results(ws)
    bold, mask = feat_paths(ws)
    mni_bold, mni_mask = make_standard_results(ws, bold, mask)
    p, spec = plan(ws, stages=only("connectivity"))
    assert p.can_start and [s.step for s in spec.steps] == ["roi_timeseries", "roi_correlation"]  # type: ignore[union-attr]
    ts = spec.steps[0]  # type: ignore[union-attr]
    assert ts.inputs == {"bold": mni_bold, "brain_mask": mni_mask}  # real files, no references
    assert "preprocessed data" in {s.name: s.value for s in conn(p).items[0].settings}["Data"]


def test_alone_it_prefers_the_cleaned_standard_space_result(tmp_path: Path) -> None:
    ws = workspace(tmp_path, volumes=45, anat_done=True)
    make_earlier_results(ws, cleaned=True)
    cleaned = existing_cleaned(ws, "sub-001", BOLD)
    assert cleaned is not None
    _, mask = feat_paths(ws)
    mni_bold, _ = make_standard_results(ws, cleaned, mask)
    assert "desc-denoised" in mni_bold
    _, spec = plan(ws, stages=only("connectivity"))
    assert spec is not None and spec.steps[0].inputs["bold"] == mni_bold


def test_existing_standard_finds_nothing_when_the_files_are_missing(tmp_path: Path) -> None:
    ws = workspace(tmp_path, anat_done=True)
    make_earlier_results(ws)
    bold, mask = feat_paths(ws)
    assert existing_standard(ws, "sub-001", bold, mask) is None
    make_standard_results(ws, bold, mask)
    found = existing_standard(ws, "sub-001", bold, mask)
    assert found is not None and set(found) == {"bold", "brain_mask"}


def test_bad_atlas_choices_are_explained(tmp_path: Path) -> None:
    ws = workspace(tmp_path, volumes=45)
    p, _ = plan(ws, **with_connectivity(atlases=[]))
    assert not conn(p).can_run and "at least one atlas" in (conn(p).reason or "")
    p, _ = plan(ws, **with_connectivity(atlases=["schaefer100n7", "brainnetome"]))
    assert not conn(p).can_run and "brainnetome" in (conn(p).reason or "")


def test_a_subject_without_functional_data_cannot_run_it(tmp_path: Path) -> None:
    ws = workspace(tmp_path, runs=(), fieldmap=False)
    p, spec = plan(ws, **with_connectivity())
    assert not conn(p).can_run and "functional" in (conn(p).reason or "").lower()
    assert not any(s.step.startswith("roi_") for s in (spec.steps if spec else []))


def test_the_plan_reaches_the_dialog_through_the_api(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from mrforge.api.app import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    body = client.post(
        f"/api/workspaces/{ws_id}/process/plan",
        json={"subject": "sub-001", "connectivity": {"atlases": ["aal3v2"]}},
    ).json()
    assert "connectivity" in [s["id"] for s in body["stages"]]


def test_progress_tells_the_atlases_of_one_run_apart(tmp_path: Path) -> None:
    """Two atlases of the same run: each pair of steps is counted once its own jobs exist (the
    step id is '<step>_<atlas>__<run>', the run folder '<label>_<run>')."""
    from test_progress import add_job, setup

    from mrforge.models import Operation
    from mrforge.progress import operation_progress

    ws, op, sid = setup(tmp_path)
    steps = []
    for atlas in ("schaefer100n7", "aal3v2"):
        for name in ("roi_timeseries", "roi_correlation"):
            steps.append(
                {
                    "id": f"{name}_{atlas}__task-rest",
                    "label": f"{name}_{atlas}",
                    "step": name,
                    "inputs": {"bold": "b"},
                }
            )
    spec = {"name": "full-sub-001", "subject": "sub-001", "steps": steps}
    with ws.session() as s:
        s.get(Operation, op.id).args = {"spec": spec}  # type: ignore[union-attr]
    for atlas, state in (("schaefer100n7", "Completed"), ("aal3v2", "Running")):
        for name in ("roi_timeseries", "roi_correlation"):
            if atlas == "aal3v2" and name == "roi_correlation":
                continue
            add_job(ws, sid, name, state, f"{name}_{atlas}", f"{name}_{atlas}_task-rest")
    with ws.session() as s:
        fresh = s.get(Operation, op.id)
        s.expunge(fresh)  # type: ignore[arg-type]
    p = operation_progress(ws, fresh)  # type: ignore[arg-type]
    assert [s.state for s in p.steps] == ["done", "done", "running", "waiting"]
    assert (p.done, p.total) == (2, 4) and p.steps[2].run == "task-rest"


def test_the_atlas_overlay_is_listed_in_the_viewer(tmp_path: Path) -> None:
    from test_viewerimages import build, image

    from mrforge.viewerimages import FUNC, find_images

    ws = build(tmp_path)
    name = "sub-001_task-rest_space-MNI152NLin6Asym_seg-aal3v2_dseg.nii.gz"
    image(ws, f"derivatives/mrforge/sub-001/func/{name}", (4, 4, 4))
    found = [f.described for f in find_images(ws, "sub-001") if "Atlas" in f.described.name]
    assert [(d.group, d.name, d.role) for d in found] == [
        (FUNC, "Atlas: AAL3 (version 3v2), regions with signal (task-rest)", "overlay")
    ]


def test_the_report_has_a_connectivity_section() -> None:
    from mrforge.report import SECTIONS, STEP_TITLES

    section = next(s for s in SECTIONS if s[0] == "connectivity")
    assert section[2] == ["roi_timeseries", "roi_correlation"]
    assert all(step in STEP_TITLES for step in section[2])


def test_a_preset_can_carry_the_atlas_choice() -> None:
    from mrforge.presets import PresetOptions

    options = PresetOptions(
        stages={"connectivity": True}, connectivity=ConnectivityOptions(atlases=["aal3v2"])
    )
    again = PresetOptions.model_validate(options.model_dump())
    assert again.connectivity.atlases == ["aal3v2"] and again.stages == {"connectivity": True}


@pytest.mark.fsl
def test_a_pipeline_of_the_stage_reruns_only_the_new_atlas(tmp_path: Path) -> None:
    """Run the steps the stage emits through the real engine on synthetic standard-space data:
    a second run reuses everything; adding an atlas runs only that atlas' two steps."""
    import nibabel as nib
    from test_roi_timeseries import BOLD as MNI_BOLD
    from test_roi_timeseries import MASK, save_bold, synthetic_bold

    from mrforge.engine import Action, run_pipeline
    from mrforge.errors import StepError
    from mrforge.fsl_env import find_fsl
    from mrforge.pipeline import PipelineSpec, PipelineStep
    from mrforge.runner.local import LocalJobQueue

    try:
        find_fsl()
    except StepError:
        pytest.skip("FSL not found")

    data, atlas, affine, _ = synthetic_bold("schaefer100n7")
    ws = Workspace.create(tmp_path / "ws")
    save_bold(ws, data, affine)
    nib.save(nib.Nifti1Image((atlas > 0).astype("float32"), affine), ws.root / MASK)

    def spec(atlases_: list[str]) -> PipelineSpec:
        steps = []
        for a in atlases_:
            ts = f"roi_timeseries_{a}__task-rest"
            steps.append(PipelineStep(id=ts, label=f"roi_timeseries_{a}", step="roi_timeseries",
                                      inputs={"bold": MNI_BOLD, "brain_mask": MASK},
                                      params={"atlas": a}))  # fmt: skip
            steps.append(PipelineStep(id=f"roi_correlation_{a}__task-rest",
                                      label=f"roi_correlation_{a}", step="roi_correlation",
                                      inputs={"timeseries": f"${{{ts}.timeseries}}"}))  # fmt: skip
        return PipelineSpec(name="conn", subject="sub-001", steps=steps)

    def actions(s: PipelineSpec) -> dict[str, Action]:
        return {o.step_id: o.action for o in run_pipeline(ws, LocalJobQueue(ws), s)}

    first = actions(spec(["schaefer100n7"]))
    assert set(first.values()) == {Action.RAN} and len(first) == 2
    assert set(actions(spec(["schaefer100n7"])).values()) == {Action.REUSED}
    both = actions(spec(["schaefer100n7", "schaefer100n17"]))  # keys are the step labels
    assert {k: v for k, v in both.items() if k.endswith("schaefer100n7")} == {
        "roi_timeseries_schaefer100n7": Action.REUSED,
        "roi_correlation_schaefer100n7": Action.REUSED,
    }
    assert {v for k, v in both.items() if k.endswith("schaefer100n17")} == {Action.RAN}
    func = ws.derivatives_dir / "sub-001" / "func"
    names = sorted(x.name for x in func.rglob("*relmat.txt"))
    assert len(names) == 4 and sum("schaefer100n17" in n for n in names) == 2
