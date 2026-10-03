"""Step registry: name -> Step class."""

from __future__ import annotations

from typing import Any, TypeVar

from mrforge.errors import StepError
from mrforge.steps.base import Step

_REGISTRY: dict[str, type[Step[Any, Any, Any]]] = {}

T = TypeVar("T", bound=type[Step[Any, Any, Any]])


def register_step(cls: T) -> T:
    """Class decorator that registers a Step under ``cls.name``."""
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"A different step named '{cls.name}' is already registered")
    _REGISTRY[cls.name] = cls
    return cls


def get_step(name: str) -> Step[Any, Any, Any]:
    try:
        return _REGISTRY[name]()
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise StepError(
            code="UNKNOWN_STEP",
            message=f"There is no step called '{name}'.",
            probable_cause="The step name is misspelled or the step does not exist.",
            suggested_action=f"Use one of: {known}.",
        ) from None


def list_steps() -> list[str]:
    return sorted(_REGISTRY)
