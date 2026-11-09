"""Where the results of earlier processing are, so that a stage can be run on its own.

The file names come from the steps themselves (``expected_outputs``), so they are written in
one place only. Nothing here checks that a result is still valid: the stage that uses it does
that when it runs (the resume rule).
"""

from __future__ import annotations

from typing import Any

from mrforge.runner.jobs import build_context
from mrforge.workspace import Workspace


def _outputs(
    ws: Workspace, step: str, subject: str, inputs: dict[str, str], label: str
) -> tuple[Any, str]:
    instance, ctx = build_context(ws, step, subject, None, inputs, {}, label)
    return instance.expected_outputs(ctx), ws.relpath(ctx.output_dir)


def existing_functional(ws: Workspace, subject: str, raw_bold: str) -> dict[str, str] | None:
    """FEAT's results for one recording (preprocessed image, brain mask, registration to the T1,
    motion), or None if any is missing."""
    dummy = {"bold": raw_bold, "t1_head": raw_bold, "t1_brain": raw_bold, "t1_seg": raw_bold}
    out, folder = _outputs(ws, "feat_preproc", subject, dummy, "feat_preproc")
    names = {
        "bold": out.preproc_bold,
        "brain_mask": out.brain_mask,
        "affine": out.to_t1_affine,
        "motion": out.motion,
    }
    found = {k: f"{folder}/{v}" for k, v in names.items() if v}
    if len(found) < 4 or not all(ws.abspath(p).is_file() for p in found.values()):
        return None
    return found


def existing_cleaned(ws: Workspace, subject: str, raw_bold: str) -> str | None:
    """The image with the noise components removed, if there is one."""
    dummy = {"bold": raw_bold, "mixing": raw_bold, "labels": raw_bold, "brain_mask": raw_bold}
    out, folder = _outputs(ws, "regfilt", subject, dummy, "regfilt")
    path = f"{folder}/{out.cleaned_bold}"
    return path if ws.abspath(path).is_file() else None


def existing_standard(
    ws: Workspace, subject: str, bold_rel: str, brain_mask_rel: str | None
) -> dict[str, str] | None:
    """The standard-space image of one recording (and its brain mask), made from ``bold_rel``
    by the standard-space step, or None if it has not been made. The names come from the step
    itself: the image is named for the data that went in (denoised or preprocessed)."""
    dummy = {
        "bold": bold_rel,
        "to_t1_affine": bold_rel,
        "t1_to_mni_warp": bold_rel,
        "brain_mask": brain_mask_rel,
    }
    out, folder = _outputs(ws, "func_to_mni", subject, dummy, "func_to_mni")  # type: ignore[arg-type]
    found = {"bold": f"{folder}/{out.bold_mni}"}
    if out.brain_mask_mni:
        found["brain_mask"] = f"{folder}/{out.brain_mask_mni}"
    return found if all(ws.abspath(p).is_file() for p in found.values()) else None
