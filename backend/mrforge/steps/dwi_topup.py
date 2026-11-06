"""DwiTopupStep: estimate the susceptibility-induced distortion from a b = 0 image of the main
diffusion series and one with the opposite phase-encoding direction (FSL ``topup``).

Port of ``alps.sh`` lines 286-417: first volume of each series (``fslroi``), the second one is
registered to the first (``flirt``, 6 parameters) when the matrix sizes differ, ``fslmerge -t``,
``topup`` with ``b02b0.cnf`` (``b02b0_1.cnf`` for an odd number of slices), the corrected b0 is
averaged (``fslmaths -Tmean``) and a brain mask is made with ``bet2 -m``.

The second image may be a whole diffusion series or a single b = 0 volume (a reverse-phase-
encoding field map). ``acqparams.txt`` is written next to the results because ``eddy`` needs the
same file.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import cast

from nibabel.loadsave import load as load_image
from nibabel.nifti1 import Nifti1Image
from pydantic import BaseModel

from mrforge.errors import StepError
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.dwi_common import (
    EncodingError,
    read_encoding,
    reverse_encoding,
    starts_with_b0,
    topup_config,
    topup_problem,
)
from mrforge.steps.registry import register_step


class DwiTopupInput(BaseModel):
    dwi: str  # main series
    dwi_json: str
    reverse: str  # image with the opposite phase-encoding direction (3D or 4D)
    dwi_bval: str | None = None
    reverse_json: str | None = None  # without it: opposite direction, same readout (as the script)
    reverse_bval: str | None = None


class DwiTopupParams(BaseModel):
    # REVIEW(domain): the script reads two Philips images as the same direction (the axis has no
    # sign) and then skips TOPUP silently. True = take the second image as the opposite one.
    second_is_opposite: bool = False


class DwiTopupOutput(BaseModel):
    acqparams: str
    both_b0: str  # the two b0 volumes that went into topup
    fieldcoef: str  # <base>_fieldcoef.nii.gz (topup's --out is the file name without this ending)
    movpar: str  # <base>_movpar.txt
    b0: str  # corrected, averaged b0
    b0_brain: str
    mask: str


def _shape(path: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in cast(Nifti1Image, load_image(str(path))).shape)


def _read_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else {}


def _bval(ctx: StepContext[DwiTopupInput, DwiTopupParams], rel: str | None) -> str | None:
    return ctx.input_path(rel).read_text() if rel else None


def plan(
    ctx: StepContext[DwiTopupInput, DwiTopupParams],
) -> tuple[str, str, str | None]:
    """(main acquisition-parameter line, reverse line, reason TOPUP is impossible)."""
    main = read_encoding(_read_json(ctx.input_path(ctx.inputs.dwi_json)))
    rev_side = (
        _read_json(ctx.input_path(ctx.inputs.reverse_json)) if ctx.inputs.reverse_json else None
    )
    rev = reverse_encoding(main, rev_side, assume_opposite=ctx.params.second_is_opposite)
    main_b0 = starts_with_b0(_bval(ctx, ctx.inputs.dwi_bval))
    rev_b0 = starts_with_b0(_bval(ctx, ctx.inputs.reverse_bval))
    return main.line, rev.line, topup_problem(main, rev, main_b0, rev_b0)


@register_step
class DwiTopupStep(Step[DwiTopupInput, DwiTopupParams, DwiTopupOutput]):
    name = "dwi_topup"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = DwiTopupInput, DwiTopupParams, DwiTopupOutput
    requires_fsl = True
    datatype = "dwi"

    def expected_outputs(self, ctx: StepContext[DwiTopupInput, DwiTopupParams]) -> DwiTopupOutput:
        d = self.desc(ctx, "topup")
        return DwiTopupOutput(
            acqparams=ctx.bids_name("acqparams", ".txt", desc=d),
            both_b0=ctx.bids_name("b0", desc=self.desc(ctx, "topupinput")),
            fieldcoef=ctx.bids_name("fieldcoef", desc=d),
            movpar=ctx.bids_name("movpar", ".txt", desc=d),
            b0=ctx.bids_name("b0", desc=d),
            b0_brain=ctx.bids_name("b0", desc=self.desc(ctx, "topupbrain")),
            mask=ctx.bids_name("mask", desc=d),
        )

    @staticmethod
    def topup_base(out: DwiTopupOutput) -> str:
        """The ``--out`` name of topup: the field file name without ``_fieldcoef.nii.gz``."""
        return out.fieldcoef.removesuffix("_fieldcoef.nii.gz")

    def validate_inputs(self, ctx: StepContext[DwiTopupInput, DwiTopupParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        try:
            reason = plan(ctx)[2]
        except EncodingError as err:
            return [
                Problem(
                    code="DWI_ENCODING_UNKNOWN",
                    message=str(err),
                    probable_cause="The scanner's metadata (JSON file next to the image) lacks it.",
                    suggested_action="Skip distortion correction, or add the missing values to "
                    "the JSON file of the original import.",
                )
            ]
        if reason:
            problems.append(
                Problem(
                    code="TOPUP_NOT_POSSIBLE",
                    message=f"Distortion correction (TOPUP) is not possible: {reason}.",
                    probable_cause="TOPUP needs two b = 0 images with opposite phase encoding.",
                    suggested_action="Leave distortion correction out, or import the reverse "
                    "phase-encoding image.",
                )
            )
        return problems

    def run(self, ctx: StepContext[DwiTopupInput, DwiTopupParams]) -> StepResult:
        out = self.expected_outputs(ctx)
        main_line, rev_line, _ = plan(ctx)
        work = ctx.run_dir / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        acq = ctx.output_dir / out.acqparams
        acq.write_text(f"{main_line}\n{rev_line}\n")

        b0_1 = work / "b0_first_direction.nii.gz"
        b0_2 = work / "b0_second_direction.nii.gz"
        main = ctx.input_path(ctx.inputs.dwi)
        ctx.run_command(["fslroi", str(main), str(b0_1), "0", "1"])
        ctx.run_command(["fslroi", str(ctx.input_path(ctx.inputs.reverse)), str(b0_2), "0", "1"])
        if _shape(b0_1)[:3] != _shape(b0_2)[:3]:
            registered = work / "b0_second_direction_reg"
            ctx.run_command(
                [
                    "flirt", "-in", str(b0_2), "-ref", str(b0_1), "-out", str(registered),
                    "-omat", str(work / "b0_2.in.b0_1.mat"),
                    "-bins", "256", "-cost", "corratio",
                    "-searchrx", "-90", "90", "-searchry", "-90", "90", "-searchrz", "-90", "90",
                    "-dof", "6",
                ]
            )  # fmt: skip
            b0_2 = work / "b0_second_direction_reg.nii.gz"
        both = ctx.output_dir / out.both_b0
        ctx.run_command(["fslmerge", "-t", str(both), str(b0_1), str(b0_2)])

        n_slices = _shape(main)[2]
        config = topup_config(n_slices)
        config_arg = config
        if config != "b02b0.cnf":  # the script searches FSLDIR for the odd-slice configuration
            found = self._find_config(ctx, config)
            if found is None:
                raise StepError(
                    code="TOPUP_CONFIG_MISSING",
                    message=f"FSL's TOPUP configuration file {config} was not found.",
                    probable_cause=f"The image has {n_slices} slices (an odd number), which needs "
                    f"{config}; it is normally in the FSL folder.",
                    suggested_action="Check the FSL installation (System page), or crop the "
                    "images to an even number of slices.",
                )
            config_arg = str(found)
        base = ctx.output_dir / self.topup_base(out)
        hifi = work / "hifi_b0"
        ctx.run_command(
            [
                "topup", f"--imain={both}", f"--datain={acq}", f"--config={config_arg}",
                f"--out={base}", f"--iout={hifi}",
            ]
        )  # fmt: skip
        mean = ctx.output_dir / out.b0
        ctx.run_command(["fslmaths", str(hifi), "-Tmean", str(mean)])
        brain = work / "b0_brain"
        ctx.run_command(["bet2", str(mean), str(brain), "-m"])
        shutil.copyfile(work / "b0_brain.nii.gz", ctx.output_dir / out.b0_brain)
        shutil.copyfile(work / "b0_brain_mask.nii.gz", ctx.output_dir / out.mask)
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    @staticmethod
    def _find_config(ctx: StepContext[DwiTopupInput, DwiTopupParams], name: str) -> Path | None:
        fsldir = (ctx.env or os.environ).get("FSLDIR", "")
        for sub in ("etc/flirtsch", "src/topup/flirtsch", "src/fsl-topup/flirtsch"):
            candidate = Path(fsldir) / sub / name
            if candidate.is_file():
                return candidate
        return None

    def generate_qc(self, ctx: StepContext[DwiTopupInput, DwiTopupParams]) -> list[QCItem]:
        main_line, rev_line, _ = plan(ctx)
        return [
            QCItem(name="Phase encoding, main series", kind="metric", value=main_line),
            QCItem(name="Phase encoding, reverse image", kind="metric", value=rev_line),
        ]
