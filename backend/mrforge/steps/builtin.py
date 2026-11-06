"""Importing this module registers every built-in step."""

from mrforge.steps import (  # noqa: F401
    alps_index,
    alps_rois,
    aroma_classify,
    bet,
    dwi_dti,
    dwi_eddy,
    dwi_mrtrix,
    dwi_to_template,
    dwi_topup,
    fake,
    feat_preproc,
    fieldmap_prep,
    fsl_anat,
    func_qc,
    func_to_mni,
    ica_labels,
    melodic,
    regfilt,
    resample_t1,
)
