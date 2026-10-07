"""After Stage 7: a folder that holds several subjects' scans becomes one import per scan."""

import tarfile
from pathlib import Path

import pytest
from dicomfactory import SECRET_ID, SECRET_NAME, make_dicom, new_uid

from mrforge.errors import StepError
from mrforge.importing.manifest import list_manifests
from mrforge.importing.scan import scan_group, scan_source
from mrforge.workspace import Workspace


def make_study(root: Path, study_uid: str, t1_number: int = 501, with_bold: bool = True) -> None:
    """One scan: a 3-slice T1 and optionally a 3-slice x 4-volume BOLD run. Every study uses
    the same series numbers, as real sessions do."""
    t1, bold = new_uid(), new_uid()
    for z in range(3):
        make_dicom(
            root / f"t1_{z}.dcm", t1, t1_number, "t1w", position_z=float(z), study_uid=study_uid
        )
    if with_bold:
        for vol in range(4):
            for z in range(3):
                make_dicom(root / f"bold_{vol}_{z}.dcm", bold, 401, "ep2d_bold_moco_p2",
                           image_type=("ORIGINAL", "PRIMARY", "FMRI", "NONE"), position_z=float(z), study_uid=study_uid)  # fmt: skip


@pytest.fixture
def several(tmp_path: Path) -> Path:
    root = tmp_path / "study"
    for name in ("1", "2", "3"):
        make_study(root / name / "PATIENT" / "20170101", new_uid(), with_bold=name != "2")
    return root


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


def test_each_scan_in_a_folder_becomes_its_own_import_with_its_own_subject(
    several: Path, ws: Workspace
) -> None:
    manifests, is_new = scan_group(ws, several)
    assert is_new and len(manifests) == 3
    assert [m.subject for m in manifests] == ["sub-001", "sub-002", "sub-003"]  # folder order
    assert [(m.group.index, m.group.of) for m in manifests if m.group] == [(1, 3), (2, 3), (3, 3)]
    # The same series numbers in every scan do not clash: each import has its own series.
    assert [sorted(s.number or 0 for s in m.series) for m in manifests] == [
        [401, 501],
        [501],
        [401, 501],
    ]
    assert [m.id for m in list_manifests(ws)] == ["import-001", "import-002", "import-003"]


def test_the_files_of_each_scan_are_copied_apart_and_the_source_is_untouched(
    several: Path, ws: Workspace
) -> None:
    before = sorted(p.relative_to(several) for p in several.rglob("*") if p.is_file())
    manifests, _ = scan_group(ws, several)
    assert sorted(p.relative_to(several) for p in several.rglob("*") if p.is_file()) == before
    counts = [sum(1 for p in (ws.root / m.dicom_dir).rglob("*") if p.is_file()) for m in manifests]
    assert counts == [15, 3, 15]  # 3 T1 + 12 BOLD, 3 T1, 3 T1 + 12 BOLD
    assert "2" in {
        part
        for p in (ws.root / manifests[1].dicom_dir).rglob("*")
        if p.is_file()
        for part in p.parts
    }  # structure kept


def test_scanning_the_same_folder_again_finds_the_same_imports(
    several: Path, ws: Workspace
) -> None:
    first, _ = scan_group(ws, several)
    again, is_new = scan_group(ws, several)
    assert not is_new and [m.id for m in again] == [m.id for m in first]
    assert len(list_manifests(ws)) == 3  # nothing was added


def test_nothing_that_identifies_a_study_or_a_person_is_stored(
    tmp_path: Path, ws: Workspace
) -> None:
    root = tmp_path / "ids"
    uids = [new_uid(), new_uid()]
    for i, uid in enumerate(uids):
        make_study(root / str(i), uid)
    manifests, _ = scan_group(ws, root)
    for m, uid in zip(manifests, uids, strict=True):
        text = m.model_dump_json()
        assert SECRET_NAME not in text and SECRET_ID not in text
        assert uid not in text and m.group and len(m.group.study) == 12  # only a short hash
        assert (
            uid not in (ws.root / "imports" / m.id / "manifest.json").read_text()
            if (ws.root / "imports" / m.id / "manifest.json").exists()
            else True
        )


