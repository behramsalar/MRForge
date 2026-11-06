# ALPS regions of interest

Four spherical regions of interest drawn on FSL's `JHU-ICBM-FA-1mm.nii.gz` (182 x 218 x 182 voxels,
1 mm) by Giuseppe Barisano for the DTI-ALPS index, copied unchanged from
https://github.com/gbarisano/alps (MIT licence, see `LICENSE`):

| File | Region | Centre voxel (x, y, z) |
|---|---|---|
| `L_SCR` | left projection fibres (superior corona radiata) | 116, 110, 99 |
| `R_SCR` | right projection fibres | 64, 110, 99 |
| `L_SLF` | left association fibres (superior longitudinal fasciculus) | 128, 110, 99 |
| `R_SLF` | right association fibres | 52, 110, 99 |

* `2p5mm/` - the current set (spheres of 2.5 mm radius, 81 voxels each) plus `all_ROIs.nii.gz`.
* `5mm_legacy/` - the earlier set (5 mm radius, 515 voxels each).

If you use the ALPS index, please cite: Liu X, Barisano G, et al. Cross-Vendor Test-Retest Validation
of Diffusion Tensor Image Analysis along the Perivascular Space (DTI-ALPS) for Evaluating Glymphatic
System Function. Aging and Disease (2023), https://doi.org/10.14336/AD.2023.0321-2, and report the
repository link above.
