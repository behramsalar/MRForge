"""Stage 7e: presets, a named bundle of the full-processing choices."""

from pathlib import Path

import pytest
from test_processing import workspace as processing_workspace

from mrforge import presets
from mrforge.errors import StepError
from mrforge.models import PipelineRun
from mrforge.overview import build_overview
from mrforge.presets import PresetOptions
from mrforge.processing import ArtifactOptions, FullOptions, FunctionalOptions, plan_full_processing


@pytest.fixture(autouse=True)
def own_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MRFORGE_CONFIG", str(tmp_path / "config.json"))


def test_two_built_in_presets_come_with_the_program() -> None:
    names = [p.name for p in presets.list_presets()]
    assert names[:2] == ["Standard preprocessing", "With ICA-AROMA (automatic)"]
    aroma = presets.list_presets()[1]
    assert (
        aroma.builtin
        and aroma.options.artifact.mode == "aroma_auto"
        and aroma.options.stages == {"artifact_rejection": True}
    )


def test_a_preset_can_be_saved_found_again_replaced_and_deleted() -> None:
    options = PresetOptions(
        functional=FunctionalOptions(smoothing_fwhm_mm=6.0, highpass_cutoff_s=None)
    )
    saved = presets.save_preset("My lab: 6 mm", "for the pilot", options)
    assert saved.id == "my-lab-6-mm" and not saved.builtin
    found = [p for p in presets.list_presets() if p.id == saved.id][0]
    assert (
        found.options.functional.smoothing_fwhm_mm == 6.0
        and found.options.functional.highpass_cutoff_s is None
    )
    presets.save_preset("My lab: 6 mm", "changed", PresetOptions())  # same name replaces it
    assert [p.description for p in presets.list_presets() if p.id == saved.id] == ["changed"]
    presets.delete_preset(saved.id)
    assert all(p.id != saved.id for p in presets.list_presets())


def test_built_in_presets_cannot_be_replaced_or_deleted() -> None:
    with pytest.raises(StepError) as taken:
        presets.save_preset("Standard preprocessing", "", PresetOptions())
    assert taken.value.code == "PRESET_NAME_TAKEN"
    with pytest.raises(StepError) as builtin:
        presets.delete_preset("standard")
    assert builtin.value.code == "PRESET_BUILTIN"
    with pytest.raises(StepError):
        presets.save_preset("  ", "", PresetOptions())


def test_the_standard_preset_is_what_the_dialog_starts_with(tmp_path: Path) -> None:
    ws = processing_workspace(tmp_path, volumes=45)
    standard = presets.list_presets()[0].options
    plain, spec_a = plan_full_processing(ws, FullOptions(subject="sub-001"))
    from_preset, spec_b = plan_full_processing(
        ws,
        FullOptions(
            subject="sub-001",
            stages=standard.stages,
            anatomical=standard.anatomical,
            functional=standard.functional,
            artifact=standard.artifact,
        ),
    )
    assert [s.step for s in spec_a.steps] == [s.step for s in spec_b.steps]  # type: ignore[union-attr]


def test_the_name_of_the_preset_is_kept_with_the_run_and_shown_for_the_subject(
    tmp_path: Path,
) -> None:
    ws = processing_workspace(tmp_path, volumes=45)
    opts = FullOptions(
        subject="sub-001",
        preset="With ICA-AROMA (automatic)",
        stages={"artifact_rejection": True},
        artifact=ArtifactOptions(mode="manual"),
    )
    _, spec = plan_full_processing(ws, opts)
    assert spec is not None and spec.preset == "With ICA-AROMA (automatic)"
    with ws.session() as s:
        s.add(PipelineRun(name=spec.name, spec=spec.model_dump(mode="json")))
    [row] = build_overview(ws).subjects
    assert row.preset == "With ICA-AROMA (automatic)"


def test_presets_through_the_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from mrforge.api.app import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert [p["id"] for p in client.get("/api/presets").json()][:2] == [
        "standard",
        "aroma-automatic",
    ]
    body = {
        "name": "Quick look",
        "description": "6 mm",
        "options": {"functional": {"smoothing_fwhm_mm": 6.0}},
    }
    created = client.post("/api/presets", json=body).json()
    assert (
        created["id"] == "quick-look"
        and created["options"]["functional"]["smoothing_fwhm_mm"] == 6.0
    )
    assert client.delete("/api/presets/quick-look").json() == {"ok": True}
    refused = client.delete("/api/presets/standard")
    assert refused.status_code >= 400 and refused.json()["code"] == "PRESET_BUILTIN"
