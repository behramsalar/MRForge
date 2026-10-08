"""Remove the components the researcher labelled as noise (FSL ``fsl_regfilt``).

The input is the preprocessed functional image (the FEAT result), the mixing matrix of the
MELODIC run, and the researcher's decision (``ica_labels``). The result is the cleaned image in
the same space, which later steps (standard space) use. By default the removal is partial
("non-aggressive"): only the part of the signal that belongs to the noise components alone is
taken out, so signal shared with good components is kept.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel

from mrforge.niftiutil import image_info, is_readable_nifti
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.registry import register_step


class RegfiltInput(BaseModel):
    bold: str  # preprocessed 4D functional image the components were found in
    mixing: str  # MELODIC mixing matrix of that image (volumes x components)
    labels: str  # the researcher's decision (output of ica_labels)
    brain_mask: str  # brain mask in the same space


class RegfiltParams(BaseModel):
    # REVIEW(domain): partial (non-aggressive) regression is fsl_regfilt's default and what
    # ICA-AROMA uses; aggressive removes everything the noise components could explain,
    # including signal they share with good components.
    aggressive: bool = False


class RegfiltOutput(BaseModel):
    cleaned_bold: str
    picture: str  # before / after: temporal standard deviation maps
    metrics: str  # JSON: what was removed and how much variance it explained


def noise_list(argument: list[int]) -> str:
    return ",".join(str(n) for n in argument)


@register_step
class RegfiltStep(Step[RegfiltInput, RegfiltParams, RegfiltOutput]):
    name = "regfilt"
    version = "2"  # 2: result named desc-denoised (was desc-cleaned)
    InputSpec, ParamSpec, OutputSpec = RegfiltInput, RegfiltParams, RegfiltOutput
    requires_fsl = True
    datatype = "func"

    def expected_outputs(self, ctx: StepContext[RegfiltInput, RegfiltParams]) -> RegfiltOutput:
        n = ctx.bids_name
        return RegfiltOutput(
            cleaned_bold=n("bold", desc=self.desc(ctx, "denoised")),
            picture=n("cleaning", ".png", desc=self.desc(ctx, "variance")),
            metrics=n("cleaning", ".json", desc=self.desc(ctx, "metrics")),
        )

    def _noise(self, ctx: StepContext[RegfiltInput, RegfiltParams]) -> list[int]:
        decision = json.loads(ctx.input_path(ctx.inputs.labels).read_text())
        return [int(n) for n in decision["noise_components"]]

    def validate_inputs(self, ctx: StepContext[RegfiltInput, RegfiltParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        for rel in (ctx.inputs.bold, ctx.inputs.brain_mask):
            if not is_readable_nifti(ctx.input_path(rel)):
                return [
                    Problem(
                        code="INPUT_NOT_NIFTI",
                        message=f"The image could not be read: {rel}",
                        probable_cause="The file is damaged, incomplete or not a NIfTI image.",
                        suggested_action="Run the step that makes it again.",
                    )
                ]
        volumes = image_info(ctx.input_path(ctx.inputs.bold))[0][3]
        mix = np.loadtxt(ctx.input_path(ctx.inputs.mixing), ndmin=2)
        noise = self._noise(ctx)
        if mix.shape[0] != volumes:
            return [
                Problem(
                    code="MIXING_MISMATCH",
                    message=f"The component time courses have {mix.shape[0]} volumes but the "
                    f"functional image has {volumes}.",
                    probable_cause="The components belong to a different image than this one.",
                    suggested_action="Run the component analysis (MELODIC) again on this image.",
                )
            ]
        if any(n < 1 or n > mix.shape[1] for n in noise):
            return [
                Problem(
                    code="LABELS_MISMATCH",
                    message="The labels name components that do not exist in this MELODIC result.",
                    probable_cause="The labels were made for another component analysis run.",
                    suggested_action="Label the components again.",
                )
            ]
        return []

    def run(self, ctx: StepContext[RegfiltInput, RegfiltParams]) -> StepResult:
        out = self.expected_outputs(ctx)
        target = ctx.output_dir / out.cleaned_bold
        noise = self._noise(ctx)
        source = ctx.input_path(ctx.inputs.bold)
        if noise:
            argv = [
                "fsl_regfilt",
                "-i", str(source),
                "-d", str(ctx.input_path(ctx.inputs.mixing)),
                "-f", noise_list(noise),
                "-m", str(ctx.input_path(ctx.inputs.brain_mask)),
                "-o", str(target),
            ]  # fmt: skip
            if ctx.params.aggressive:
                argv.append("-a")
            ctx.run_command(argv)
        else:  # nothing to remove: the cleaned image is the input (linked, no extra space)
            target.unlink(missing_ok=True)
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        before, after = _load(source), _load(target)
        mask = _load(ctx.input_path(ctx.inputs.brain_mask))[..., 0] > 0
        std_before, std_after = before.std(axis=3), after.std(axis=3)
        var_before = float((std_before[mask] ** 2).sum())
        var_after = float((std_after[mask] ** 2).sum())
        removed_pct = 100.0 * (1.0 - var_after / var_before) if var_before > 0 else 0.0
        metrics = {
            "noise_components": noise,
            "n_removed": len(noise),
            "mode": "aggressive" if ctx.params.aggressive else "non-aggressive (partial)",
            "variance_removed_pct": round(removed_pct, 2),
            "variance_definition": "sum over brain voxels of the temporal variance, "
            "before minus after, as a percentage of before",
        }
        (ctx.output_dir / out.metrics).write_text(json.dumps(metrics, indent=2) + "\n")
        import nibabel as nib

        zooms = tuple(float(z) for z in nib.load(source).header.get_zooms()[:3])  # type: ignore[attr-defined]
        _draw(std_before, std_after, mask, ctx.output_dir / out.picture, noise, zooms)
        return StepResult()

    def validate_outputs(self, ctx: StepContext[RegfiltInput, RegfiltParams]) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        out = self.expected_outputs(ctx)
        want = image_info(ctx.input_path(ctx.inputs.bold))[0]
        got = image_info(ctx.output_dir / out.cleaned_bold)[0]
        if got != want:
            return [
                Problem(
                    code="CLEANED_SHAPE_MISMATCH",
                    message=f"The cleaned image has the shape {got}, expected {want}.",
                    probable_cause="fsl_regfilt finished with an unexpected result.",
                    suggested_action="Open the raw log, then run the step again.",
                )
            ]
        return []

    def generate_qc(self, ctx: StepContext[RegfiltInput, RegfiltParams]) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        m = json.loads((ctx.output_dir / out.metrics).read_text())
        return [
            QCItem(name="Components removed", kind="metric", value=m["n_removed"]),
            QCItem(name="Removal mode", kind="metric", value=m["mode"]),
            QCItem(name="Variance removed (%)", kind="metric", value=m["variance_removed_pct"]),
            QCItem(
                name="Variability before (top) and after (bottom)", kind="image", path=out.picture
            ),
        ]


def _load(path: Path) -> NDArray[np.float32]:
    import nibabel as nib

    data = np.asarray(nib.load(path).dataobj, dtype=np.float32)  # type: ignore[attr-defined]
    return data if data.ndim == 4 else data[..., None]


def _draw(
    before: NDArray[Any],
    after: NDArray[Any],
    mask: NDArray[np.bool_],
    out: Path,
    noise: list[int],
    zooms: tuple[float, ...] = (1.0, 1.0, 1.0),
) -> None:
    """Temporal standard deviation before (top) and after (bottom), same colour scale,
    through the middle of the brain in three planes."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    centre = [
        int(round(np.flatnonzero(mask.any(axis=tuple(k for k in range(3) if k != ax))).mean()))
        for ax in range(3)
    ]
    top = float(np.percentile(before[mask], 99)) if mask.any() else 1.0
    fig, axes = plt.subplots(2, 3, figsize=(10, 6.6), dpi=90)
    for row, (name, data) in enumerate((("before", before), ("after", after))):
        for col, (plane, sl, aspect) in enumerate(
            (
                ("Axial", data[:, :, centre[2]], zooms[1] / zooms[0]),
                ("Coronal", data[:, centre[1], :], zooms[2] / zooms[0]),
                ("Sagittal", data[centre[0], :, :], zooms[2] / zooms[1]),
            )
        ):
            ax = axes[row, col]
            # pixel height / width in mm, so thick slices are not squashed
            ax.imshow(np.rot90(sl), cmap="inferno", vmin=0, vmax=top, aspect=aspect)
            ax.set_axis_off()
            ax.set_title(f"{plane}, {name}", fontsize=9)
    removed = ", ".join(str(n) for n in noise) or "none"
    fig.suptitle(
        f"Temporal variability (standard deviation). Components removed: {removed}", fontsize=10
    )
    fig.tight_layout()
    fig.savefig(out, dpi=90)
    plt.close(fig)
