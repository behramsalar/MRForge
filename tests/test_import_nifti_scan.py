"""Loose NIfTI files appear in the review table with a proposed type; unsure ones wait."""

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mrforge.importing.classify import effective_all, load_rules, set_override
from mrforge.importing.inspect import inspect_source
from mrforge.importing.manifest import list_manifests, load_manifest, save_manifest
from mrforge.operations import _import_run, _scan
from mrforge.workspace import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def write(folder: Path, name: str, shape: tuple[int, ...], sidecar: dict | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = np.random.default_rng(len(name)).random(shape).astype("float32")
    nib.save(nib.Nifti1Image(data, np.eye(4)), folder / f"{name}.nii.gz")  # type: ignore[attr-defined]
    if sidecar is not None:
        (folder / f"{name}.json").write_text(json.dumps(sidecar))


@pytest.fixture
def subject_folder(tmp_path: Path) -> Path:
    f = tmp_path / "data" / "alpha"
    write(f, "scan1", (8, 8, 70), {"SeriesDescription": "t1_mprage", "SeriesNumber": 2})
    write(
        f, "scan2", (6, 6, 6, 12),
        {"SeriesDescription": "resting_state_bold", "SeriesNumber": 3, "RepetitionTime": 2.0,
         "ImageType": ["ORIGINAL", "PRIMARY", "FMRI"]},
    )  # fmt: skip
    write(f, "scan3", (6, 6, 6), {"SeriesDescription": "mystery", "SeriesNumber": 4})
    write(f, "scan4", (6, 6, 6), {"SeriesDescription": "fmap", "SeriesNumber": 5})
    return f.parent


def table(ws: Workspace) -> dict[str, tuple[str, str]]:
    m = list_manifests(ws)[0]
    eff = effective_all(m, load_rules(ws))
    return {s.description: (eff[s.uid].kind, eff[s.uid].action) for s in m.series}


def test_files_are_proposed_a_type_and_unsure_ones_ask(ws: Workspace, subject_folder: Path) -> None:
    result = _scan(ws, {"source": str(subject_folder)}, lambda _m: None)
    assert result["source_kind"] == "nifti" and result["group_size"] == 1
    found = table(ws)
    assert found["t1_mprage"] == ("T1w", "import")
    assert found["resting_state_bold"] == ("bold", "import")
    assert found["mystery"][1] == "ask"
    assert found["fmap"][1] == "skip"  # fieldmaps cannot come from loose files


def test_scanning_again_changes_nothing(ws: Workspace, subject_folder: Path) -> None:
    first = _scan(ws, {"source": str(subject_folder)}, lambda _m: None)
    second = _scan(ws, {"source": str(subject_folder)}, lambda _m: None)
    assert first["is_new"] and not second["is_new"]
    assert len(list_manifests(ws)) == 1


def test_import_writes_bids_after_the_researcher_decides(
    ws: Workspace, subject_folder: Path
) -> None:
    _scan(ws, {"source": str(subject_folder)}, lambda _m: None)
    manifest = load_manifest(ws)
    set_option = set_override(manifest, load_rules(ws), 4, skip=True)
    assert set_option.action == "skip"
    save_manifest(ws, manifest)
    result = _import_run(ws, {"import_id": manifest.id}, lambda _m: None)
    assert result["written"] > 0
    rawbids = ws.root / "rawbids" / "sub-001"
    assert (rawbids / "anat" / "sub-001_T1w.nii.gz").is_file()
    assert (rawbids / "func" / "sub-001_task-rest_bold.nii.gz").is_file()


def test_every_folder_is_a_subject_in_one_group(ws: Workspace, tmp_path: Path) -> None:
    root = tmp_path / "many"
    write(root / "a", "x", (8, 8, 70), {"SeriesDescription": "t1_mprage"})
    write(root / "b", "x", (8, 8, 70), {"SeriesDescription": "t1_mprage", "Extra": 1})
    result = _scan(ws, {"source": str(root)}, lambda _m: None)
    assert result["group_size"] == 2
    manifests = list_manifests(ws)
    assert {m.subject for m in manifests} == {"sub-001", "sub-002"}
    assert all(m.group is not None and m.group.of == 2 for m in manifests)


def test_bids_like_names_give_task_and_subject(ws: Workspace, tmp_path: Path) -> None:
    root = tmp_path / "named"
    write(root, "sub-07_task-nback_bold", (6, 6, 6, 10), {"RepetitionTime": 2.0})
    plan = inspect_source(root)
    assert plan.nifti[0].label == "sub-07"
    _scan(ws, {"source": str(root)}, lambda _m: None)
    manifest = list_manifests(ws)[0]
    assert manifest.subject == "sub-07"
    cls = effective_all(manifest, load_rules(ws))[manifest.series[0].uid]
    assert cls.entities.get("task") == "nback"


def test_a_wrong_shape_stops_the_import_with_an_explanation(
    ws: Workspace, subject_folder: Path
) -> None:
    from mrforge.errors import StepError

    _scan(ws, {"source": str(subject_folder)}, lambda _m: None)
    manifest = load_manifest(ws)
    set_override(manifest, load_rules(ws), 4, kind="dwi")  # one volume, no b-values
    save_manifest(ws, manifest)
    with pytest.raises(StepError) as raised:
        _import_run(ws, {"import_id": manifest.id}, lambda _m: None)
    assert raised.value.code == "CONVERSION_FAILED"
    assert "Series 4" in raised.value.message
    assert not (ws.root / "rawbids" / "sub-001").exists()
