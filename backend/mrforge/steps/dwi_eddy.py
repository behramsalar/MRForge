"""DwiEddyStep: correct eddy-current distortions and head motion of a diffusion series.

Port of ``alps.sh`` lines 418-498. Options exactly as in the script:

* ``eddy_cpu`` (default), ``eddy``, ``eddy_cuda...`` or any other program in ``$FSLDIR/bin`` that
  takes eddy's arguments, always with the script's default options (no ``--repol``, no
  ``--slm``, ...): ``--imain --mask --acqp --index --bvecs --bvals [--topup] --out``;
* ``eddy_correct`` (``eddy_correct <in> <out> 0 trilinear``): the old method, no rotated
  b-vectors;
* ``--index``: every volume uses the first line of the acquisition-parameter file (the script
  assumes all volumes were acquired the same way);
* with TOPUP results (``dwi_topup``) ``--topup`` is added and the brain mask is the one made from
  the corrected b0. Without: the mask is made here from the first volume (``fslroi`` + ``bet2 -m``,
  as the script does) and the acquisition-parameter file has one line.

REVIEW(domain): defaults of the script (no outlier replacement); every volume assumed acquired
with the first acquisition-parameter line.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import cast

from nibabel.loadsave import load as load_image
from nibabel.nifti1 import Nifti1Image
from pydantic import BaseModel, Field

from mrforge.errors import StepError
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.dwi_common import EncodingError, read_encoding
from mrforge.steps.registry import register_step

EDDY_CORRECT = "eddy_correct"


class DwiEddyInput(BaseModel):
    dwi: str
    bval: str
    bvec: str
    dwi_json: str | None = None  # needed for eddy without TOPUP (acquisition parameters)
    topup_acqparams: str | None = None
    topup_fieldcoef: str | None = None
    topup_movpar: str | None = None
    topup_mask: str | None = None


class DwiEddyParams(BaseModel):
    program: str = "eddy_cpu"  # eddy_cpu, eddy, eddy_cuda*, eddy_correct, or another eddy program
    # Threads for eddy (--nthr). None = what the Settings resource policy gives one job. alps.sh
    # does not pass --nthr, so eddy runs on one thread there; the command is in the provenance.
    threads: int | None = Field(default=None, ge=1)


class DwiEddyOutput(BaseModel):
    dwi: str
    bval: str
    bvec: str  # rotated by eddy; eddy_correct does not rotate, so this is a copy of the input
    mask: str
    acqparams: str
    index: str
    parameters: str | None = None  # eddy's own motion/eddy-current parameters
    movement_rms: str | None = None
    restricted_rms: str | None = None
    outlier_report: str | None = None


def _has_nthr_option(program: Path, env: dict[str, str] | None) -> bool:
    """Whether this eddy build accepts --nthr (FSL 6.0.7+); older builds do not."""
    try:
        proc = subprocess.run(
            [str(program), "--help"], capture_output=True, text=True, env=env or os.environ.copy(),
            timeout=60, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell: keep the previous behaviour
    return "--nthr" in proc.stdout + proc.stderr


def _n_volumes(path: Path) -> int:
    shape = cast(Nifti1Image, load_image(str(path))).shape
    return int(shape[3]) if len(shape) > 3 else 1


def _topup_given(i: DwiEddyInput) -> bool:
    return any((i.topup_acqparams, i.topup_fieldcoef, i.topup_movpar, i.topup_mask))


@register_step
class DwiEddyStep(Step[DwiEddyInput, DwiEddyParams, DwiEddyOutput]):
    name = "dwi_eddy"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = DwiEddyInput, DwiEddyParams, DwiEddyOutput
    requires_fsl = True
    datatype = "dwi"

    def expected_outputs(self, ctx: StepContext[DwiEddyInput, DwiEddyParams]) -> DwiEddyOutput:
        d = self.desc(ctx, "eddy")
        plain = ctx.params.program == EDDY_CORRECT
        return DwiEddyOutput(
            dwi=ctx.bids_name("dwi", desc=d),
            bval=ctx.bids_name("dwi", ".bval", desc=d),
            bvec=ctx.bids_name("dwi", ".bvec", desc=d),
            mask=ctx.bids_name("mask", desc=d),
            acqparams=ctx.bids_name("acqparams", ".txt", desc=d),
            index=ctx.bids_name("index", ".txt", desc=d),
            parameters=None if plain else ctx.bids_name("parameters", ".txt", desc=d),
            movement_rms=None if plain else ctx.bids_name("rms", ".txt", desc=d),
            restricted_rms=None if plain else ctx.bids_name("restrictedrms", ".txt", desc=d),
            outlier_report=None if plain else ctx.bids_name("outliers", ".txt", desc=d),
        )

    def _fsldir(self, ctx: StepContext[DwiEddyInput, DwiEddyParams]) -> str:
        return (ctx.env or os.environ).get("FSLDIR", "")

    def _program(self, ctx: StepContext[DwiEddyInput, DwiEddyParams]) -> Path:
        return Path(self._fsldir(ctx)) / "bin" / ctx.params.program

    def validate_inputs(self, ctx: StepContext[DwiEddyInput, DwiEddyParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        i, p = ctx.inputs, ctx.params
        if "/" in p.program or not p.program:
            problems.append(
                Problem(
                    code="EDDY_PROGRAM_UNKNOWN",
                    message=f"'{p.program}' is not a name of an FSL program.",
                    probable_cause="Only programs in the FSL folder can be used.",
                    suggested_action="Choose eddy_cpu, eddy, eddy_cuda or eddy_correct.",
                )
            )
            return problems
        if p.program != EDDY_CORRECT:
            if _topup_given(i):
                if not all((i.topup_acqparams, i.topup_fieldcoef, i.topup_movpar, i.topup_mask)):
                    problems.append(
                        Problem(
                            code="EDDY_TOPUP_INCOMPLETE",
                            message="The distortion-correction (TOPUP) results are incomplete.",
                            probable_cause="Some of its files were not given.",
                            suggested_action="Run distortion correction again, or leave it out.",
                        )
                    )
            elif not i.dwi_json:
                problems.append(self._no_sidecar())
            else:
                try:
                    read_encoding(json.loads(ctx.input_path(i.dwi_json).read_text()))
                except EncodingError as err:
                    problems.append(
                        Problem(
                            code="DWI_ENCODING_UNKNOWN",
                            message=str(err),
                            probable_cause="The scanner's metadata (JSON) lacks it.",
                            suggested_action="Use eddy_correct, or add the value to the JSON file "
                            "of the original import.",
                        )
                    )
        if not self._program(ctx).is_file():
            problems.append(
                Problem(
                    code="EDDY_PROGRAM_MISSING",
                    message=f"The FSL program '{p.program}' was not found.",
                    probable_cause="It is not part of this FSL installation (eddy_cuda needs a "
                    "GPU build, for example).",
                    suggested_action="Choose another eddy program (System page lists them).",
                )
            )
        return problems

    @staticmethod
    def _no_sidecar() -> Problem:
        return Problem(
            code="DWI_ENCODING_UNKNOWN",
            message="There is no metadata file (JSON) for the diffusion image, so eddy cannot "
            "know how it was acquired.",
            probable_cause="The image was imported without its JSON file.",
            suggested_action="Use eddy_correct, or import the image with its JSON file.",
        )

    def run(self, ctx: StepContext[DwiEddyInput, DwiEddyParams]) -> StepResult:
        i, p = ctx.inputs, ctx.params
        out = self.expected_outputs(ctx)
        work = ctx.run_dir / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        dwi = ctx.input_path(i.dwi)
        bval, bvec = ctx.input_path(i.bval), ctx.input_path(i.bvec)
        n_vol = _n_volumes(dwi)

        use_topup = i.topup_fieldcoef is not None and p.program != EDDY_CORRECT
        if use_topup:
            assert i.topup_acqparams and i.topup_mask and i.topup_fieldcoef
            acq_source = ctx.input_path(i.topup_acqparams)
            mask = ctx.input_path(i.topup_mask)
            shutil.copyfile(acq_source, ctx.output_dir / out.acqparams)
        else:
            mask = work / "b0_brain_mask.nii.gz"
            ctx.run_command(["fslroi", str(dwi), str(work / "b0"), "0", "1"])
            ctx.run_command(["bet2", str(work / "b0"), str(work / "b0_brain"), "-m"])
            if p.program != EDDY_CORRECT:
                assert i.dwi_json
                enc = read_encoding(json.loads(ctx.input_path(i.dwi_json).read_text()))
                (ctx.output_dir / out.acqparams).write_text(enc.line + "\n")
            else:  # eddy_correct does not use them; a record of what was assumed
                (ctx.output_dir / out.acqparams).write_text("not used by eddy_correct\n")
        (ctx.output_dir / out.index).write_text(" ".join(["1"] * n_vol) + "\n")

        prefix = work / "eddy_corrected_data"
        if p.program == EDDY_CORRECT:
            ctx.run_command([str(self._program(ctx)), str(dwi), str(prefix), "0", "trilinear"])
            rotated = bvec
        else:
            argv = [
                str(self._program(ctx)), f"--imain={dwi}", f"--mask={mask}",
                f"--acqp={ctx.output_dir / out.acqparams}", f"--index={ctx.output_dir / out.index}",
                f"--bvecs={bvec}", f"--bvals={bval}",
            ]  # fmt: skip
            if use_topup:
                assert i.topup_fieldcoef
                field = ctx.input_path(i.topup_fieldcoef)
                argv.append(
                    f"--topup={field.parent / field.name.removesuffix('_fieldcoef.nii.gz')}"
                )
            argv.append(f"--out={prefix}")
            n_threads = p.threads or int(os.environ.get("OMP_NUM_THREADS", "1") or 1)
            if n_threads > 1 and not p.program.startswith("eddy_cuda"):
                if _has_nthr_option(self._program(ctx), ctx.env):
                    argv.append(f"--nthr={n_threads}")
                else:
                    # FSL 6.0.6 and older: eddy_cpu / eddy_openmp have no --nthr and take the
                    # thread count from OMP_NUM_THREADS. The command log header shows it.
                    ctx.env = {**(ctx.env or os.environ), "OMP_NUM_THREADS": str(n_threads)}
                    ctx.run_command(["echo", f"eddy has no --nthr; OMP_NUM_THREADS={n_threads}"])
            ctx.run_command(argv)
            rotated = work / "eddy_corrected_data.eddy_rotated_bvecs"

        shutil.copyfile(work / "eddy_corrected_data.nii.gz", ctx.output_dir / out.dwi)
        shutil.copyfile(rotated, ctx.output_dir / out.bvec)
        shutil.copyfile(bval, ctx.output_dir / out.bval)
        shutil.copyfile(mask, ctx.output_dir / out.mask)
        extras = {
            out.parameters: "eddy_parameters",
            out.movement_rms: "eddy_movement_rms",
            out.restricted_rms: "eddy_restricted_movement_rms",
            out.outlier_report: "eddy_outlier_report",
        }
        for name, ending in extras.items():
            if name is None:
                continue
            source = work / f"eddy_corrected_data.{ending}"
            if not source.is_file():
                raise StepError(
                    code="EDDY_OUTPUT_MISSING",
                    message=f"{p.program} finished but did not write its file '{ending}'.",
                    probable_cause="This version of eddy does not write it.",
                    suggested_action="Open the raw log, or try another eddy program.",
                    log_path=ctx.log_dir / "stderr.log",
                )
            shutil.copyfile(source, ctx.output_dir / name)
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def generate_qc(self, ctx: StepContext[DwiEddyInput, DwiEddyParams]) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        items = [
            QCItem(
                name="Distortion correction (TOPUP) used",
                kind="metric",
                value="yes" if ctx.inputs.topup_fieldcoef else "no",
            )
        ]
        if out.movement_rms:
            rows = [
                [float(v) for v in line.split()]
                for line in (ctx.output_dir / out.movement_rms).read_text().splitlines()
                if line.strip()
            ]
            if rows:
                items.append(
                    QCItem(
                        name="Mean movement relative to the first volume (mm)",
                        kind="metric",
                        value=round(sum(r[0] for r in rows) / len(rows), 3),
                    )
                )
        return items
