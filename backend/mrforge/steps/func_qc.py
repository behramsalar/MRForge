"""Quality-control pictures and numbers for functional preprocessing.

QC flags; it never decides (CLAUDE.md principle 6). This step reports head motion and shows
the registration (and distortion correction) so that the researcher can judge them. Whether
to keep or exclude a subject is a separate, recorded decision (Stage 7).

* Motion: the six realignment parameters of FEAT's motion correction, a plot, and framewise
  displacement (Power et al. 2012: the sum of the absolute frame-to-frame changes of the three
  translations and of the three rotations expressed as arc length on a sphere of radius
  ``head_radius_mm``).
* Registration: the example volume in T1 space with the white-matter boundary drawn over it,
  and the T1 with the edges of the functional image drawn over it (FSL ``slicer``).
* Distortion correction (only when a fieldmap was used): the same picture before and after.
"""

from __future__ import annotations

import json
import math
import shutil
import statistics
from pathlib import Path

from pydantic import BaseModel, Field

from mrforge.errors import StepError
from mrforge.niftiutil import is_readable_nifti
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.feat_preproc import WM_LABEL
from mrforge.steps.qcpics import slice_row, stack_rows
from mrforge.steps.registry import register_step

MOTION_COLUMNS = ["rot_x", "rot_y", "rot_z", "trans_x", "trans_y", "trans_z"]


class FuncQcInput(BaseModel):
    motion: str  # TSV of the six realignment parameters (rotations in radians, translations in mm)
    boldref_t1: str  # example volume in T1 space
    t1_head: str  # bias-corrected T1 (whole head)
    t1_seg: str  # tissue segmentation (1 CSF, 2 GM, 3 WM)
    boldref_distorted_t1: str | None = None  # the example volume without distortion correction


class FuncQcParams(BaseModel):
    # REVIEW(domain): the 0.5 mm count is only reported (never used to exclude anyone);
    # 50 mm is Power's head radius.
    fd_threshold_mm: float = Field(default=0.5, gt=0)
    head_radius_mm: float = Field(default=50.0, gt=0)


class FuncQcOutput(BaseModel):
    motion_plot: str
    registration: str
    metrics: str
    unwarping: str | None = None


def read_motion(path: Path) -> list[list[float]]:
    """Rows of (rot_x, rot_y, rot_z, trans_x, trans_y, trans_z) from the motion TSV."""
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    if not lines or lines[0].split("\t") != MOTION_COLUMNS:
        raise StepError(
            code="MOTION_TABLE_INVALID",
            message="The motion parameter table does not have the expected columns.",
            probable_cause="The file was edited or came from another program.",
            suggested_action="Run the preprocessing step again to recreate it.",
        )
    return [[float(v) for v in ln.split("\t")] for ln in lines[1:]]


def framewise_displacement(rows: list[list[float]], radius_mm: float = 50.0) -> list[float]:
    """Power's FD per volume; the first volume has no predecessor and gets 0."""
    fd = [0.0]
    for prev, cur in zip(rows, rows[1:], strict=False):
        rot = sum(abs(c - p) for c, p in zip(cur[:3], prev[:3], strict=True))
        trans = sum(abs(c - p) for c, p in zip(cur[3:], prev[3:], strict=True))
        fd.append(trans + radius_mm * rot)
    return fd


def motion_metrics(
    rows: list[list[float]], fd: list[float], threshold: float, radius: float
) -> dict[str, object]:
    above = sum(1 for v in fd if v > threshold)
    return {
        "n_volumes": len(rows),
        "fd_mean_mm": statistics.fmean(fd),
        "fd_median_mm": statistics.median(fd),
        "fd_max_mm": max(fd),
        "fd_threshold_mm": threshold,
        "fd_above_threshold": above,
        "fd_above_threshold_fraction": above / len(fd),
        "max_abs_translation_mm": max(abs(r[i]) for r in rows for i in (3, 4, 5)),
        "max_abs_rotation_deg": max(abs(math.degrees(r[i])) for r in rows for i in (0, 1, 2)),
        "head_radius_mm": radius,
        "fd_definition": "Power et al. 2012: sum of absolute frame-to-frame changes of the "
        "translations plus head_radius_mm times the sum of those of the rotations (radians)",
        "fd_mm": fd,
    }


