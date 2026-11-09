"""ROI-to-ROI correlation matrices from the time series of ``roi_timeseries``.

Pearson correlation between the mean time series of every pair of regions, and its Fisher z
transform. Pure numpy; no FSL. The two matrices are written as plain numbers only (N x N, no
name row or column, ``%.8f``), the format NBS-type tools read directly; the order of the regions
is that of the time-series header and of the ``..._roi.json`` next to it.

Choices (the lab's own scripts compute the same, with two differences noted here):
- A region whose time series is missing (no voxel with signal) or constant gets NaN in its row
  and column. The scripts do the same, except that they give a constant series 1 on its own
  diagonal cell; here that cell is NaN too (a constant series has no correlation). Constant
  series cannot occur with signal-only averaging.
- REVIEW(domain): Fisher z is ``arctanh`` of r clipped to +-0.999999 (as in the scripts), but
  the diagonal of z is 0, not ``arctanh(0.999999)`` = 7.25. That value is an artefact of the
  clip: the true value is infinite. The r matrix keeps 1 on its diagonal.
- The scripts compute a pair's correlation over the volumes where both series are valid; a
  region with any missing volume is treated here as missing as a whole. fslmeants never gives a
  partly missing series, so the results are the same.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.fsl_anat import STANDARD_SPACE
from mrforge.steps.registry import register_step

FISHER_CLIP = 0.999999  # as in the lab's scripts


class RoiCorrelationInput(BaseModel):
    timeseries: str  # from roi_timeseries: header = region names, one row per volume


class RoiCorrelationParams(BaseModel):
    fisher_clip: float = FISHER_CLIP
    z_diagonal: float = 0.0  # REVIEW(domain): see the module text
    min_volumes: int = 3  # fewer volumes than this: no correlation (as in the scripts)


class RoiCorrelationOutput(BaseModel):
    r_matrix: str  # Pearson r, plain numbers
    z_matrix: str  # Fisher z, plain numbers
    info: str  # JSON: settings, region order, counts


def read_timeseries(path: Path) -> tuple[list[str], np.ndarray[Any, Any]]:
    """The header names and the values (volumes x regions) of a time-series file."""
    with path.open() as f:
        header = f.readline().rstrip("\n").split("\t")
        rows = [[float(x) for x in line.rstrip("\n").split("\t")] for line in f if line.strip()]
    values = np.array(rows, dtype=np.float64).reshape(len(rows), len(header))
    return header, values


def pearson(values: np.ndarray[Any, Any], min_volumes: int = 3) -> np.ndarray[Any, Any]:
    """Pearson r between the columns. Columns with a missing volume, or without variation, give
    NaN in their row and column; valid columns have exactly 1 on the diagonal."""
    t, n = values.shape
    r = np.full((n, n), np.nan)
    if t < min_volumes:
        return r
    ok = np.flatnonzero(~np.isnan(values).any(axis=0))
    sub = values[:, ok] - values[:, ok].mean(axis=0, keepdims=True)
    norm = np.sqrt((sub**2).sum(axis=0))
    varying = norm > 0
    idx = ok[varying]
    if idx.size:
        unit = sub[:, varying] / norm[varying]
        r[np.ix_(idx, idx)] = np.clip(unit.T @ unit, -1.0, 1.0)
        r[idx, idx] = 1.0
    return r


def fisher_z(
    r: np.ndarray[Any, Any], clip: float = FISHER_CLIP, diagonal: float = 0.0
) -> np.ndarray[Any, Any]:
    """arctanh of r clipped to +-clip; the diagonal of valid regions is set to ``diagonal``."""
    z: np.ndarray[Any, Any] = np.arctanh(np.clip(r, -clip, clip))
    diag = np.diag_indices_from(r)
    ok = ~np.isnan(r[diag])
    z[diag[0][ok], diag[1][ok]] = diagonal
    return z


def write_matrix(path: Path, matrix: np.ndarray[Any, Any]) -> None:
    """Plain numbers, whitespace separated, ``%.8f`` (the lab's NBS text format); NaN as 'nan'."""
    np.savetxt(path, matrix, fmt="%.8f")


@register_step
class RoiCorrelationStep(Step[RoiCorrelationInput, RoiCorrelationParams, RoiCorrelationOutput]):
    name = "roi_correlation"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = (
        RoiCorrelationInput,
        RoiCorrelationParams,
        RoiCorrelationOutput,
    )
    requires_fsl = False
    datatype = "func"

    def expected_outputs(
        self, ctx: StepContext[RoiCorrelationInput, RoiCorrelationParams]
    ) -> RoiCorrelationOutput:
        n = ctx.bids_name  # sub, task, run and seg-<atlas> come from the time-series name
        e = {"space": STANDARD_SPACE}
        return RoiCorrelationOutput(
            r_matrix=n("relmat", ".txt", **e, stat="pearsoncorrelation"),
            z_matrix=n("relmat", ".txt", **e, stat="fisherz"),
            info=n("relmat", ".json", **e, stat="pearsoncorrelation"),
        )

    def validate_inputs(
        self, ctx: StepContext[RoiCorrelationInput, RoiCorrelationParams]
    ) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        try:
            header, values = read_timeseries(ctx.input_path(ctx.inputs.timeseries))
        except (ValueError, OSError):
            return [
                Problem(
                    code="TIMESERIES_UNREADABLE",
                    message="The time-series file could not be read.",
                    probable_cause="The file is damaged or was not made by the extraction step.",
                    suggested_action="Run the time-series extraction again.",
                )
            ]
        if len(header) < 2 or values.shape[0] < ctx.params.min_volumes:
            return [
                Problem(
                    code="TIMESERIES_TOO_SHORT",
                    message=(
                        f"The file has {len(header)} region(s) and {values.shape[0]} volume(s); "
                        f"at least 2 regions and {ctx.params.min_volumes} volumes are needed."
                    ),
                    probable_cause="The extraction did not finish properly, or the run is tiny.",
                    suggested_action="Run the time-series extraction again on the full run.",
                )
            ]
        return []

    def run(self, ctx: StepContext[RoiCorrelationInput, RoiCorrelationParams]) -> StepResult:
        p = ctx.params
        out = self.expected_outputs(ctx)
        header, values = read_timeseries(ctx.input_path(ctx.inputs.timeseries))
        r = pearson(values, p.min_volumes)
        z = fisher_z(r, p.fisher_clip, p.z_diagonal)
        write_matrix(ctx.output_dir / out.r_matrix, r)
        write_matrix(ctx.output_dir / out.z_matrix, z)
        off = ~np.eye(len(header), dtype=bool) & ~np.isnan(r)
        info = {
            "input": ctx.inputs.timeseries,
            "regions": header,
            "volumes": int(values.shape[0]),
            "method": "Pearson correlation between the mean time series of every pair of regions",
            "fisher_z": {
                "transform": "arctanh(clip(r))",
                "clip": p.fisher_clip,
                "diagonal": p.z_diagonal,
            },  # fmt: skip
            "format": "plain numbers, N x N, %.8f, no name row or column; order = regions",
            "n_regions_without_values": int(np.isnan(np.diag(r)).sum()),
            "n_pairs": int(off.sum() // 2),
            "n_pairs_clipped": int((np.abs(r[off]) > p.fisher_clip).sum() // 2),
            "mean_r": float(r[off].mean()) if off.any() else None,
            "mean_z": float(z[off].mean()) if off.any() else None,
        }
        (ctx.output_dir / out.info).write_text(json.dumps(info, indent=2) + "\n")
        return StepResult()

    def validate_outputs(
        self, ctx: StepContext[RoiCorrelationInput, RoiCorrelationParams]
    ) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        out = self.expected_outputs(ctx)
        n = len(json.loads((ctx.output_dir / out.info).read_text())["regions"])
        for field_name, rel in (("r", out.r_matrix), ("z", out.z_matrix)):
            m = np.loadtxt(ctx.output_dir / rel, ndmin=2)
            if m.shape != (n, n) or not np.allclose(m, m.T, equal_nan=True):
                return [
                    Problem(
                        code="MATRIX_UNEXPECTED",
                        message=f"The {field_name} matrix is not a symmetric {n} x {n} table.",
                        probable_cause="The calculation finished with an unexpected result.",
                        suggested_action="Open the raw log, then run the step again.",
                    )
                ]
        return []

    def generate_qc(
        self, ctx: StepContext[RoiCorrelationInput, RoiCorrelationParams]
    ) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        info = json.loads((ctx.output_dir / out.info).read_text())
        missing = info["n_regions_without_values"]
        return [
            QCItem(
                name="Regions without a correlation (no signal or no variation)",
                kind="metric",
                value=f"{missing} of {len(info['regions'])}",
                warning=(
                    f"{missing} region(s) have no usable time series; their rows and columns "
                    "are 'nan'. Tools that read the matrix must handle that."
                )
                if missing
                else None,
            ),
            QCItem(
                name="Mean correlation between regions (r)",
                kind="metric",
                value=None if info["mean_r"] is None else f"{info['mean_r']:.3f}",
            ),
        ]
