"""Diffusion processing for one subject: what data exists, and the choices the user can make.

The stage itself (``DiffusionStage`` in ``processing.py``) turns these into separate steps. This
module only looks at the raw data: for every diffusion series it finds the b-value, b-vector and
metadata files and, if there is one, an image with the opposite phase-encoding direction (a
field map of type ``epi`` or a second diffusion series), as ``alps.sh`` expects.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mrforge.datafiles import subject_data
from mrforge.steps.dwi_common import (
    EncodingError,
    opposite,
    read_encoding,
    reverse_encoding,
    starts_with_b0,
    topup_problem,
)
from mrforge.steps.sidecar import read_sidecar
from mrforge.workspace import Workspace


class DiffusionOptions(BaseModel):
    """The choices of the diffusion stage. Defaults are those of ``alps.sh`` unless noted."""

    # MRtrix3 steps; used only when MRtrix3 is installed (the plan says when it is skipped).
    denoise: bool = True
    unring: bool = True
    # Distortion correction with TOPUP; used only when an opposite-direction image exists.
    topup: bool = True
    # REVIEW(domain): Philips axes carry no sign, so two Philips images look alike. True =
    # the second image is taken as the opposite direction.
    second_is_opposite: bool = False
    # Eddy-current and motion correction: an eddy program of the FSL folder, or "none".
    eddy: str = "eddy_cpu"
    eddy_threads: int | None = Field(default=None, ge=1)  # None: the Settings resource policy
    # "native": the index is measured in the person's own space; otherwise the maps are moved
    # to a template first (script default: linear, JHU-FA).
    registration: Literal["native", "linear", "fnirt", "linear_fnirt"] = "linear"
    # Registration through the person's T1 (to MNI) or T2 (to the JHU T2 template); the
    # registration choice above is then ignored (as in the script).
    structural: Literal["none", "t1", "t2"] = "none"
    template: Literal["default", "jhu_fa", "mni_t1", "jhu_t2"] = "default"
    # REVIEW(domain): the script moves the tensor with flirt (default) which does not rotate it;
    # vecreg does.
    tensor_method: Literal["flirt", "vecreg"] = "flirt"
    roi_source: Literal["default", "legacy5", "sphere", "custom"] = "default"
    roi_radius_mm: float = Field(default=2.5, gt=0, le=20)
    custom_rois: list[str] = []  # four workspace-relative files for roi_source "custom"
    # Reproduce the script's rounding of ROI means (fslstats prints 6 decimals).
    round_like_script: bool = False


class DiffusionRun(BaseModel):
    """One diffusion series with its companion files."""

    relpath: str
    bval: str | None
    bvec: str | None
    sidecar: str | None
    shape: list[int] | None
    problem: str | None = None  # why this series cannot be processed
    # Opposite phase-encoding image (3D or 4D) with its metadata, for TOPUP.
    reverse: str | None = None
    reverse_json: str | None = None
    reverse_bval: str | None = None
    reverse_from: str | None = None  # "field map" or "second diffusion series"
    topup_note: str | None = None  # why TOPUP is not possible, or None


def _companion(relpath: str, ending: str) -> str:
    return relpath.removesuffix(".nii.gz") + ending


def _exists(ws: Workspace, rel: str) -> bool:
    return ws.abspath(rel).is_file()


def _intended(side: dict[str, object], dwi_rel: str) -> bool:
    target = side.get("IntendedFor")
    items = [target] if isinstance(target, str) else (target if isinstance(target, list) else [])
    return any(isinstance(t, str) and t.endswith(dwi_rel.rsplit("/", 1)[-1]) for t in items)


def _reverse_candidates(ws: Workspace, subject: str, main_rel: str) -> list[tuple[str, str]]:
    """(image, where it comes from): field maps of type epi first, then other diffusion series."""
    files = subject_data(ws, subject).files
    found: list[tuple[str, str]] = []
    epi = [f for f in files if f.datatype == "fmap" and f.suffix == "epi"]
    # Field maps that list this series in IntendedFor come before the rest.
    epi.sort(key=lambda f: 0 if _intended(read_sidecar(ws, f.relpath), main_rel) else 1)
    found += [(f.relpath, "field map") for f in epi]
    found += [
        (f.relpath, "second diffusion series")
        for f in files
        if f.datatype == "dwi" and f.suffix == "dwi" and f.relpath != main_rel
    ]
    return found


def diffusion_runs(
    ws: Workspace, subject: str, second_is_opposite: bool = False
) -> list[DiffusionRun]:
    """Every diffusion series of the subject, with what is known about processing it."""
    runs: list[DiffusionRun] = []
    for f in subject_data(ws, subject).files:
        if f.datatype != "dwi" or f.suffix != "dwi":
            continue
        bval = _companion(f.relpath, ".bval")
        bvec = _companion(f.relpath, ".bvec")
        sidecar = _companion(f.relpath, ".json")
        run = DiffusionRun(
            relpath=f.relpath,
            bval=bval if _exists(ws, bval) else None,
            bvec=bvec if _exists(ws, bvec) else None,
            sidecar=sidecar if _exists(ws, sidecar) else None,
            shape=f.shape,
        )
        if run.bval is None or run.bvec is None:
            run.problem = "The b-value or b-vector file (.bval / .bvec) is missing."
        elif f.shape is not None and len(f.shape) != 4:
            run.problem = "The diffusion image is not a 4D series."
        _find_reverse(ws, subject, run, second_is_opposite)
        runs.append(run)
    return runs


def _find_reverse(ws: Workspace, subject: str, run: DiffusionRun, assume_opposite: bool) -> None:
    if run.sidecar is None:
        run.topup_note = "no metadata (JSON) file with the phase-encoding direction"
        return
    try:
        main = read_encoding(read_sidecar(ws, run.relpath))
    except EncodingError as error:
        run.topup_note = str(error).rstrip(".").lower()
        return
    reasons: list[str] = []
    for rel, origin in _reverse_candidates(ws, subject, run.relpath):
        side_json = _companion(rel, ".json")
        has_json = _exists(ws, side_json)
        try:
            other = (
                reverse_encoding(main, read_sidecar(ws, rel), assume_opposite=assume_opposite)
                if has_json
                else None
            )
        except EncodingError:
            continue
        direction = other.direction if other else opposite(main.direction)
        if direction != opposite(main.direction):
            reasons.append(
                "the other image has the same phase-encoding direction"
                if origin == "second diffusion series"
                else "the field map has the same phase-encoding direction"
            )
            continue
        rev_bval = _companion(rel, ".bval")
        bval_text = ws.abspath(rev_bval).read_text() if _exists(ws, rev_bval) else None
        main_bval = ws.abspath(run.bval).read_text() if run.bval else None
        if other is not None:
            problem = topup_problem(
                main, other, starts_with_b0(main_bval), starts_with_b0(bval_text)
            )
            if problem:
                reasons.append(problem)
                continue
        elif not (starts_with_b0(main_bval) and starts_with_b0(bval_text)):
            reasons.append("both images must start with a b = 0 volume")
            continue
        run.reverse = rel
        run.reverse_json = side_json if has_json else None
        run.reverse_bval = rev_bval if bval_text is not None else None
        run.reverse_from = origin
        return
    run.topup_note = (
        reasons[0] if reasons else "no image with the opposite phase-encoding direction"
    )
