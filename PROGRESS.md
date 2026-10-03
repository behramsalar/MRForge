# Progress

**Current stage:** 2 (Import and BIDS), branch `stage-2-import`. Stages 0 and 1 accepted (tags `stage0-accepted`, `stage1-accepted`).

## Stage 1 (accepted)
Headless engine: workspace + SQLite, Step contract, job runner with stale-job recovery, provenance and resume, `mrforge` CLI, FakeStep, `bet`, `fsl_anat`. Amendments made at acceptance: subcortical segmentation is opt-in; results use a full BIDS derivatives layout (`derivatives/mrforge/sub-XXX/[ses-YY/]anat/` with BIDS names, native `sub-001_T1w.anat/`, per-step `_runs/<label>/`).

Last test status: `pytest -m "not fsl"` 82 passed; `pytest -m "fsl and not slow"` 6 passed; `pytest -m "fsl and slow"` kill test passed (24 s) and full `fsl_anat` vs manual run passed (18 min 30 s); ruff and mypy clean.

## Stage 2 sub-steps
| Sub-step | Status |
|---|---|
| 2a Scan + metadata | done |
| 2b Classification | done |
| 2c Conversion (dcm2niix) | not started |
| 2d BIDS organizer | not started |
| 2e Validator + plain-language messages | not started |
| 2f Import existing NIfTI / BIDS | not started |

## Known issues / limits
- The installed BIDS validator (npm `bids-validator` 1.15.0) predates derivatives support and rejects `desc-` files as 'not part of BIDS'. Layout is checked by tests and by eye; validator upgrade is proposed for Stage 2e.
- One `fsl_anat` per T1 input per subject: two runs with different labels on the same input would share the native `.anat` folder and several result names.
- One `LocalJobQueue` per workspace at a time (two could start the same queued job).
- Pipelines run steps sequentially; per-subject parallelism is Stage 6.
- No QC output yet for `bet`/`fsl_anat` (QC contract exists; real QC arrives in Stage 5).
- `fsl_anat` leaves stray `imcp.e<PID>`/`imcp.o<PID>` files; ignored.
- The claim "fsl_anat on a skull-stripped input skips registration" is from the script source, not an experiment.
- Test data is full-size DICOM, possibly with identifying information.

## Open questions
- Lab members for UX feedback (needed from Stage 3/4).
- Fieldmap handling: your DICOM set contains gradient-echo field maps; types to confirm before Stage 5c.

## Next action
Sub-step 2c: conversion with dcm2niix (verify flags with `--help`), outputs checked against the scan.
