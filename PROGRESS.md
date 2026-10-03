# Progress

**Current stage:** 2 (Import and BIDS), branch `stage-2-import`. Stages 0 and 1 accepted (tags `stage0-accepted`, `stage1-accepted`).

## Stage 1 (accepted)
Headless engine: workspace + SQLite, Step contract, job runner with stale-job recovery, provenance and resume, `mrforge` CLI, FakeStep, `bet`, `fsl_anat`. Amendments made at acceptance: subcortical segmentation is opt-in; results use a full BIDS derivatives layout (`derivatives/mrforge/sub-XXX/[ses-YY/]anat/` with BIDS names, native `sub-001_T1w.anat/`, per-step `_runs/<label>/`).

Last test status: `pytest -m "not fsl"` 82 passed; `pytest -m "fsl and not slow"` 6 passed; `pytest -m "fsl and slow"` kill test passed (24 s) and full `fsl_anat` vs manual run passed (18 min 30 s); ruff and mypy clean.

## Stage 2 (Import and BIDS): all sub-steps done, waiting for "stage accepted"
| Sub-step | Status |
|---|---|
| 2a Scan + metadata | done |
| 2b Classification (rules, confidence, user decisions) | done |
| 2c Conversion (dcm2niix, checked against the scan) | done |
| 2d BIDS organizer (names, privacy filter, fieldmaps, IntendedFor) | done |
| 2e BIDS validator + plain-language messages | done |
| 2f Import existing NIfTI files / BIDS datasets | done |

Last test status: `pytest -m "not fsl"` 267 passed (includes real-session tests and real-validator tests); `pytest -m "fsl and not slow"` 6 passed; `pytest -m "fsl and slow" -k kill` passed. The slow full `fsl_anat` comparison (about 19 minutes) was not re-run in Stage 2 (the engine and the FSL steps were not changed). ruff and mypy clean.

Demo workspace with your real session imported: `~/Documents/mrforge-workspaces/import-test`.

## Known issues / limits
- The installed BIDS validator (npm `bids-validator` 1.15.0) checks raw datasets fully but predates derivatives support (it rejects `desc-` files), so `derivatives/` is not validated yet; a newer validator would be needed.
- Import: classification rules are derived from one Siemens session; other vendors will need more examples. Fieldmap-to-run pairing is a heuristic (latest fieldmap before a run; editable with `import set --fieldmap`). One subject per DICOM import. Adding a series later that needs renaming already-written files (for example a second run of the same task) is refused; start a new workspace.
- Several full-size copies exist while importing (DICOM copy, converted files, rawbids is hard-linked); `sourcedata/` and `imports/…/converted/` can be removed by hand once an import is final, but MRForge does not do this itself yet.
- One `fsl_anat` per T1 input per subject: two runs with different labels on the same input would share the native `.anat` folder and several result names.
- One `LocalJobQueue` per workspace at a time (two could start the same queued job).
- Pipelines run steps sequentially; per-subject parallelism is Stage 6.
- No QC output yet for `bet`/`fsl_anat` (QC contract exists; real QC arrives in Stage 5).
- `fsl_anat` leaves stray `imcp.e<PID>`/`imcp.o<PID>` files; ignored.
- The claim "fsl_anat on a skull-stripped input skips registration" is from the script source, not an experiment.
- Test data is full-size DICOM, possibly with identifying information.

## Open questions
- Real task names for series 19 and 25 of your session (waiting for `mrforge import set <series> --task <name>`).
- Privacy list defaults (`sidecar_privacy.yaml`), `IntendedFor` for diffusion runs: your review.
- Lab members for UX feedback (needed from Stage 3/4).
- Fieldmap handling: your DICOM set contains gradient-echo field maps; types to confirm before Stage 5c.

## Next action
User runs the Stage 2 manual checklist and says "stage accepted" (or lists changes). Then merge to `main`, tag `stage2-accepted`, plan Stage 3.
