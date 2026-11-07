"""AlpsRoisStep: the four regions of interest of the DTI-ALPS index, in the space the index is
measured in.

Port of the ROI part of ``alps.sh`` (G. Barisano, MIT licence; lines 540-568 and 684-708):

* the ROIs are four spheres in the space of FSL's ``JHU-ICBM-FA-1mm`` (the same grid as
  ``MNI152_T1_1mm``): left and right projection fibres (superior corona radiata, SCR) and left
  and right association fibres (superior longitudinal fasciculus, SLF);
* source ``default`` = the packaged 2.5 mm spheres, ``legacy5`` = the older 5 mm set,
  ``sphere`` = new spheres of any radius made with the script's own ``fslmaths`` command (same
  centres), ``custom`` = four files of the researcher (order: SCR left, SCR right, SLF left,
  SLF right);
* space ``template``: the ROIs are used as they are, on the grid of the template-space FA map
  (an error says so when the grids differ); space ``native``: the JHU template is registered to
  the subject's FA map (``flirt`` 12 parameters, correlation ratio) and the ROIs are moved with
  that matrix (nearest neighbour).

REVIEW(domain): in native space the script moves custom ROI files from the JHU template space to
the native space too, although its README says custom ROIs for native space must already be in
native space. Here ``custom_in_analysis_space`` says which of the two is meant; the default
follows the code of the script (they are in template space and are moved).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from importlib import metadata
from pathlib import Path
from typing import Literal, cast

import numpy as np
from nibabel.loadsave import load as load_image
from nibabel.nifti1 import Nifti1Image
from pydantic import BaseModel, Field

from mrforge.hashing import sha256_of
from mrforge.niftiutil import is_readable_nifti
from mrforge.steps.base import Problem, QCItem, Step, StepContext, StepResult
from mrforge.steps.registry import register_step

DATA = Path(__file__).resolve().parents[1] / "data" / "alps_rois"
SETS = {"default": DATA / "2p5mm", "legacy5": DATA / "5mm_legacy"}
ROI_FILES = ("L_SCR", "R_SCR", "L_SLF", "R_SLF")  # projection L/R, association L/R
CENTRES = {  # voxel coordinates in the JHU-ICBM 1 mm grid (as in the script)
    "L_SCR": (116, 110, 99),
    "R_SCR": (64, 110, 99),
    "L_SLF": (128, 110, 99),
    "R_SLF": (52, 110, 99),
}
DESC = {"L_SCR": "LSCR", "R_SCR": "RSCR", "L_SLF": "LSLF", "R_SLF": "RSLF"}
TEMPLATES = {  # key -> (file under FSLDIR, name used in result names)
    "jhu_fa": ("data/atlases/JHU/JHU-ICBM-FA-1mm.nii.gz", "JHUFA1mm"),
    "mni_t1": ("data/standard/MNI152_T1_1mm_brain.nii.gz", "MNI152T1"),
    "jhu_t2": ("data/atlases/JHU/JHU-ICBM-T2-1mm.nii.gz", "JHUT21mm"),
}
JHU_FA = TEMPLATES["jhu_fa"][0]


def regions_tag(source: str, radius_mm: float = 2.5) -> str:
    """A short name for a set of regions, used in the labels of the two steps that depend on it
    so that every set keeps its own results. The packaged 2.5 mm spheres have no tag (their
    result names are the same as before region sets could be told apart)."""
    if source == "legacy5":
        return "legacy5"
    if source == "sphere":
        return "sphere" + f"{radius_mm:g}".replace(".", "p")
    if source == "custom":
        return "custom"
    return ""


def regions_text(source: str, radius_mm: float = 2.5) -> str:
    """The set of regions in plain language (plan, results table, export)."""
    return {
        "default": "packaged 2.5 mm spheres",
        "legacy5": "packaged 5 mm boxes (older)",
        "sphere": f"spheres of {radius_mm:g} mm radius",
        "custom": "your own four files",
    }.get(source, source)


def tagged_desc(step_name: str, label: str, base: str) -> str:
    """``desc-`` value of a result: ``base`` plus the region-set tag carried by the step label
    (``alps_rois_legacy5`` -> ``legacy5``)."""
    return base + re.sub(r"[^A-Za-z0-9]", "", label.removeprefix(step_name))


class AlpsRoisInput(BaseModel):
    fa: str  # the FA map in the space of the analysis (native, or already on the template)
    custom_rois: list[str] = []  # workspace-relative; four files when source is "custom"


class AlpsRoisParams(BaseModel):
    source: Literal["default", "legacy5", "sphere", "custom"] = "default"
    radius_mm: float = Field(default=2.5, gt=0, le=20)  # for source "sphere"
    space: Literal["template", "native"] = "template"
    template: Literal["jhu_fa", "mni_t1", "jhu_t2", "custom"] = "jhu_fa"
    template_file: str | None = None  # absolute path, when template is "custom"
    custom_in_analysis_space: bool = False  # custom ROIs already in the space of ``fa``


class AlpsRoisOutput(BaseModel):
    proj_l: str
    proj_r: str
    assoc_l: str
    assoc_r: str
    all_rois: str  # the four ROIs labelled 1-4 by ``cluster`` (for checking)
    info: str  # JSON: where the ROIs came from and how many voxels each has
    matrix: str | None = None  # native space: JHU template -> FA map (flirt matrix)


def template_path(fsldir: str, params: AlpsRoisParams) -> Path | None:
    """The template image the analysis is in (None: none was given for 'custom')."""
    if params.template == "custom":
        return Path(params.template_file) if params.template_file else None
    return Path(fsldir) / TEMPLATES[params.template][0]


def space_label(params: AlpsRoisParams) -> str:
    if params.space == "native":
        return "native"
    return TEMPLATES[params.template][1] if params.template != "custom" else "template"


def _load(path: Path) -> Nifti1Image:
    return cast(Nifti1Image, load_image(str(path)))


def voxel_count(path: Path) -> int:
    return int(np.count_nonzero(np.asarray(_load(path).dataobj)))


def _same_grid(a: Path, b: Path) -> bool:
    ia, ib = _load(a), _load(b)
    return tuple(ia.shape[:3]) == tuple(ib.shape[:3]) and bool(
        np.allclose(ia.affine, ib.affine, atol=1e-3)
    )


@register_step
class AlpsRoisStep(Step[AlpsRoisInput, AlpsRoisParams, AlpsRoisOutput]):
    name = "alps_rois"
    version = "1"
    InputSpec, ParamSpec, OutputSpec = AlpsRoisInput, AlpsRoisParams, AlpsRoisOutput
    requires_fsl = True
    datatype = "dwi"

    def desc(self, ctx: StepContext[AlpsRoisInput, AlpsRoisParams], base: str) -> str:
        return tagged_desc(self.name, ctx.label, base)

    def expected_outputs(self, ctx: StepContext[AlpsRoisInput, AlpsRoisParams]) -> AlpsRoisOutput:
        space = space_label(ctx.params)
        names = {
            roi: ctx.bids_name("mask", desc=self.desc(ctx, DESC[roi]), space=space)
            for roi in ROI_FILES
        }
        return AlpsRoisOutput(
            proj_l=names["L_SCR"],
            proj_r=names["R_SCR"],
            assoc_l=names["L_SLF"],
            assoc_r=names["R_SLF"],
            all_rois=ctx.bids_name("dseg", desc=self.desc(ctx, "ALPSrois"), space=space),
            info=ctx.bids_name("info", ".json", desc=self.desc(ctx, "ALPSrois"), space=space),
            matrix=(
                ctx.bids_name("xfm", ".mat", mode="image", **{"from": "JHUFA1mm", "to": "native"})
                if self._moves_rois(ctx)
                else None
            ),
        )

    @staticmethod
    def _moves_rois(ctx: StepContext[AlpsRoisInput, AlpsRoisParams]) -> bool:
        p = ctx.params
        return p.space == "native" and not (p.source == "custom" and p.custom_in_analysis_space)

    def validate_inputs(self, ctx: StepContext[AlpsRoisInput, AlpsRoisParams]) -> list[Problem]:
        problems = super().validate_inputs(ctx)
        p = ctx.params
        if problems:
            return problems
        if not is_readable_nifti(ctx.input_path(ctx.inputs.fa)):
            problems.append(
                Problem(
                    code="INPUT_NOT_NIFTI",
                    message=f"The FA map could not be read: {ctx.inputs.fa}",
                    probable_cause="The file is damaged or not a NIfTI image.",
                    suggested_action="Run the diffusion fit again.",
                )
            )
        if p.source == "custom" and len(ctx.inputs.custom_rois) != 4:
            problems.append(
                Problem(
                    code="ROI_NEED_FOUR",
                    message="Custom ROIs need exactly four files, in this order: projection "
                    "left, projection right, association left, association right.",
                    probable_cause=f"{len(ctx.inputs.custom_rois)} file(s) were given.",
                    suggested_action="Choose the four ROI files again.",
                )
            )
        if p.template == "custom" and (
            p.template_file is None or not Path(p.template_file).is_file()
        ):
            problems.append(
                Problem(
                    code="ROI_TEMPLATE_MISSING",
                    message="The template you chose could not be found.",
                    probable_cause="No template file was given, or it was moved.",
                    suggested_action="Choose the template file again.",
                )
            )
        return problems

    def tool_versions(self, ctx: StepContext[AlpsRoisInput, AlpsRoisParams]) -> dict[str, str]:
        return {"nibabel": metadata.version("nibabel")}

    def _fsldir(self, ctx: StepContext[AlpsRoisInput, AlpsRoisParams]) -> str:
        return (ctx.env or os.environ).get("FSLDIR", "")

    def run(self, ctx: StepContext[AlpsRoisInput, AlpsRoisParams]) -> StepResult:
        p = ctx.params
        fsldir = self._fsldir(ctx)
        fa = ctx.input_path(ctx.inputs.fa)
        work = ctx.run_dir / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        out = self.expected_outputs(ctx)
        targets = {
            "L_SCR": out.proj_l, "R_SCR": out.proj_r, "L_SLF": out.assoc_l, "R_SLF": out.assoc_r,
        }  # fmt: skip

        # 1. the four ROIs in template space (``source``)
        sources: dict[str, Path] = {}
        origin: dict[str, object] = {"source": p.source}
        if p.source in SETS:
            for roi in ROI_FILES:
                sources[roi] = SETS[p.source] / f"{roi}.nii.gz"
        elif p.source == "custom":
            for roi, rel in zip(ROI_FILES, ctx.inputs.custom_rois, strict=True):
                sources[roi] = ctx.input_path(rel)
        else:  # sphere: the script's own command, one voxel at the centre grown to a sphere
            grid = (
                Path(fsldir) / JHU_FA
                if p.space == "native"
                else template_path(fsldir, p) or Path(fsldir) / JHU_FA
            )
            origin["radius_mm"] = p.radius_mm
            for roi in ROI_FILES:
                x, y, z = CENTRES[roi]
                dest = work / f"{roi}_sphere.nii.gz"
                ctx.run_command(
                    [
                        "fslmaths", str(grid), "-mul", "0", "-add", "1",
                        "-roi", str(x), "1", str(y), "1", str(z), "1", "0", "1",
                        "-kernel", "sphere", f"{p.radius_mm:g}", "-fmean", "-bin",
                        str(dest), "-odt", "float",
                    ]
                )  # fmt: skip
                sources[roi] = dest
        origin["files"] = {
            roi: sha256_of(path)[:16] for roi, path in sources.items() if path.is_file()
        }

        # 2. into the space of the FA map
        final: dict[str, Path] = {}
        matrix_path: Path | None = None
        if self._moves_rois(ctx):
            matrix_path = ctx.output_dir / out.matrix if out.matrix else None
            assert matrix_path is not None
            ctx.run_command(
                [
                    "flirt", "-ref", str(fa), "-in", str(Path(fsldir) / JHU_FA),
                    "-out", str(work / "jhu_in_native"), "-omat", str(matrix_path),
                    "-bins", "256", "-cost", "corratio",
                    "-searchrx", "-90", "90", "-searchry", "-90", "90", "-searchrz", "-90", "90",
                    "-dof", "12",
                ]
            )  # fmt: skip
            for roi in ROI_FILES:
                dest = work / f"{roi}_native.nii.gz"
                ctx.run_command(
                    [
                        "flirt", "-in", str(sources[roi]), "-ref", str(fa), "-out", str(dest),
                        "-init", str(matrix_path), "-applyxfm", "-interp", "nearestneighbour",
                    ]
                )  # fmt: skip
                final[roi] = dest
        else:
            final = dict(sources)
            for roi, path in final.items():
                if not _same_grid(path, fa):
                    raise_grid_mismatch(roi, ctx.inputs.fa)

        # 3. results (copied under BIDS names) and the labelled picture of all four
        for roi in ROI_FILES:
            shutil.copyfile(final[roi], ctx.output_dir / targets[roi])
        ctx.run_command(
            ["fslmaths", str(final["L_SCR"]), "-add", str(final["R_SCR"]),
             "-add", str(final["L_SLF"]), "-add", str(final["R_SLF"]),
             "-bin", str(work / "all_sum")]
        )  # fmt: skip
        ctx.run_command(
            ["cluster", "-t", "1", "-i", str(work / "all_sum"), "-o", str(work / "all_labelled")]
        )
        shutil.copyfile(work / "all_labelled.nii.gz", ctx.output_dir / out.all_rois)

        counts = {roi: voxel_count(ctx.output_dir / targets[roi]) for roi in ROI_FILES}
        info = {
            **origin,
            "space": p.space,
            "template": p.template,
            "voxels": counts,
            "moved_to_native": self._moves_rois(ctx),
        }
        (ctx.output_dir / out.info).write_text(json.dumps(info, indent=2) + "\n")
        shutil.rmtree(work, ignore_errors=True)
        return StepResult()

    def validate_outputs(self, ctx: StepContext[AlpsRoisInput, AlpsRoisParams]) -> list[Problem]:
        problems = super().validate_outputs(ctx)
        if problems:
            return problems
        out = self.expected_outputs(ctx)
        for label, rel in (
            ("projection left", out.proj_l), ("projection right", out.proj_r),
            ("association left", out.assoc_l), ("association right", out.assoc_r),
        ):  # fmt: skip
            if voxel_count(ctx.output_dir / rel) == 0:
                problems.append(
                    Problem(
                        code="ROI_EMPTY",
                        message=f"The {label} region has no voxels in the space of the FA map.",
                        probable_cause="The FA map does not cover that region, or its alignment "
                        "to the template failed.",
                        suggested_action="Check the FA map and its registration pictures, then "
                        "try another registration setting.",
                    )
                )
        return problems

    def generate_qc(self, ctx: StepContext[AlpsRoisInput, AlpsRoisParams]) -> list[QCItem]:
        out = self.expected_outputs(ctx)
        items: list[QCItem] = []
        for label, rel in (
            ("Voxels in the projection ROI, left", out.proj_l),
            ("Voxels in the projection ROI, right", out.proj_r),
            ("Voxels in the association ROI, left", out.assoc_l),
            ("Voxels in the association ROI, right", out.assoc_r),
        ):
            items.append(QCItem(name=label, kind="metric", value=voxel_count(ctx.output_dir / rel)))
        return items


def raise_grid_mismatch(roi: str, fa_rel: str) -> None:
    from mrforge.errors import StepError

    raise StepError(
        code="ROI_GRID_MISMATCH",
        message=f"The ROI {roi} is not on the same grid as the FA map ({fa_rel}).",
        probable_cause="The ROIs are drawn on the 1 mm template, but the FA map is not in that "
        "space (it was not registered to the template, or to another template).",
        suggested_action="Use the registration to the template in this step, or analyse in "
        "native space (the ROIs are then moved to the subject).",
    )
