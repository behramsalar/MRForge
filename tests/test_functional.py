"""Stage 5f: what functional preprocessing needs, and the pipeline built from the options."""

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from mrforge.api.app import create_app
from mrforge.errors import StepError
from mrforge.functional import ANAT_FILES, FunctionalOptions, build_pipeline, check_ready
from mrforge.pipeline import parse_pipeline
from mrforge.runner.jobs import build_context
from mrforge.steps import builtin  # noqa: F401
from mrforge.workspace import Workspace

BOLD = "rawbids/sub-001/func/sub-001_task-rest_bold.nii.gz"
BOLD_FACTS = {
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
    anat: bool = True,
    fieldmap: bool = True,
    bold_facts: dict[str, object] | None = None,
) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    image(ws.root / BOLD, (4, 4, 4, 8))
    (ws.root / BOLD.replace(".nii.gz", ".json")).write_text(json.dumps(bold_facts or BOLD_FACTS))
    if fieldmap:
        for name in ("magnitude1", "magnitude2", "phasediff"):
            image(ws.root / f"rawbids/sub-001/fmap/sub-001_{name}.nii.gz")
        side = {
            "EchoTime1": 0.00492,
            "EchoTime2": 0.00738,
            "IntendedFor": ["func/sub-001_task-rest_bold.nii.gz"],
        }
        (ws.root / "rawbids/sub-001/fmap/sub-001_phasediff.json").write_text(json.dumps(side))
    if anat:
        for ending in ANAT_FILES.values():
            image(ws.derivatives_dir / "sub-001" / "anat" / f"sub-001{ending}")
    return ws


def options(**kw: object) -> FunctionalOptions:
    return FunctionalOptions(**{"subject": "sub-001", "bold": BOLD, **kw})  # type: ignore[arg-type]


def test_everything_available(tmp_path: Path) -> None:
    ready = check_ready(workspace(tmp_path), "sub-001")
    assert ready.anat_ready and ready.anat_reason is None
    [run] = ready.runs
    assert run.name == "task-rest" and run.volumes == 8
    assert run.fieldmap.available and run.fieldmap.reason is None
    assert run.fieldmap.phasediff == "rawbids/sub-001/fmap/sub-001_phasediff.nii.gz"


def test_without_anatomical_results_nothing_can_start(tmp_path: Path) -> None:
    ws = workspace(tmp_path, anat=False)
    ready = check_ready(ws, "sub-001")
    assert not ready.anat_ready and "Anatomical processing" in (ready.anat_reason or "")
    with pytest.raises(StepError) as err:
        build_pipeline(ws, options())
    assert (
        err.value.code == "ANAT_NOT_READY"
        and "Run anatomical processing first" in err.value.suggested_action
    )


def test_no_fieldmap_is_explained_and_the_pipeline_works_without_it(tmp_path: Path) -> None:
    ws = workspace(tmp_path, fieldmap=False)
    fmap = check_ready(ws, "sub-001").runs[0].fieldmap
    assert not fmap.available and fmap.reason == "No fieldmap was acquired for this run."
    spec = build_pipeline(ws, options(use_fieldmap=False))
    assert [s.id for s in spec.steps] == ["feat_preproc", "func_qc", "func_to_mni"]
    with pytest.raises(StepError) as err:
        build_pipeline(ws, options(use_fieldmap=True))
    assert err.value.code == "FIELDMAP_UNAVAILABLE"


