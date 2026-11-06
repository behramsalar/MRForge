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
    assert found["fmap"][1] == "ask"  # a lone fieldmap file has no partner: the researcher decides


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


def test_a_single_diffusion_volume_is_written_as_a_reverse_phase_encoding_image(
    ws: Workspace, tmp_path: Path
) -> None:
    root = tmp_path / "dti"
    for name, shape, number, pe in (("ap", (6, 6, 6, 4), 11, "j-"), ("pa", (6, 6, 6), 10, "j")):
        write(root, name, shape, {"SeriesDescription": f"dti_{name}", "SeriesNumber": number,
                                  "PhaseEncodingDirection": pe, "ImageType": ["ORIGINAL", "PRIMARY", "DIFFUSION", "NONE"]})  # fmt: skip
        (root / f"{name}.bval").write_text(
            " ".join(["0"] + ["1000"] * (shape[-1] - 1 if len(shape) > 3 else 0))
        )
        n = shape[-1] if len(shape) > 3 else 1
        (root / f"{name}.bvec").write_text("\n".join([" ".join(["0"] * n)] * 3))
    _scan(ws, {"source": str(root)}, lambda _m: None)
    manifest = load_manifest(ws)
    _import_run(ws, {"import_id": manifest.id}, lambda _m: None)
    sub = ws.root / "rawbids" / "sub-001"
    assert (sub / "dwi" / "sub-001_dwi.nii.gz").is_file()  # no run number: only one real dwi
    epi = sub / "fmap" / "sub-001_dir-PA_epi.json"
    assert json.loads(epi.read_text())["IntendedFor"] == ["dwi/sub-001_dwi.nii.gz"]


def test_a_bids_dataset_is_imported_from_the_same_entry_point(
    ws: Workspace, tmp_path: Path
) -> None:
    from test_import_existing import build_source

    source = build_source(tmp_path / "bidssrc", load_rules())
    result = _scan(ws, {"source": str(source)}, lambda _m: None)
    assert result["source_kind"] == "bids" and result["is_new"]
    assert result["subjects"] == ["sub-001", "sub-002"]
    assert (ws.root / "rawbids" / "sub-002" / "func").is_dir()
    again = _scan(ws, {"source": str(source)}, lambda _m: None)
    assert not again["is_new"] and again["import_id"] == result["import_id"]


def test_the_api_says_what_a_chosen_folder_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from mrforge.api.app import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MRFORGE_CONFIG", str(tmp_path / "cfg" / "config.json"))
    write(tmp_path / "data" / "alpha", "scan", (8, 8, 70))
    app = create_app(tmp_path / "workspaces")
    client = TestClient(app)
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    r = client.post(
        f"/api/workspaces/{ws_id}/imports/inspect", json={"source": str(tmp_path / "data")}
    )
    assert r.status_code == 200 and r.json()["kind"] == "nifti" and r.json()["count"] == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    bad = client.post(f"/api/workspaces/{ws_id}/imports/inspect", json={"source": str(empty)})
    assert bad.status_code == 400 and bad.json()["code"] == "IMPORT_SOURCE_EMPTY"


def test_fieldmap_echoes_stay_together_and_are_written(ws: Workspace, tmp_path: Path) -> None:
    root = tmp_path / "fm"
    mag = ["ORIGINAL", "PRIMARY", "M", "NONE", "MAGNITUDE"]
    base = {"SeriesDescription": "fmap"}
    write(
        root,
        "m_e1",
        (6, 6, 6),
        {**base, "SeriesNumber": 4, "EchoNumber": 1, "EchoTime": 0.005, "ImageType": mag},
    )
    write(
        root,
        "m_e2",
        (6, 6, 6),
        {**base, "SeriesNumber": 4, "EchoNumber": 2, "EchoTime": 0.0074, "ImageType": mag},
    )
    write(root, "p_e2_ph", (6, 6, 6), {**base, "SeriesNumber": 5, "EchoNumber": 2, "EchoTime": 0.0074,
                                       "ImageType": ["ORIGINAL", "PRIMARY", "P", "NONE", "PHASE"]})  # fmt: skip
    write(root, "t1", (8, 8, 70), {"SeriesDescription": "t1_mprage", "SeriesNumber": 2})
    _scan(ws, {"source": str(root)}, lambda _m: None)
    manifest = load_manifest(ws)
    kinds = {
        s.number: c.kind
        for s, c in zip(
            manifest.series, effective_all(manifest, load_rules(ws)).values(), strict=True
        )
    }
    assert kinds[4] == "fieldmap-magnitude" and kinds[5] == "fieldmap-phase"
    _import_run(ws, {"import_id": manifest.id}, lambda _m: None)
    fmap = ws.root / "rawbids" / "sub-001" / "fmap"
    for name in ("magnitude1", "magnitude2", "phasediff"):
        assert (fmap / f"sub-001_{name}.nii.gz").is_file()
