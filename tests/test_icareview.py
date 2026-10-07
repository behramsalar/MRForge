"""Stage 6: the MELODIC results of a subject, as the review screen asks for them."""

import json
from pathlib import Path

from mrforge.icareview import find_ica_results
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001/func"


def fake_result(ws: Workspace, complete: bool = True) -> None:
    folder = ws.root / D / "sub-001_task-rest_desc-preproc_bold.ica" / "mrforge_report"
    folder.mkdir(parents=True)
    comps = []
    for n in (1, 2):
        files = {
            k: f"{D}/sub-001_task-rest_desc-preproc_bold.ica/mrforge_report/{k}-{n}.x"
            for k in ("map", "plots", "picture", "planes")
        }
        for rel in files.values():
            if complete or n == 1:
                (ws.root / rel).write_bytes(b"x")
        comps.append({"number": n, "variance_pct": 5.0 - n, "peak_mm": [1.0, 2.0, 3.0], **files})
    mean = f"{D}/sub-001_task-rest_desc-preproc_bold.ica/mrforge_report/mean.nii.gz"
    (ws.root / mean).write_bytes(b"x")
    summary = {"n_components": 2, "n_volumes": 100, "tr_s": 2.0, "mean": mean, "components": comps}
    (ws.root / D / "sub-001_task-rest_desc-melodic_components.json").write_text(json.dumps(summary))


def test_a_complete_result_is_listed(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    fake_result(ws)
    found = find_ica_results(ws, "ws", "sub-001")
    assert [r.recording for r in found] == ["task-rest"]
    r = found[0]
    assert (r.n_components, r.n_volumes, r.tr_s) == (2, 100, 2.0)
    assert r.components[0].map_url.startswith("/api/workspaces/ws/file/derivatives/")
    assert r.components[1].peak_mm == [1.0, 2.0, 3.0]


def test_a_result_with_missing_pictures_is_not_offered(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    fake_result(ws, complete=False)
    assert find_ica_results(ws, "ws", "sub-001") == []


def test_a_subject_without_components_has_none(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    assert find_ica_results(ws, "ws", "sub-001") == []
