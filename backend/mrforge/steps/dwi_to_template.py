"""DwiToTemplateStep: bring the FA map, the MD map and the diffusion tensor into template space.

Port of ``alps.sh`` lines 572-675 with all of its registration options, command for command:

* ``linear`` (script ``-w 0``, default): ``flirt`` FA to the template, 12 parameters, correlation
  ratio; MD with the same matrix;
* ``fnirt`` (``-w 1``): ``fnirt`` alone with the script's parameter set (FSL's FA_2_FMRIB58 style);
* ``linear_fnirt`` (``-w 2``): ``flirt`` then ``fnirt`` with that matrix as start;
* with a structural image (T1 or T2, script ``-v``; the mode above is then ignored): FA (or the b0
  for a T2) to the structural image with 6 parameters, the structural image masked with the
  brain mask, ``flirt`` + ``fnirt`` of the structural image to the template, ``applywarp`` with the
  FA-to-structural matrix as ``--premat``;
* the tensor is moved with ``flirt``/``applywarp`` (script ``-f 1``, default) or ``vecreg``
  (``-f 2``).

Template: JHU-ICBM-FA-1mm without structural image, MNI152_T1_1mm_brain with a T1, JHU-ICBM-T2-1mm
with a T2, or a file of the researcher. As in the script, the dilated MNI brain mask limits
``fnirt`` (``--refmask``) whenever a default template is used.

REVIEW(domain): ``flirt``/``applywarp`` move the tensor's numbers without rotating its
directions, which ``vecreg`` does; the script's default is ``flirt`` (kept). The
``fnirt`` parameter sets are the script's; the structural route masks the structural image with
the diffusion brain mask moved onto it.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Literal, cast

from nibabel.loadsave import load as load_image
from nibabel.nifti1 import Nifti1Image
from pydantic import BaseModel

from mrforge.steps.alps_rois import TEMPLATES
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.qcpics import known_slices, slice_row, slices_dir
from mrforge.steps.registry import register_step

REFMASK = "data/standard/MNI152_T1_1mm_brain_mask_dil.nii.gz"
SEARCH = ["-searchrx", "-90", "90", "-searchry", "-90", "90", "-searchrz", "-90", "90"]


class DwiToTemplateInput(BaseModel):
    fa: str
    md: str
    tensor: str
    mask: str | None = None  # brain mask of the diffusion data (structural route)
    b0: str | None = None  # first volume; used for a T2-weighted structural image
    struct: str | None = None  # T1w or T2w image of the same person


class DwiToTemplateParams(BaseModel):
    registration: Literal["linear", "fnirt", "linear_fnirt"] = "linear"  # ignored with struct
    template: Literal["default", "jhu_fa", "mni_t1", "jhu_t2", "custom"] = "default"
    template_file: str | None = None  # absolute path, when template is "custom"
    struct_weight: Literal["t1", "t2"] = "t1"
    tensor_method: Literal["flirt", "vecreg"] = "flirt"


class DwiToTemplateOutput(BaseModel):
    fa: str
    md: str
    tensor: str
    affine: str  # FA -> template (linear), FA -> structural (structural route)
    info: str  # JSON: what was done, and whether the warp needs the affine as --premat
    qc_picture: str
    warp: str | None = None


def resolve_template(p: DwiToTemplateParams, has_struct: bool) -> str:
    """The template key the script would use: FA template, or by the weight of the structural
    image; an explicit choice wins."""
    if p.template != "default":
        return p.template
    if not has_struct:
        return "jhu_fa"
    return "mni_t1" if p.struct_weight == "t1" else "jhu_t2"


def space_label(p: DwiToTemplateParams, has_struct: bool) -> str:
    key = resolve_template(p, has_struct)
    return "template" if key == "custom" else TEMPLATES[key][1]


def _volumes(path: Path) -> int:
    shape = cast(Nifti1Image, load_image(str(path))).shape
    return int(shape[3]) if len(shape) > 3 else 1


@register_step
class DwiToTemplateStep(Step[DwiToTemplateInput, DwiToTemplateParams, DwiToTemplateOutput]):
    name = "dwi_to_template"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = DwiToTemplateInput, DwiToTemplateParams, DwiToTemplateOutput
    requires_fsl = True
    datatype = "dwi"

    def expected_outputs(
        self, ctx: StepContext[DwiToTemplateInput, DwiToTemplateParams]
    ) -> DwiToTemplateOutput:
        sp = space_label(ctx.params, ctx.inputs.struct is not None)
        d = self.desc(ctx, "dti")
        structural = ctx.inputs.struct is not None
        needs_warp = structural or ctx.params.registration != "linear"
        xfm = {"mode": "image", "from": "native", "to": sp}
        return DwiToTemplateOutput(
            fa=ctx.bids_name("FA", desc=d, space=sp),
            md=ctx.bids_name("MD", desc=d, space=sp),
            tensor=ctx.bids_name("tensor", desc=d, space=sp),
            affine=ctx.bids_name("xfm", ".mat", **xfm),
            info=ctx.bids_name("info", ".json", desc=self.desc(ctx, "toTemplate"), space=sp),
            qc_picture=ctx.bids_name("qc", ".png", desc=self.desc(ctx, "toTemplate")),
            warp=ctx.bids_name("xfm", ".nii.gz", desc="warp", **xfm) if needs_warp else None,
        )

    def _fsldir(self, ctx: StepContext[DwiToTemplateInput, DwiToTemplateParams]) -> str:
        return (ctx.env or os.environ).get("FSLDIR", "")

    def _template(self, ctx: StepContext[DwiToTemplateInput, DwiToTemplateParams]) -> Path:
        key = resolve_template(ctx.params, ctx.inputs.struct is not None)
        if key == "custom":
            return Path(ctx.params.template_file or "")
        return Path(self._fsldir(ctx)) / TEMPLATES[key][0]

    def validate_inputs(
        self, ctx: StepContext[DwiToTemplateInput, DwiToTemplateParams]
    ) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        if problems:
            return problems
        p = ctx.params
        template = self._template(ctx)
        if p.template == "custom" and not template.is_file():
            problems.append(
                Problem(
                    code="TEMPLATE_MISSING",
                    message="The template you chose could not be found.",
                    probable_cause="No template file was given, or it was moved.",
                    suggested_action="Choose the template file again.",
                )
            )
        elif p.template != "custom" and not template.is_file():
            problems.append(
                Problem(
                    code="TEMPLATE_MISSING",
                    message=f"FSL's template {template.name} was not found.",
                    probable_cause="The FSL installation is incomplete.",
                    suggested_action="Check the FSL installation on the System page.",
                )
            )
        if _volumes(ctx.input_path(ctx.inputs.tensor)) != 6:
            problems.append(
                Problem(
                    code="TENSOR_NOT_SIX_VOLUMES",
                    message="The tensor file does not have 6 volumes.",
                    probable_cause="It was not made by the tensor fit of this app.",
                    suggested_action="Run the tensor fit again.",
                )
            )
        return problems

    # -- commands (named as in the script) ------------------------------------------------------

    def run(self, ctx: StepContext[DwiToTemplateInput, DwiToTemplateParams]) -> StepResult:
        i, p = ctx.inputs, ctx.params
        out = self.expected_outputs(ctx)
        template = self._template(ctx)
        work = ctx.run_dir / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        fa, md, tensor = (ctx.input_path(x) for x in (i.fa, i.md, i.tensor))
        affine = ctx.output_dir / out.affine
        warp = ctx.output_dir / out.warp if out.warp else None
        fa_t, md_t, tensor_t = (ctx.output_dir / x for x in (out.fa, out.md, out.tensor))
        key = resolve_template(p, i.struct is not None)
        refmask = Path(self._fsldir(ctx)) / REFMASK
        ref_args = [f"--refmask={refmask}"] if key != "custom" and refmask.is_file() else []
        info: dict[str, object] = {
            "template": key,
            "template_file": str(template),
            "tensor_method": p.tensor_method,
            "refmask": bool(ref_args),
        }

        def run(argv: list[Any]) -> None:
            ctx.run_command([str(a) for a in argv])

        if i.struct:
            info |= {"route": "structural", "struct_weight": p.struct_weight, "premat": True}
            self._structural(ctx, template, ref_args, work, affine, warp, fa_t, md_t, tensor_t)
        elif p.registration == "linear":
            info |= {"route": "linear", "premat": False}
            run(["flirt", "-in", fa, "-ref", template, "-out", fa_t, "-omat", affine,
                 "-bins", "256", "-cost", "corratio", *SEARCH, "-dof", "12"])  # fmt: skip
            run(["flirt", "-in", md, "-ref", template, "-out", md_t, "-init", affine, "-applyxfm"])
            if p.tensor_method == "flirt":
                run(["flirt", "-in", tensor, "-ref", template, "-out", tensor_t,
                     "-init", affine, "-applyxfm"])  # fmt: skip
            else:
                run(["vecreg", "-i", tensor, "-r", template, "-o", tensor_t, "-t", affine])
        else:
            assert warp is not None
            info |= {"route": p.registration, "premat": False}
            start: list[str] = []
            if p.registration == "linear_fnirt":
                run(["flirt", "-in", fa, "-ref", template, "-omat", affine, "-bins", "256",
                     "-cost", "corratio", *SEARCH, "-dof", "12"])  # fmt: skip
                start = [f"--aff={affine}"]
            else:  # the matrix file is part of the results; here it is the identity
                affine.write_text("1 0 0 0\n0 1 0 0\n0 0 1 0\n0 0 0 1\n")
            run(["fnirt", f"--in={fa}", f"--ref={template}", *ref_args, *start,
                 f"--cout={warp}", "--imprefm=1", "--impinm=1", "--imprefval=0", "--impinval=0",
                 "--subsamp=8,4,2,2", "--miter=5,5,5,5", "--infwhm=12,6,2,2",
                 "--reffwhm=12,6,2,2", "--lambda=300,75,30,30", "--estint=1,1,1,0",
                 "--warpres=10,10,10", "--ssqlambda=1", "--regmod=bending_energy",
                 "--intmod=global_linear", "--refderiv=0"])  # fmt: skip
            for src, dst in ((fa, fa_t), (md, md_t)):
                run(["applywarp", f"--in={src}", f"--ref={template}", f"--warp={warp}",
                     f"--out={dst}"])  # fmt: skip
            if p.tensor_method == "flirt":
                run(["applywarp", f"--in={tensor}", f"--ref={template}", f"--warp={warp}",
                     f"--out={tensor_t}"])  # fmt: skip
            else:
                run(["vecreg", "-i", tensor, "-r", template, "-o", tensor_t, "-w", warp])

        (ctx.output_dir / out.info).write_text(json.dumps(info, indent=2) + "\n")
        # the picture: the template with the outline of the FA map moved onto it
        slice_row(
            ctx, template, fa_t, ctx.output_dir / out.qc_picture,
            slices_dir(ctx, out.qc_picture), "template",
        )  # fmt: skip
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def _structural(
        self,
        ctx: StepContext[DwiToTemplateInput, DwiToTemplateParams],
        template: Path,
        ref_args: list[str],
        work: Path,
        affine: Path,
        warp: Path | None,
        fa_t: Path,
        md_t: Path,
        tensor_t: Path,
    ) -> None:
        i, p = ctx.inputs, ctx.params
        assert i.struct and warp is not None
        struct = ctx.input_path(i.struct)
        fa, md, tensor = (ctx.input_path(x) for x in (i.fa, i.md, i.tensor))

        def run(argv: list[Any]) -> None:
            ctx.run_command([str(a) for a in argv])

        # diffusion -> structural, 6 parameters; a T2 is better aligned with the b0 than with FA
        moving = ctx.input_path(i.b0) if p.struct_weight == "t2" and i.b0 else fa
        run(["flirt", "-ref", struct, "-in", moving, "-dof", "6", "-out", work / "to_struct",
             "-omat", affine])  # fmt: skip
        if i.mask:
            mask = ctx.input_path(i.mask)
        else:  # only the maps are available: a mask from FA, as the script does
            run(["bet2", fa, work / "fa_brain", "-m"])
            mask = work / "fa_brain_mask.nii.gz"
        run(["flirt", "-in", mask, "-ref", struct, "-interp", "nearestneighbour",
             "-out", work / "mask_in_struct", "-init", affine, "-applyxfm"])  # fmt: skip
        run(["fslmaths", struct, "-mul", work / "mask_in_struct", work / "struct_brain"])
        run(["flirt", "-ref", template, "-in", work / "struct_brain",
             "-omat", work / "struct2template_aff.mat"])  # fmt: skip
        run(["fnirt", f"--in={struct}", f"--aff={work / 'struct2template_aff.mat'}",
             f"--cout={warp}", f"--ref={template}", *ref_args, "--imprefm=1", "--impinm=1",
             "--imprefval=0", "--impinval=0", "--subsamp=4,4,2,2,1,1", "--miter=5,5,5,5,5,10",
             "--infwhm=8,6,5,4.5,3,2", "--reffwhm=8,6,5,4,2,0", "--lambda=300,150,100,50,40,30",
             "--estint=1,1,1,1,1,0", "--applyrefmask=1,1,1,1,1,1", "--applyinmask=1",
             "--warpres=10,10,10", "--ssqlambda=1", "--regmod=bending_energy",
             "--intmod=global_non_linear_with_bias", "--intorder=5", "--biasres=50,50,50",
             "--biaslambda=10000", "--refderiv=0"])  # fmt: skip
        for src, dst in ((fa, fa_t), (md, md_t)):
            run(["applywarp", f"--in={src}", f"--ref={template}", f"--warp={warp}",
                 f"--premat={affine}", f"--out={dst}"])  # fmt: skip
        if p.tensor_method == "flirt":
            run(["applywarp", f"--in={tensor}", f"--ref={template}", f"--warp={warp}",
                 f"--premat={affine}", f"--out={tensor_t}"])  # fmt: skip
        else:
            run(["vecreg", "-i", tensor, "-r", template, "-o", work / "tensor_in_struct",
                 "-t", affine])  # fmt: skip
            run(["vecreg", "-i", work / "tensor_in_struct", "-r", template, "-o", tensor_t,
                 "-w", warp])  # fmt: skip

    def validate_outputs(
        self, ctx: StepContext[DwiToTemplateInput, DwiToTemplateParams]
    ) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        out = self.expected_outputs(ctx)
        if _volumes(ctx.output_dir / out.tensor) != 6:
            problems.append(
                Problem(
                    code="TENSOR_NOT_SIX_VOLUMES",
                    message="The tensor in template space does not have 6 volumes.",
                    probable_cause="The transformation of the tensor did not run correctly.",
                    suggested_action="Open the raw log, then run the step again.",
                )
            )
        return problems

    def generate_qc(
        self, ctx: StepContext[DwiToTemplateInput, DwiToTemplateParams]
    ) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        slices = known_slices(ctx, slices_dir(ctx, out.qc_picture), "template")
        return [
            QCItem(
                name="FA map outlined on the template",
                kind="image",
                path=out.qc_picture,
                slices=slices,
            )
        ]