def draw_motion_plot(rows: list[list[float]], fd: list[float], threshold: float, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(rows)
    t = list(range(1, n + 1))
    fig, axes = plt.subplots(3, 1, figsize=(10, 7.5), sharex=True)
    for i, label in enumerate(("x", "y", "z")):
        axes[0].plot(t, [math.degrees(r[i]) for r in rows], label=f"rotation {label}")
        axes[1].plot(t, [r[3 + i] for r in rows], label=f"shift {label}")
    axes[0].set_ylabel("Rotation (degrees)")
    axes[1].set_ylabel("Shift (mm)")
    axes[2].plot(t, fd, color="black", linewidth=1)
    axes[2].axhline(threshold, color="tab:red", linestyle="--", linewidth=1)
    axes[2].text(n, threshold, f" {threshold:g} mm", color="tab:red", va="bottom", ha="right")
    axes[2].set_ylabel("Framewise displacement (mm)")
    axes[2].set_xlabel("Volume (after the discarded ones)")
    for ax in axes[:2]:
        ax.legend(loc="upper right", ncol=3, fontsize="small")
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.suptitle("Head motion during the scan")
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


@register_step
class FuncQcStep(Step[FuncQcInput, FuncQcParams, FuncQcOutput]):
    name = "func_qc"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = FuncQcInput, FuncQcParams, FuncQcOutput
    requires_fsl = True
    datatype = "func"

    def expected_outputs(self, ctx: StepContext[FuncQcInput, FuncQcParams]) -> FuncQcOutput:
        n = ctx.bids_name
        return FuncQcOutput(
            motion_plot=n("qc", ".png", desc=self.desc(ctx, "motion")),
            registration=n("qc", ".png", desc=self.desc(ctx, "registration")),
            metrics=n("qc", ".json", desc=self.desc(ctx, "metrics")),
            unwarping=(
                n("qc", ".png", desc=self.desc(ctx, "unwarping"))
                if ctx.inputs.boldref_distorted_t1
                else None
            ),
        )

    def validate_inputs(self, ctx: StepContext[FuncQcInput, FuncQcParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        i = ctx.inputs
        for rel in (i.boldref_t1, i.t1_head, i.t1_seg, i.boldref_distorted_t1):
            if rel and not is_readable_nifti(ctx.input_path(rel)):
                problems.append(
                    Problem(
                        code="INPUT_NOT_NIFTI",
                        message=f"An image could not be read: {rel}",
                        probable_cause="The file is damaged or incomplete.",
                        suggested_action="Run the preprocessing step again.",
                    )
                )
        return problems

    def prepare(self, ctx: StepContext[FuncQcInput, FuncQcParams]) -> None:
        super().prepare(ctx)
        shutil.rmtree(ctx.run_dir / "work", ignore_errors=True)

    # -- pictures -----------------------------------------------------------

    def run(self, ctx: StepContext[FuncQcInput, FuncQcParams]) -> StepResult:
        i, p = ctx.inputs, ctx.params
        work = ctx.run_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        out = self.expected_outputs(ctx)

        rows = read_motion(ctx.input_path(i.motion))
        fd = framewise_displacement(rows, p.head_radius_mm)
        metrics = motion_metrics(rows, fd, p.fd_threshold_mm, p.head_radius_mm)
        draw_motion_plot(rows, fd, p.fd_threshold_mm, ctx.output_dir / out.motion_plot)
        (ctx.output_dir / out.metrics).write_text(json.dumps(metrics, indent=2) + "\n")

        wm = work / "wm.nii.gz"
        label = str(WM_LABEL)
        ctx.run_command(
            [
                "fslmaths",
                str(ctx.input_path(i.t1_seg)),
                "-thr",
                label,
                "-uthr",
                label,
                "-bin",
                str(wm),
            ]
        )
        ref, t1 = ctx.input_path(i.boldref_t1), ctx.input_path(i.t1_head)
        slice_row(ctx, ref, wm, work / "func.png")  # functional with the white-matter boundary
        slice_row(ctx, t1, ref, work / "t1.png")  # T1 with the edges of the functional image
        stack_rows(ctx, [work / "func.png", work / "t1.png"], ctx.output_dir / out.registration)
        if out.unwarping and i.boldref_distorted_t1:
            slice_row(ctx, ctx.input_path(i.boldref_distorted_t1), wm, work / "before.png")
            slice_row(ctx, ref, wm, work / "after.png")
            stack_rows(
                ctx, [work / "before.png", work / "after.png"], ctx.output_dir / out.unwarping
            )
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def generate_qc(self, ctx: StepContext[FuncQcInput, FuncQcParams]) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        m = json.loads((ctx.output_dir / out.metrics).read_text())
        items = [
            QCItem(
                name="Mean framewise displacement (mm)",
                kind="metric",
                value=round(m["fd_mean_mm"], 3),
            ),
            QCItem(
                name="Median framewise displacement (mm)",
                kind="metric",
                value=round(m["fd_median_mm"], 3),
            ),
            QCItem(
                name="Largest framewise displacement (mm)",
                kind="metric",
                value=round(m["fd_max_mm"], 3),
            ),
            QCItem(
                name=f"Volumes with framewise displacement above {m['fd_threshold_mm']:g} mm",
                kind="metric",
                value=f"{m['fd_above_threshold']} of {m['n_volumes']}",
            ),
            QCItem(name="Head motion", kind="plot", path=out.motion_plot),
            QCItem(name="Registration to the T1", kind="image", path=out.registration),
        ]
        if out.unwarping:
            label = "Distortion correction (before above, after below)"
            items.append(QCItem(name=label, kind="image", path=out.unwarping))
        return items