def test_a_fieldmap_for_other_runs_is_not_used(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    path = ws.root / "rawbids/sub-001/fmap/sub-001_phasediff.json"
    data = json.loads(path.read_text())
    data["IntendedFor"] = ["func/sub-001_task-other_bold.nii.gz"]
    path.write_text(json.dumps(data))
    assert not check_ready(ws, "sub-001").runs[0].fieldmap.available


def test_unsupported_fieldmap_type_is_named(tmp_path: Path) -> None:
    ws = workspace(tmp_path, fieldmap=False)
    image(ws.root / "rawbids/sub-001/fmap/sub-001_fieldmap.nii.gz")  # a ready-made Hz map
    reason = check_ready(ws, "sub-001").runs[0].fieldmap.reason or ""
    assert "not supported yet" in reason and "Siemens" in reason


def test_scan_facts_missing_for_unwarping_are_named(tmp_path: Path) -> None:
    facts = {k: v for k, v in BOLD_FACTS.items() if k != "PhaseEncodingDirection"}
    fmap = check_ready(workspace(tmp_path, bold_facts=facts), "sub-001").runs[0].fieldmap
    assert not fmap.available and "phase-encoding direction" in (fmap.reason or "")


def test_full_pipeline_is_valid_and_ordered(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    spec = build_pipeline(
        ws, options(delete_volumes=3, smoothing_fwhm_mm=6.0, highpass_cutoff_s=None)
    )
    assert [s.id for s in spec.steps] == ["fieldmap_prep", "feat_preproc", "func_qc", "func_to_mni"]
    parse_pipeline(spec.model_dump(mode="json"))  # references only point at earlier steps
    feat = next(s for s in spec.steps if s.id == "feat_preproc")
    assert feat.params == {"delete_volumes": 3, "smoothing_fwhm_mm": 6.0, "highpass_cutoff_s": None}
    assert feat.inputs["fieldmap"] == "${fieldmap_prep.fieldmap}"
    assert spec.name == "functional-sub-001_task-rest"
    # the standard-space step is optional
    short = build_pipeline(ws, options(to_mni=False))
    assert [s.id for s in short.steps][-1] == "func_qc"


def test_step_ids_equal_step_names_so_result_names_stay_clean(tmp_path: Path) -> None:
    spec = build_pipeline(workspace(tmp_path), options())
    assert all(s.id == s.step for s in spec.steps)


def test_unknown_image_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StepError) as err:
        build_pipeline(
            workspace(tmp_path), options(bold="rawbids/sub-001/func/nothing_bold.nii.gz")
        )
    assert err.value.code == "UNKNOWN_FILE"


def test_two_runs_of_a_subject_keep_separate_records(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    other = "rawbids/sub-001/func/sub-001_task-other_run-2_bold.nii.gz"
    image(ws.root / other, (4, 4, 4, 8))
    dirs = []
    for bold in (BOLD, other):
        _, ctx = build_context(ws, "feat_preproc", "sub-001", None, {"bold": bold}, {})
        dirs.append(ctx.run_dir.name)
    assert dirs == ["feat_preproc_task-rest", "feat_preproc_task-other_run-2"]
    _, anat = build_context(
        ws, "fsl_anat", "sub-001", None, {"t1": "rawbids/sub-001/anat/sub-001_T1w.nii.gz"}, {}
    )
    assert anat.run_dir.name == "fsl_anat"  # nothing changes for steps without entities
    # results of an earlier step (desc-, space-) do not change which recording a run belongs to
    _, qc = build_context(
        ws, "fieldmap_prep", "sub-001", None,
        {"magnitude1": "x/sub-001_task-rest_desc-brain_bold.nii.gz", "phasediff": "y"}, {},
    )  # fmt: skip
    assert qc.run_dir.name == "fieldmap_prep_task-rest"


# -- API ----------------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path))
    return TestClient(create_app(tmp_path / "workspaces"))


def test_api_reports_readiness_and_refuses_what_is_impossible(
    client: TestClient, tmp_path: Path
) -> None:
    created = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    ws = Workspace.open(tmp_path / "workspaces" / created)
    image(ws.root / BOLD, (4, 4, 4, 8))
    body = client.get(f"/api/workspaces/{created}/subjects/sub-001/functional").json()
    assert body["anat_ready"] is False and body["runs"][0]["fieldmap"]["available"] is False
    refused = client.post(
        f"/api/workspaces/{created}/functional", json={"subject": "sub-001", "bold": BOLD}
    )
    assert refused.status_code == 400 and refused.json()["code"] == "ANAT_NOT_READY"
    assert client.get(f"/api/workspaces/{created}/subjects/sub-001/qc").json() == []
