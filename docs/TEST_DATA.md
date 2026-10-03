# Test data

Location (outside the repo, never committed): `~/Documents/mri-test-data/`

## What exists now

| Item | Description |
|---|---|
| `test/` | One DICOM session in DICOMDIR layout (`DICOMDIR`, `DICOM/<study>/<series>/...`), about 1.2 GB, 1064 files, 3 top-level series folders. |
| `test.zip` | The same data zipped (497 MB). Useful for testing ZIP import. |

Notes:
- This is real scanner data, so it **may contain patient identifying information** in DICOM headers and in the zip's internal folder name. Do not share it, put it in git, or paste its contents in docs/issues. Consider de-identifying a copy for any shared use.
- It is not "tiny": it is fine for Stage 2 (import) but too big for fast unit tests. Unit tests should use small synthetic or trimmed files.
- Contents have not been inspected yet (series types, T1/BOLD presence, fieldmaps). Stage 2a will produce that list.

## Still needed

- [ ] A small public fMRI dataset (for example from OpenNeuro) with a T1 and a resting BOLD, in BIDS format. Dataset name/link: ___
- [ ] A dataset **with** fieldmaps, to test fieldmap correction. Name/link: ___ (the app must also work with datasets without fieldmaps)
- [ ] Tiny test files for fast tests (few volumes, small matrix), kept outside git.

## Per-dataset description (fill in)

For each dataset record: source/link, license, subjects, modalities present, fieldmap type (if any), voxel size, TR, number of volumes.
