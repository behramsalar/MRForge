"""Processing presets: a named bundle of the full-processing choices.

A preset is the settings of the confirmation dialog (which stages, smoothing, drift filter,
who labels the components, ...) without the subject. Two built-in presets come with MRForge;
researchers can save their own from the dialog. They are kept per computer with the other
settings (``config.json``), so everyone who uses this computer sees them. Choosing a preset
only fills in the dialog; what runs is still shown and confirmed, and the preset's name is
recorded with the run.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from mrforge.config import load_config, save_config
from mrforge.errors import StepError
from mrforge.processing import AnatomicalOptions, ArtifactOptions, FunctionalOptions


class PresetOptions(BaseModel):
    stages: dict[str, bool] = {}
    anatomical: AnatomicalOptions = AnatomicalOptions()
    functional: FunctionalOptions = FunctionalOptions()
    artifact: ArtifactOptions = ArtifactOptions()


class Preset(BaseModel):
    id: str
    name: str
    description: str
    builtin: bool = False
    options: PresetOptions


BUILTIN: list[Preset] = [
    Preset(
        id="standard",
        name="Standard preprocessing",
        description=(
            "The recommended settings: anatomical processing, functional preprocessing and "
            "standard space, without artifact rejection."
        ),
        builtin=True,
        options=PresetOptions(),
    ),
    Preset(
        id="aroma-automatic",
        name="With ICA-AROMA (automatic)",
        description=(
            "As standard, plus artifact rejection: ICA-AROMA labels the components and the "
            "noise is removed without pausing for you (needs ICA-AROMA installed)."
        ),
        builtin=True,
        options=PresetOptions(
            stages={"artifact_rejection": True}, artifact=ArtifactOptions(mode="aroma_auto")
        ),
    ),
]


def _saved() -> list[Preset]:
    out: list[Preset] = []
    for raw in load_config().get("presets", []) or []:
        try:
            out.append(Preset.model_validate(raw))
        except ValueError:
            continue
    return out


def list_presets() -> list[Preset]:
    return [*BUILTIN, *_saved()]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "preset"


def save_preset(name: str, description: str, options: PresetOptions) -> Preset:
    name = name.strip()
    if not name:
        raise StepError(
            "PRESET_NAME_REQUIRED",
            "Please give the preset a name.",
            suggested_action="Type a short name you will recognise.",
        )
    taken = {p.id for p in BUILTIN} | {p.name.lower() for p in BUILTIN}
    if _slug(name) in taken or name.lower() in taken:
        raise StepError(
            "PRESET_NAME_TAKEN",
            "A built-in preset already has this name.",
            suggested_action="Choose another name.",
        )
    saved = [p for p in _saved() if p.id != _slug(name)]  # saving again replaces your own
    preset = Preset(id=_slug(name), name=name, description=description.strip(), options=options)
    config = load_config()
    config["presets"] = [p.model_dump() for p in [*saved, preset]]
    save_config(config)
    return preset


def delete_preset(preset_id: str) -> None:
    if any(p.id == preset_id for p in BUILTIN):
        raise StepError(
            "PRESET_BUILTIN",
            "A built-in preset cannot be deleted.",
            suggested_action="Delete only presets you saved yourself.",
        )
    config = load_config()
    config["presets"] = [p.model_dump() for p in _saved() if p.id != preset_id]
    save_config(config)
