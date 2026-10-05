"""The Data page's view of a subject's raw images."""

from pathlib import Path

import nibabel as nib
import numpy as np
from fastapi.testclient import TestClient

from mrforge.api.app import create_app
from mrforge.datafiles import subject_data
from mrforge.workspace import Workspace


def image(path: Path, shape: tuple[int, ...], tr: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = nib.Nifti1Image(np.ones(shape, dtype="float32"), np.diag([2.0, 2.0, 2.0, 1.0]))
    if tr is not None:
        img.header.set_zooms((2.0, 2.0, 2.0, tr))
    nib.save(img, path)


def test_files_are_listed_by_datatype_with_details(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    base = ws.root / "rawbids" / "sub-001"
    image(base / "func" / "sub-001_task-rest_run-1_bold.nii.gz", (4, 4, 4, 6), tr=2.0)
    image(base / "anat" / "sub-001_T1w.nii.gz", (6, 6, 6))
    image(base / "fmap" / "sub-001_acq-fmap_phasediff.nii.gz", (4, 4, 4))
    (base / "anat" / "sub-001_T1w.json").write_text("{}")  # sidecars are not images
    data = subject_data(ws, "sub-001")
    assert [(f.datatype, f.suffix) for f in data.files] == [
        ("anat", "T1w"),
        ("func", "bold"),
        ("fmap", "phasediff"),
    ]
    bold = data.files[1]
    assert bold.recording == "task-rest run-1" and bold.shape == [4, 4, 4, 6]
    assert bold.repetition_time_s == 2.0
    assert data.files[0].repetition_time_s is None and data.files[0].recording == ""
    assert data.files[2].recording == "acq-fmap"
    assert data.bytes_total == sum(f.size_bytes for f in data.files) > 0


def test_a_broken_image_is_still_listed(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    path = ws.root / "rawbids/sub-001/anat/sub-001_T1w.nii.gz"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not an image")
    [f] = subject_data(ws, "sub-001").files
    assert f.shape is None and f.size_bytes == 12


def test_unknown_subject_is_empty_and_bad_names_are_refused(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    assert client.get(f"/api/workspaces/{ws_id}/subjects/sub-009/data").json()["files"] == []
    assert client.get(f"/api/workspaces/{ws_id}/subjects/..%2Fx/data").status_code in (400, 404)
