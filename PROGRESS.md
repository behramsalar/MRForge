# Progress

**Current stage:** 1 (Headless engine), branch `stage-1-engine`. Stage 0 accepted (tag `stage0-accepted`).

| Sub-step | Status |
|---|---|
| 1a Models + SQLite, workspace create/open | done |
| 1b Step base, registry, specs, StepError | done |
| 1c Job runner (worker processes, stale-job recovery, JobQueue) | done |
| 1d Provenance, hash cache, resume, pipelines | done |
| 1e CLI (`mrforge`) | done |
| 1f FakeStep | done (delivered with 1c; fail-once option with 1e) |
| 1g BetStep + FSL lookup | done |
| 1h FslAnatStep | done |
| Amendments after review | subcortical segmentation opt-in; full BIDS derivatives layout (in progress: verifying with real runs) |
| Stage-end protocol | done once; redone after the amendments |

## Test status (last run)
- `pytest -m "not fsl"`: 71 passed
- `pytest -m "fsl and not slow"`: 6 passed
- `pytest -m "fsl and slow"`: kill test passed (23 s); full fsl_anat vs manual run passed (21 min 20 s)
- ruff and mypy: clean

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
User runs the Stage 1 manual checklist and says "stage accepted" (or lists changes). Then merge to `main`, tag `stage1-accepted`, and plan Stage 2.
