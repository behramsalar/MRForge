"""The diffusion stage: what it plans for a subject, and the pipeline it turns into."""

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge import diffusion as diffusion_module
from mrforge import processing
from mrforge.diffusion import DiffusionOptions, diffusion_runs
from mrforge.processing import FullOptions, plan_full_processing
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.registry import get_step
from mrforge.workspace import Workspace

AP = {"Manufacturer": "Siemens", "PhaseEncodingDirection": "j-", "TotalReadoutTime": 0.05}
PA = {"Manufacturer": "Siemens", "PhaseEncodingDirection": "j", "TotalReadoutTime": 0.05}
PHILIPS = {"Manufacturer": "Philips", "PhaseEncodingAxis": "j"}


def image(path: Path, shape: tuple[int, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.ones(shape, dtype="float32"), np.eye(4)), path)


def put_dwi(ws: Workspace, name: str, side: dict | None, *, bvals: bool = True) -> str:
    rel = f"rawbids/sub-001/dwi/{name}.nii.gz"
    image(ws.root / rel, (4, 4, 4, 3))
    if side is not None:
        (ws.root / rel.replace(".nii.gz", ".json")).write_text(json.dumps(side))
    if bvals:
        (ws.root / rel.replace(".nii.gz", ".bval")).write_text("0 1000 1000\n")
        (ws.root / rel.replace(".nii.gz", ".bvec")).write_text("0 1 0\n0 0 1\n0 0 0\n")
    return rel


def put_epi(ws: Workspace, side: dict, intended: str | None = None) -> None:
    rel = "rawbids/sub-001/fmap/sub-001_dir-PA_epi.nii.gz"
    image(ws.root / rel, (4, 4, 4))
    data = dict(side)
    if intended:
        data["IntendedFor"] = [intended]
    (ws.root / rel.replace(".nii.gz", ".json")).write_text(json.dumps(data))


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    w = Workspace.create(tmp_path / "ws")
    w.get_or_create_subject("sub-001")
    return w


@pytest.fixture(autouse=True)
def mrtrix_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(processing, "find_mrtrix", lambda: object())


def plan(ws: Workspace, **options: object):
    opts = FullOptions(
        subject="sub-001",
        stages={
            "anatomical": False,
            "functional": False,
            "standard_space": False,
            "diffusion": True,
        },
        diffusion=DiffusionOptions(**options),  # type: ignore[arg-type]
    )
    return plan_full_processing(ws, opts)


def ids(spec) -> list[str]:
    return [s.id.split("__")[0] for s in spec.steps]


def stage_of(p):
    return next(s for s in p.stages if s.id == "diffusion")


def test_the_stage_is_off_by_default_and_last() -> None:
    assert processing.STAGES[-1].id == "diffusion"
    assert processing.STAGES[-1].default_enabled is False


def test_a_subject_without_diffusion_data_cannot_run_the_stage(ws: Workspace) -> None:
    p, spec = plan(ws)
    assert not stage_of(p).can_run
    assert "no diffusion image" in (stage_of(p).reason or "")
    assert spec is None


def test_missing_bvals_are_explained(ws: Workspace) -> None:
    put_dwi(ws, "sub-001_dwi", AP, bvals=False)
    p, _ = plan(ws)
    assert not stage_of(p).can_run
    assert ".bval" in (stage_of(p).reason or "")


def test_with_a_field_map_the_whole_chain_is_planned(ws: Workspace) -> None:
    put_dwi(ws, "sub-001_dwi", AP)
    put_epi(ws, PA, intended="dwi/sub-001_dwi.nii.gz")
    p, spec = plan(ws)
    assert spec is not None
    assert ids(spec) == [
        "dwi_denoise", "dwi_unring", "dwi_topup", "dwi_eddy", "dwi_dtifit", "dwi_qc",
        "dwi_to_template", "alps_rois", "alps_index",
    ]  # fmt: skip
    steps = {s.id.split("__")[0]: s for s in spec.steps}
    # each step takes the output of the one before it
    assert steps["dwi_unring"].inputs["dwi"] == "${dwi_denoise__dwi.dwi}"
    assert steps["dwi_topup"].inputs["dwi"] == "${dwi_unring__dwi.dwi}"
    assert steps["dwi_eddy"].inputs["topup_fieldcoef"] == "${dwi_topup__dwi.fieldcoef}"
    assert steps["dwi_dtifit"].inputs["bvec"] == "${dwi_eddy__dwi.bvec}"
    assert steps["dwi_dtifit"].inputs["mask"] == "${dwi_eddy__dwi.mask}"
    assert steps["alps_rois"].inputs["fa"] == "${dwi_to_template__dwi.fa}"
    assert steps["alps_index"].inputs["tensor"] == "${dwi_to_template__dwi.tensor}"
    assert steps["alps_rois"].params["space"] == "template"
    assert steps["alps_rois"].params["template"] == "jhu_fa"
    assert steps["alps_index"].params["settings"]["distortion correction"] == "TOPUP"
    assert steps["alps_index"].params["notes"] == []
    assert stage_of(p).can_run


