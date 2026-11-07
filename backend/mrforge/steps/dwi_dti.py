"""DwiDtifitStep (tensor fit, FSL ``dtifit``) and DwiQcStep (pictures and numbers for review).

``dtifit`` is run as in ``alps.sh`` (lines 501-522): ``--data --out --mask --bvecs --bvals
--save_tensor``. The data is the best available (the stage passes eddy-corrected data with
eddy's rotated b-vectors, else preprocessed data, else the raw series with its own b-vectors);
without a mask one is made from the first volume (``fslroi`` + ``bet2 -m``) like the script does.

The QC step draws the FA map with the outline of the brain mask, plots eddy's motion estimates and
counts its outliers. Everything it shows is reported only; nothing is excluded (principle 6).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.qcpics import slice_row, slices_dir
from mrforge.steps.registry import register_step


class DwiDtifitInput(BaseModel):
    dwi: str
    bval: str
    bvec: str
    mask: str | None = None


class DwiDtifitParams(BaseModel):
    pass


class DwiDtifitOutput(BaseModel):
    fa: str
    md: str
    tensor: str  # 6 volumes, volumes 0, 3 and 5 are Dxx, Dyy and Dzz
    mask: str


@register_step
class DwiDtifitStep(Step[DwiDtifitInput, DwiDtifitParams, DwiDtifitOutput]):
    name = "dwi_dtifit"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = DwiDtifitInput, DwiDtifitParams, DwiDtifitOutput
    requires_fsl = True
    datatype = "dwi"

    def expected_outputs(
        self, ctx: StepContext[DwiDtifitInput, DwiDtifitParams]
    ) -> DwiDtifitOutput:
        d = self.desc(ctx, "dti")
        return DwiDtifitOutput(
            fa=ctx.bids_name("FA", desc=d),
            md=ctx.bids_name("MD", desc=d),
            tensor=ctx.bids_name("tensor", desc=d),
            mask=ctx.bids_name("mask", desc=self.desc(ctx, "dtimask")),
        )

    def run(self, ctx: StepContext[DwiDtifitInput, DwiDtifitParams]) -> StepResult:
        i = ctx.inputs
        out = self.expected_outputs(ctx)
        work = ctx.run_dir / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        dwi = ctx.input_path(i.dwi)
        if i.mask:
            mask = ctx.input_path(i.mask)
        else:
            ctx.run_command(["fslroi", str(dwi), str(work / "b0"), "0", "1"])
            ctx.run_command(["bet2", str(work / "b0"), str(work / "b0_brain"), "-m"])
            mask = work / "b0_brain_mask.nii.gz"
        ctx.run_command(
            [
                "dtifit", f"--data={dwi}", f"--out={work / 'dti'}", f"--mask={mask}",
                f"--bvecs={ctx.input_path(i.bvec)}", f"--bvals={ctx.input_path(i.bval)}",
                "--save_tensor",
            ]
        )  # fmt: skip
        shutil.copyfile(work / "dti_FA.nii.gz", ctx.output_dir / out.fa)
        shutil.copyfile(work / "dti_MD.nii.gz", ctx.output_dir / out.md)
        shutil.copyfile(work / "dti_tensor.nii.gz", ctx.output_dir / out.tensor)
        shutil.copyfile(mask, ctx.output_dir / out.mask)
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()


class DwiQcInput(BaseModel):
    fa: str
    mask: str
    movement_rms: str | None = None
    restricted_rms: str | None = None
    outlier_report: str | None = None


class DwiQcParams(BaseModel):
    # REVIEW(domain): proposal, a warning only. Mean volume-to-volume movement above this is
    # worth a look.
    relative_rms_warning_mm: float = Field(default=1.0, gt=0)


class DwiQcOutput(BaseModel):
    fa_picture: str
    metrics: str
    motion_plot: str | None = None


def read_rms(path: Path) -> list[tuple[float, float]]:
    """eddy's ``.eddy_movement_rms``: per volume, movement relative to the first volume and
    relative to the previous volume (mm)."""
    rows = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            rows.append((float(parts[0]), float(parts[1])))
    return rows


def count_outlier_slices(path: Path) -> int:
    """Slices eddy reports as outliers (one line each in its outlier report)."""
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def draw_motion_plot(rows: list[tuple[float, float]], threshold: float, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = list(range(1, len(rows) + 1))
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t, [r[0] for r in rows], label="relative to the first volume")
    ax.plot(t, [r[1] for r in rows], label="relative to the previous volume")
    ax.axhline(threshold, color="tab:red", linestyle="--", linewidth=1)
    ax.set_xlabel("Volume")
    ax.set_ylabel("Movement (mm)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", fontsize="small")
    fig.suptitle("Head motion estimated by eddy")
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


@register_step
class DwiQcStep(Step[DwiQcInput, DwiQcParams, DwiQcOutput]):
    name = "dwi_qc"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = DwiQcInput, DwiQcParams, DwiQcOutput
    requires_fsl = True
    datatype = "dwi"

    def expected_outputs(self, ctx: StepContext[DwiQcInput, DwiQcParams]) -> DwiQcOutput:
        n = ctx.bids_name
        return DwiQcOutput(
            fa_picture=n("qc", ".png", desc=self.desc(ctx, "dtifa")),
            metrics=n("qc", ".json", desc=self.desc(ctx, "dwimetrics")),
            motion_plot=(
                n("qc", ".png", desc=self.desc(ctx, "dwimotion"))
                if ctx.inputs.movement_rms
                else None
            ),
        )

    def validate_inputs(self, ctx: StepContext[DwiQcInput, DwiQcParams]) -> list[Problem]:
        return super().validate_inputs(ctx)

    def run(self, ctx: StepContext[DwiQcInput, DwiQcParams]) -> StepResult:
        i, p = ctx.inputs, ctx.params
        out = self.expected_outputs(ctx)
        metrics: dict[str, object] = {"eddy_used": i.movement_rms is not None}
        if i.movement_rms and out.motion_plot:
            rows = read_rms(ctx.input_path(i.movement_rms))
            if rows:
                metrics["n_volumes"] = len(rows)
                metrics["mean_rms_first_mm"] = sum(r[0] for r in rows) / len(rows)
                metrics["max_rms_first_mm"] = max(r[0] for r in rows)
                metrics["mean_rms_previous_mm"] = sum(r[1] for r in rows) / len(rows)
                metrics["max_rms_previous_mm"] = max(r[1] for r in rows)
                draw_motion_plot(rows, p.relative_rms_warning_mm, ctx.output_dir / out.motion_plot)
        if i.restricted_rms:
            rr = read_rms(ctx.input_path(i.restricted_rms))
            if rr:
                metrics["mean_restricted_rms_first_mm"] = sum(r[0] for r in rr) / len(rr)
        if i.outlier_report:
            metrics["outlier_slices"] = count_outlier_slices(ctx.input_path(i.outlier_report))
        (ctx.output_dir / out.metrics).write_text(json.dumps(metrics, indent=2) + "\n")

        work = ctx.run_dir / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        slice_row(
            ctx, ctx.input_path(i.fa), ctx.input_path(i.mask),
            ctx.output_dir / out.fa_picture, slices_dir(ctx, out.fa_picture), "fa",
        )  # fmt: skip
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def generate_qc(self, ctx: StepContext[DwiQcInput, DwiQcParams]) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        m = json.loads((ctx.output_dir / out.metrics).read_text())
        items = [QCItem(name="FA map and brain mask", kind="image", path=out.fa_picture)]
        if out.motion_plot:
            items.append(QCItem(name="Head motion (eddy)", kind="plot", path=out.motion_plot))
        if "mean_rms_previous_mm" in m:
            mean_prev = round(m["mean_rms_previous_mm"], 3)
            warn = (
                f"Mean volume-to-volume movement is {mean_prev} mm, above "
                f"{ctx.params.relative_rms_warning_mm:g} mm."
                if mean_prev > ctx.params.relative_rms_warning_mm
                else None
            )
            items.append(
                QCItem(
                    name="Mean movement relative to the previous volume (mm)",
                    kind="metric",
                    value=mean_prev,
                    warning=warn,
                )
            )
            items.append(
                QCItem(
                    name="Largest movement relative to the first volume (mm)",
                    kind="metric",
                    value=round(m["max_rms_first_mm"], 3),
                )
            )
        if "outlier_slices" in m:
            items.append(
                QCItem(
                    name="Slices eddy reports as outliers", kind="metric", value=m["outlier_slices"]
                )
            )
        return items
