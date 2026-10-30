"""What the viewer lists for a subject: plain names, groups, nothing technical."""

from pathlib import Path

import nibabel as nib
import numpy as np
from fastapi.testclient import TestClient

from mrforge.api.app import create_app
from mrforge.viewerimages import ANAT, FMAP, FUNC, RAW, find_images
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001"


def image(ws: Workspace, rel: str, shape: tuple[int, ...] = (4, 4, 4)) -> None:
    path = ws.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.ones(shape, dtype="float32"), np.eye(4)), path)


def build(tmp_path: Path) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    raw = [
        ("rawbids/sub-001/anat/sub-001_T1w.nii.gz", (4, 4, 4)),
        ("rawbids/sub-001/func/sub-001_task-rest_run-1_bold.nii.gz", (4, 4, 4, 9)),
        ("rawbids/sub-001/fmap/sub-001_acq-fmap_phasediff.nii.gz", (4, 4, 4)),
    ]
    results = [
        f"{D}/anat/sub-001_desc-biascorr_T1w.nii.gz",
        f"{D}/anat/sub-001_desc-brain_mask.nii.gz",
        f"{D}/anat/sub-001_dseg.nii.gz",
        f"{D}/anat/sub-001_label-GM_probseg.nii.gz",
        f"{D}/anat/sub-001_from-T1w_to-MNI152NLin6Asym_mode-image_desc-fnirtcoeff_xfm.nii.gz",
        f"{D}/func/sub-001_task-rest_run-1_desc-preproc_bold.nii.gz",
        f"{D}/func/sub-001_task-rest_run-1_space-T1w_desc-feat_boldref.nii.gz",
        f"{D}/func/sub-001_task-rest_run-1_space-MNI152NLin6Asym_desc-preproc_bold.nii.gz",
        f"{D}/func/sub-001_task-rest_run-1_desc-brain_mask.nii.gz",
        f"{D}/fmap/sub-001_desc-prepared_fieldmap.nii.gz",
        # native tool folders hold many files that must not be listed
        f"{D}/anat/sub-001_T1w.anat/T1_fast_pve_0.nii.gz",
        f"{D}/func/sub-001_task-rest_run-1_bold.feat/filtered_func_data.nii.gz",
    ]
    for rel, shape in raw:
        image(ws, rel, shape)
    for rel in results:
        image(ws, rel, (4, 4, 4, 9) if "bold.nii" in rel else (4, 4, 4))
    return ws


def test_the_resampled_t1_has_a_plain_name(tmp_path: Path) -> None:
    ws = build(tmp_path)
    image(ws, f"{D}/anat/sub-001_desc-1mm_T1w.nii.gz", (4, 4, 4))
    names = {f.described.name for f in find_images(ws, "sub-001")}
    assert "T1, resampled to 1 mm" in names


def test_groups_names_and_roles(tmp_path: Path) -> None:
    found = {
        (f.described.group, f.described.name, f.described.role)
        for f in find_images(build(tmp_path), "sub-001")
    }
    assert (RAW, "T1 (original)", "underlay") in found
    assert (RAW, "Functional (task-rest run-1)", "underlay") in found
    assert (RAW, "Fieldmap phase difference (acq-fmap)", "underlay") in found
    assert (ANAT, "T1, bias-corrected", "underlay") in found
    assert (ANAT, "Brain mask", "overlay") in found
    assert (ANAT, "Tissue segmentation (CSF, GM, WM)", "overlay") in found
    assert (ANAT, "Grey matter probability", "overlay") in found
    assert (FUNC, "Functional, preprocessed (task-rest run-1)", "underlay") in found
    assert (
        FUNC,
        "Functional example volume (task-rest run-1), aligned to the T1",
        "overlay",
    ) in found
    assert (FUNC, "Functional in standard space (task-rest run-1)", "underlay") in found
    assert (FUNC, "Brain mask (task-rest run-1)", "overlay") in found
    assert (FMAP, "Fieldmap, prepared (rad/s)", "overlay") in found


def test_transforms_and_native_tool_folders_are_not_listed(tmp_path: Path) -> None:
    names = [f.path.name for f in find_images(build(tmp_path), "sub-001")]
    assert not any("xfm" in n for n in names)
    assert "T1_fast_pve_0.nii.gz" not in names and "filtered_func_data.nii.gz" not in names


def test_order_is_raw_first_then_results_by_group(tmp_path: Path) -> None:
    groups = [f.described.group for f in find_images(build(tmp_path), "sub-001")]
    assert groups == sorted(groups, key=[RAW, ANAT, FUNC, FMAP].index)
    first = find_images(build(tmp_path / "b"), "sub-001")[0]
    assert first.described.name == "T1 (original)"


def test_time_series_say_how_many_volumes(tmp_path: Path) -> None:
    by_name = {f.described.name: f for f in find_images(build(tmp_path), "sub-001")}
    assert by_name["Functional (task-rest run-1)"].volumes == 9
    assert by_name["T1 (original)"].volumes is None


def test_route_returns_files_the_viewer_can_load(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    ws = Workspace.open(tmp_path / "workspaces" / ws_id)
    image(ws, "rawbids/sub-001/anat/sub-001_T1w.nii.gz")
    [item] = client.get(f"/api/workspaces/{ws_id}/subjects/sub-001/images").json()
    assert (
        item["group"] == "Raw data" and item["name"] == "T1 (original)" and item["size_bytes"] > 0
    )
    assert client.get(item["url"]).status_code == 200  # served, from an allowed folder