def test_without_a_reverse_image_topup_is_left_out_and_flagged(ws: Workspace) -> None:
    put_dwi(ws, "sub-001_dwi", PHILIPS)
    p, spec = plan(ws)
    assert spec is not None
    assert "dwi_topup" not in ids(spec)
    index = next(s for s in spec.steps if s.step == "alps_index")
    assert index.params["settings"]["distortion correction"] == "none"
    assert any("No distortion correction" in n for n in index.params["notes"])
    assert "No distortion correction" in (stage_of(p).items[0].note or "")
    eddy = next(s for s in spec.steps if s.step == "dwi_eddy")
    assert "topup_fieldcoef" not in eddy.inputs


def test_without_mrtrix_denoising_is_skipped_and_recorded(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(processing, "find_mrtrix", lambda: None)
    put_dwi(ws, "sub-001_dwi", AP)
    p, spec = plan(ws)
    assert spec is not None
    assert "dwi_denoise" not in ids(spec) and "dwi_unring" not in ids(spec)
    index = next(s for s in spec.steps if s.step == "alps_index")
    assert any("MRtrix3 is not installed" in n for n in index.params["notes"])
    assert stage_of(p).can_run


def test_native_space_skips_the_registration(ws: Workspace) -> None:
    put_dwi(ws, "sub-001_dwi", AP)
    _, spec = plan(ws, registration="native")
    assert spec is not None
    assert "dwi_to_template" not in ids(spec)
    rois = next(s for s in spec.steps if s.step == "alps_rois")
    assert rois.params["space"] == "native"
    assert rois.inputs["fa"] == "${dwi_dtifit__dwi.fa}"


def test_skipping_eddy_is_a_recorded_choice(ws: Workspace) -> None:
    put_dwi(ws, "sub-001_dwi", AP)
    _, spec = plan(ws, eddy="none")
    assert spec is not None
    assert "dwi_eddy" not in ids(spec)
    index = next(s for s in spec.steps if s.step == "alps_index")
    assert any("No eddy-current" in n for n in index.params["notes"])
    fit = next(s for s in spec.steps if s.step == "dwi_dtifit")
    assert fit.inputs["dwi"] == "${dwi_unring__dwi.dwi}"


def test_without_eddy_topup_is_left_out_as_in_the_script(ws: Workspace) -> None:
    """alps.sh with -e 0 never applies TOPUP and takes the mask from the raw b0."""
    put_dwi(ws, "sub-001_dwi", AP)
    put_epi(ws, PA, intended="dwi/sub-001_dwi.nii.gz")
    _, spec = plan(ws, eddy="none")
    assert spec is not None
    assert "dwi_topup" not in ids(spec)
    fit = next(s for s in spec.steps if s.step == "dwi_dtifit")
    assert "mask" not in fit.inputs  # the step makes it from the b0 itself
    index = next(s for s in spec.steps if s.step == "alps_index")
    assert index.params["settings"]["distortion correction"] == "none"
    assert any("TOPUP is applied through eddy" in n for n in index.params["notes"])


def test_the_structural_route_needs_the_image_and_picks_the_template(ws: Workspace) -> None:
    put_dwi(ws, "sub-001_dwi", AP)
    p, _ = plan(ws, structural="t1")
    assert not stage_of(p).can_run and "T1" in (stage_of(p).reason or "")
    image(ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz", (4, 4, 4))
    p, spec = plan(ws, structural="t1")
    assert spec is not None
    reg = next(s for s in spec.steps if s.step == "dwi_to_template")
    assert reg.inputs["struct"] == "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    assert reg.params["struct_weight"] == "t1"
    rois = next(s for s in spec.steps if s.step == "alps_rois")
    assert rois.params["template"] == "mni_t1"


def test_pipeline_steps_are_valid_for_their_step_classes(ws: Workspace) -> None:
    put_dwi(ws, "sub-001_dwi", AP)
    put_epi(ws, PA, intended="dwi/sub-001_dwi.nii.gz")
    _, spec = plan(ws, roi_source="sphere", roi_radius_mm=3.0, tensor_method="vecreg")
    assert spec is not None
    for step in spec.steps:
        # parameters and input names must be accepted by the step's own specs
        built = get_step(step.step)
        built.ParamSpec(**step.params)
        assert set(step.inputs) <= set(built.InputSpec.model_fields), step.id


def test_reverse_image_rules(ws: Workspace) -> None:
    main = put_dwi(ws, "sub-001_dwi", AP)
    put_epi(ws, AP)  # same direction: not usable
    (run,) = diffusion_runs(ws, "sub-001")
    assert run.reverse is None and "same phase-encoding" in (run.topup_note or "")
    put_epi(ws, PA)
    (run,) = diffusion_runs(ws, "sub-001")
    assert run.reverse == "rawbids/sub-001/fmap/sub-001_dir-PA_epi.nii.gz"
    assert run.reverse_from == "field map"
    assert main  # the main series itself is never its own reverse image


def test_two_philips_series_look_alike_unless_told(ws: Workspace) -> None:
    put_dwi(ws, "sub-001_acq-a_dwi", PHILIPS)
    put_dwi(ws, "sub-001_acq-b_dwi", PHILIPS)
    runs = diffusion_runs(ws, "sub-001")
    assert all(r.reverse is None for r in runs)
    runs = diffusion_runs(ws, "sub-001", second_is_opposite=True)
    assert runs[0].reverse is not None and runs[0].reverse_from == "second diffusion series"


def test_module_is_the_one_the_stage_uses() -> None:
    assert processing.diffusion_runs is diffusion_module.diffusion_runs


def test_a_batch_of_only_the_diffusion_stage_needs_no_anatomical_or_functional_data(
    ws: Workspace,
) -> None:
    """The Diffusion page runs many subjects at once; the other stages are ticked off."""
    from mrforge.processing import BatchOptions, plan_batch

    put_dwi(ws, "sub-001_dwi", AP)
    ws.get_or_create_subject("sub-002")
    ws.get_or_create_subject("sub-003")
    rel = "rawbids/sub-002/dwi/sub-002_dwi.nii.gz"
    image(ws.root / rel, (4, 4, 4, 3))
    (ws.root / rel.replace(".nii.gz", ".json")).write_text(json.dumps(AP))
    (ws.root / rel.replace(".nii.gz", ".bval")).write_text("0 1000 1000\n")
    (ws.root / rel.replace(".nii.gz", ".bvec")).write_text("0 1 0\n0 0 1\n0 0 0\n")
    # sub-003 has a functional run only
    image(ws.root / "rawbids/sub-003/func/sub-003_task-rest_bold.nii.gz", (4, 4, 4, 8))
    only = {"anatomical": False, "functional": False, "standard_space": False, "diffusion": True}
    batch, specs = plan_batch(
        ws, BatchOptions(subjects=["sub-001", "sub-002", "sub-003"], stages=only)
    )
    lines = {s.subject: s for s in batch.subjects}
    assert lines["sub-001"].can_start and lines["sub-002"].can_start  # no T1, no BOLD needed
    assert not lines["sub-003"].can_start and lines["sub-003"].reason  # says why, others unharmed
    assert batch.runnable == 2 and len(specs) == 2
    assert {spec.subject for spec in specs} == {"sub-001", "sub-002"}


def test_in_a_batch_the_structural_route_skips_only_subjects_without_the_anatomical_image(
    ws: Workspace,
) -> None:
    """As in alps.sh: the T1/T2 is needed only for the structural route (-v), per subject."""
    from mrforge.processing import BatchOptions, plan_batch

    put_dwi(ws, "sub-001_dwi", AP)
    ws.get_or_create_subject("sub-002")
    rel = "rawbids/sub-002/dwi/sub-002_dwi.nii.gz"
    image(ws.root / rel, (4, 4, 4, 3))
    (ws.root / rel.replace(".nii.gz", ".json")).write_text(json.dumps(AP))
    (ws.root / rel.replace(".nii.gz", ".bval")).write_text("0 1000 1000\n")
    (ws.root / rel.replace(".nii.gz", ".bvec")).write_text("0 1 0\n0 0 1\n0 0 0\n")
    image(ws.root / "rawbids/sub-002/anat/sub-002_T1w.nii.gz", (4, 4, 4))  # only sub-002 has a T1
    only = {"anatomical": False, "functional": False, "standard_space": False, "diffusion": True}
    structural = BatchOptions(
        subjects=["sub-001", "sub-002"], stages=only, diffusion=DiffusionOptions(structural="t1")
    )
    batch, specs = plan_batch(ws, structural)
    lines = {s.subject: s for s in batch.subjects}
    assert not lines["sub-001"].can_start and lines["sub-001"].reason  # says why
    assert lines["sub-002"].can_start and len(specs) == 1
    default, _ = plan_batch(ws, BatchOptions(subjects=["sub-001", "sub-002"], stages=only))
    assert default.runnable == 2  # the default route needs no anatomical image