def test_a_source_with_one_scan_still_gives_one_import_exactly_as_before(
    tmp_path: Path, ws: Workspace
) -> None:
    root = tmp_path / "one"
    make_study(root / "A", new_uid())
    manifests, is_new = scan_group(ws, root)
    assert is_new and len(manifests) == 1 and manifests[0].group is None
    assert manifests[0].subject == "sub-001"
    again, is_new2 = scan_group(ws, root)
    assert not is_new2 and again[0].id == manifests[0].id


def test_one_label_cannot_be_given_to_several_scans(several: Path, ws: Workspace) -> None:
    with pytest.raises(StepError) as err:
        scan_group(ws, several, subject="sub-007")
    assert err.value.code == "IMPORT_LABELS_FOR_SEVERAL" and "3 scans" in err.value.message
    assert list_manifests(ws) == []  # nothing was left behind


def test_an_archive_with_several_scans_is_split_the_same_way(
    several: Path, ws: Workspace, tmp_path: Path
) -> None:
    archive = tmp_path / "all.tar.bz2"
    with tarfile.open(archive, "w:bz2") as tf:
        tf.add(several, arcname="all")
    manifests, _ = scan_group(ws, archive)
    assert [m.subject for m in manifests] == ["sub-001", "sub-002", "sub-003"]
    assert all(m.source.kind == "tar" for m in manifests)
    assert not (ws.root / "sourcedata" / "dicom" / ".staging").exists()  # staging is cleaned up


def test_removed_copies_come_back_from_the_original(several: Path, ws: Workspace) -> None:
    import shutil
    from datetime import UTC, datetime

    from mrforge.importing.manifest import save_manifest

    manifests, _ = scan_group(ws, several)
    for m in manifests:  # what removing the DICOM copy does
        shutil.rmtree(ws.root / m.dicom_dir)
        m.dicom_removed = datetime.now(UTC)
        save_manifest(ws, m)
    again, is_new = scan_group(ws, several)
    assert not is_new and all(m.dicom_removed is None for m in again)
    counts = [sum(1 for p in (ws.root / m.dicom_dir).rglob("*") if p.is_file()) for m in again]
    assert counts == [15, 3, 15]  # each copy holds only its own scan again


def test_scan_source_keeps_its_old_meaning_for_a_single_scan(tmp_path: Path, ws: Workspace) -> None:
    root = tmp_path / "x"
    make_study(root, new_uid())
    manifest, is_new = scan_source(ws, root)
    assert is_new and manifest.subject == "sub-001"


def test_the_labels_of_a_scan_can_be_changed_until_it_is_imported(
    several: Path, ws: Workspace
) -> None:
    from mrforge.importing.manifest import load_manifest
    from mrforge.importing.scan import set_labels

    manifests, _ = scan_group(ws, several)
    set_labels(ws, manifests[0], "sub-ali", None)
    assert load_manifest(ws, "import-001").subject == "sub-ali"
    # Two scans of one subject need different sessions.
    with pytest.raises(StepError) as clash:
        set_labels(ws, manifests[1], "sub-ali", None)
    assert clash.value.code == "IMPORT_LABELS_CLASH" and "import-001" in clash.value.message
    set_labels(ws, manifests[0], "sub-ali", "ses-01")
    set_labels(ws, manifests[1], "sub-ali", "ses-02")
    assert [load_manifest(ws, i).session for i in ("import-001", "import-002")] == [
        "ses-01",
        "ses-02",
    ]
    with pytest.raises(StepError) as bad:
        set_labels(ws, manifests[2], "subject three", None)
    assert bad.value.code == "BAD_SUBJECT_LABEL"


