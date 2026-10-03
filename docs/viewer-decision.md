# Viewer decision (Stage 3b)

**Decision:** NiiVue 0.69.0 (BSD-2-Clause), chosen by the user on 2026-10-03 on the condition
that it is lightweight and integrates seamlessly. Both conditions were tested.

## Why not VoxelLab
No project of that name could be found, so it could not be compared. Other candidates seen
(VolView, dwv) are full applications or DICOM-oriented; NiiVue is a small library built for NIfTI.

## Spike results (2026-10-03, Chrome-class WebGL2 on an Apple M2)
| Question | Result |
|---|---|
| Size | Whole page (React + NiiVue + API client): 1.1 MB minified, **396 kB gzipped**. NiiVue is the bulk. Loaded only on the viewer screen later (code-splitting). |
| Effort | One React component (`frontend/src/components/Viewer.tsx`, about 40 lines): underlay plus overlays from the API's image list. |
| Overlay alignment | fsl_anat's brain mask and tissue segmentation (written in fsl_anat's cropped, reoriented space) lay exactly on the original T1 (checked visually in axial, coronal, sagittal). No resampling or extra code was needed: NiiVue places every volume by its own header. |
| File loading | NIfTI `.nii.gz` straight from `/api/workspaces/<id>/file/...` (byte ranges supported). |
| Licence | BSD-2-Clause, free for lab and commercial use. |
| Warnings | "voxels not aligned with world space: 1.8 degrees from plumb" for the T1: the scan is slightly oblique. Harmless; NiiVue handles it. |

## Known limits
- Needs WebGL2 (any current browser). A machine without GPU acceleration will be slow.
- NiiVue's `next` line (1.0 release candidates) changes the packaging; we pin 0.69.0 and revisit later.
