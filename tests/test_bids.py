import json
from pathlib import Path

import pytest

from mrforge import bids
from mrforge.bids import bids_name, inherited_entities, parse_bids_name, split_extension
from mrforge.workspace import Workspace, WorkspaceError


def test_split_extension() -> None:
    assert split_extension("sub-01_T1w.nii.gz") == ("sub-01_T1w", ".nii.gz")
    assert split_extension("sub-01_T1w.nii") == ("sub-01_T1w", ".nii")
    assert split_extension("x_xfm.mat") == ("x_xfm", ".mat")


def test_parse_bids_name() -> None:
    entities, suffix, ext = parse_bids_name(
        "rawbids/sub-001/ses-01/anat/sub-001_ses-01_run-2_T1w.nii.gz"
    )
    assert entities == {"sub": "001", "ses": "01", "run": "2"}
    assert suffix == "T1w" and ext == ".nii.gz"
    assert parse_bids_name("t1w.nii.gz") == ({}, "t1w", ".nii.gz")
    assert parse_bids_name("my scan (1).nii.gz")[:2] == ({}, None)


def test_bids_name_orders_entities_correctly() -> None:
    name = bids_name(
        {"desc": "brain", "run": "2", "space": "MNI152NLin6Asym", "ses": "01", "sub": "001"},
        "T1w",
    )
    assert name == "sub-001_ses-01_run-2_space-MNI152NLin6Asym_desc-brain_T1w.nii.gz"
    xfm = bids_name(
        {"sub": "001", "mode": "image", "to": "MNI", "from": "T1w", "desc": "field"}, "xfm"
    )
    assert xfm == "sub-001_from-T1w_to-MNI_mode-image_desc-field_xfm.nii.gz"


def test_entity_values_are_made_alphanumeric() -> None:
    assert bids_name({"sub": "001", "desc": "fsl_anat"}, "fake", ".txt") == (
        "sub-001_desc-fslanat_fake.txt"
    )


def test_inherited_entities() -> None:
    got = inherited_entities(
        "sub-007", "ses-02", "rawbids/x/sub-001_acq-hi_run-3_desc-old_T1w.nii.gz"
    )
    # sub/ses come from the workspace; acq/run are carried over; desc describes processing
    assert got == {"sub": "007", "ses": "02", "acq": "hi", "run": "3"}
    assert inherited_entities("sub-001", None, "t1w.nii.gz") == {"sub": "001"}
    assert inherited_entities("sub-001", None, None) == {"sub": "001"}


def test_workspace_creates_a_bids_derivatives_dataset(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "w")
    desc = json.loads((ws.derivatives_dir / "dataset_description.json").read_text())
    assert desc["DatasetType"] == "derivative" and desc["BIDSVersion"] == bids.BIDS_VERSION
    assert desc["GeneratedBy"][0]["Name"] == "MRForge"
    ignore = (ws.derivatives_dir / ".bidsignore").read_text().split()
    assert "_runs/" in ignore and "*.anat/" in ignore


def test_tool_versions_are_added_once(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "w")
    for _ in range(2):
        bids.record_tool_versions(ws.derivatives_dir, {"mrforge": "0.0.0", "fsl": "6.0.7.23"})
    generated = json.loads((ws.derivatives_dir / "dataset_description.json").read_text())[
        "GeneratedBy"
    ]
    assert [g["Name"] for g in generated] == ["MRForge", "FSL"]
    assert generated[1]["Version"] == "6.0.7.23"


def test_old_layout_workspace_is_refused_in_plain_language(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "w")
    meta = ws.root / "workspace.json"
    data = json.loads(meta.read_text())
    data["schema_version"] = 1
    meta.write_text(json.dumps(data))
    with pytest.raises(WorkspaceError, match="Create a new workspace"):
        Workspace.open(ws.root)