def test_labels_of_an_imported_scan_are_locked(several: Path, ws: Workspace) -> None:
    from mrforge.importing.models import OrganizedSeries
    from mrforge.importing.scan import set_labels

    manifests, _ = scan_group(ws, several)
    m = manifests[0]
    m.organized = {m.series[0].uid: OrganizedSeries(files={"rawbids/x.nii.gz": "a" * 64})}
    with pytest.raises(StepError) as err:
        set_labels(ws, m, "sub-009", None)
    assert err.value.code == "IMPORT_LABELS_LOCKED"


def test_import_all_that_are_ready_leaves_the_others_and_survives_a_failure(
    several: Path, ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mrforge import operations
    from mrforge.importing.classify import load_rules, set_override

    manifests, _ = scan_group(ws, several)
    rules = load_rules(ws)
    # Scan 1 and 3 have a BOLD run that waits for a task name; scan 2 (T1 only) is ready.
    waiting = [
        m.id
        for m in manifests
        if any(c.action == "ask" for c in operations.effective_all(m, rules).values())
    ]
    assert waiting == ["import-001", "import-003"]
    ran: list[str] = []

    def fake_run(ws_: Workspace, args: dict, log) -> dict:  # type: ignore[no-untyped-def]
        ran.append(args["import_id"])
        return {}

    monkeypatch.setattr(operations, "_import_run", fake_run)
    result = operations._import_run_all(
        ws, {"import_ids": [m.id for m in manifests]}, lambda line: None
    )
    assert ran == ["import-002"]
    assert {r["import_id"]: r["status"] for r in result["imports"]} == {
        "import-001": "needs-you",
        "import-002": "done",
        "import-003": "needs-you",
    }
    # Give both waiting scans their task: now all three are ready, and one failure does not stop the rest.
    for m in manifests:
        for s in m.series:
            if "task" in operations.effective_all(m, rules)[s.uid].needs:
                set_override(m, rules, None, entities={"task": "rest"}, uid=s.uid)
        operations.save_manifest(ws, m)

    def flaky(ws_: Workspace, args: dict, log) -> dict:  # type: ignore[no-untyped-def]
        if args["import_id"] == "import-001":
            raise StepError("CONVERSION_FAILED", "A series could not be converted.")
        ran.append(args["import_id"])
        return {}

    monkeypatch.setattr(operations, "_import_run", flaky)
    ran.clear()
    with pytest.raises(StepError) as err:
        operations._import_run_all(ws, {"import_ids": [m.id for m in manifests]}, lambda line: None)
    assert ran == ["import-002", "import-003"]  # the others were imported
    assert err.value.code == "IMPORTS_FAILED" and "import-001" in err.value.message
    statuses = {r["import_id"]: r["status"] for r in err.value.result["imports"]}  # type: ignore[attr-defined]
    assert statuses == {"import-001": "failed", "import-002": "done", "import-003": "done"}


def test_the_routes_for_scans_found_together(
    several: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from mrforge.api.app import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    ws_id = client.post("/api/workspaces", json={"name": "w"}).json()["id"]
    ws = Workspace.open(tmp_path / "workspaces" / ws_id)
    scan_group(ws, several)
    base = f"/api/workspaces/{ws_id}/imports"
    detail = client.get(f"{base}/import-002").json()
    assert (detail["group_index"], detail["group_size"]) == (2, 3) and detail["group_source"]
    changed = client.patch(
        f"{base}/import-002/labels", json={"subject": "sub-ali", "session": "ses-01"}
    )
    assert changed.status_code == 200 and changed.json()["subject"] == "sub-ali"
    clash = client.patch(
        f"{base}/import-003/labels", json={"subject": "sub-ali", "session": "ses-01"}
    )
    assert clash.status_code >= 400 and clash.json()["code"] == "IMPORT_LABELS_CLASH"
    task = client.post(
        f"{base}/set-task", json={"import_ids": ["import-001", "import-003"], "task": "rest"}
    ).json()
    assert [d["needs_input"] for d in task] == [0, 0]  # the waiting BOLD runs now have their task
    started = client.post(f"{base}/run-ready", json={"import_ids": ["import-001"]})
    assert started.status_code == 200 and "operation_id" in started.json()
