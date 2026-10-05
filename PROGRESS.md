# Progress

**Current stage:** Stage 6 (artifact rejection) in progress on branch `stage-6-artifact-rejection`; Stage 4 accepted and merged (`stage4-accepted`); Stages 0-3 and 5 accepted.

Stage 6 sub-steps: 6a `melodic` (done: fixed seed, per-component pictures and maps, maps on the T1) | 6b "Waiting for you" state, `ica_labels` gate, label saving (done) | 6c `regfilt` (done, identical to a manual `fsl_regfilt`) | 6d labelling on the review screen (done) | 6e artifact stage in the full-processing dialog (done; run end to end on a copy of the demo data) | 6f ICA-AROMA (not started; needs your approval to install it).

Last test status: `pytest -m "not fsl"` 476 passed, 19 deselected; frontend 26 passed, `tsc`, ruff and mypy clean. Real FSL: melodic, regfilt and fixed-seed tests pass; full flow on a copy of `sub-ali` (357 volumes): MELODIC 6 min (57 components), pause, labels saved, regfilt, standard space on cleaned data: all done. The whole `-m fsl` suite was not re-run since Stage 5.

REVIEW(domain) items of Stage 6: z threshold 2.3 of the maps; automatic dimensionality; fixed seed 1; partial (non-aggressive) removal default; uncertain kept as signal; variance-removed metric definition; slice summary every 5 mm; MELODIC `--nobet` with FEAT's mask.

Stage 6 manual checklist: see CLAUDE.md Stage 6; to try the review screen without touching real workspaces see `mri-test-data/ica-real` (MELODIC result) and `mri-test-data/full-art` (full flow).

## Stage 5 (Functional preprocessing, on FEAT)
| Sub-step | Status |
|---|---|
| 5-0 Spike: FEAT headless from a written design.fsf | done (`docs/DECISIONS.md`) |
| 5a design.fsf writer | done |
| 5b `fieldmap_prep` (Siemens gradient-echo) | done |
| 5c `feat_preproc` (motion, brain extraction, unwarping, smoothing, high-pass, BBR registration to the fsl_anat T1) | done |
| 5d `func_qc` (motion plot and framewise displacement, registration and unwarping pictures; QC stored in provenance) | done |
| 5e `func_to_mni` (fsl_anat warp + FEAT affine, one resampling) | done |
| 5f Functional pipeline builder, API routes, Functional screen with QC and viewer overlays | done |
| 5g Optional slice timing (off by default) | done |

Last test status: `pytest -m "not fsl"` 378 passed; `pytest -m fsl` (38 min, includes the slow `fsl_anat` and FEAT comparison tests): 13 passed, 2 failed in `tests/test_func_qc.py` because the test looked for the old run-record folder name (fixed afterwards; that file now passes, 9 of 9, but the whole `-m fsl` suite was not run again). Frontend `npm test` 9 passed, `tsc` clean; ruff and mypy clean. Not tested: a full 360-volume run through the UI (the 20-volume example `func-e2e` was run from the UI); killing and resuming the functional pipeline from the UI (the same mechanisms are tested for FEAT and for `fsl_anat`).

Also changed in Stage 5: run records are keyed by recording (`_runs/<step>_task-rest_run-1/`) so two BOLD runs of one subject no longer overwrite each other's provenance; CLAUDE.md principle 2 and the Stage 5 list were amended (FEAT as one Step).

## Stage 3 (API + first real UI)
| Sub-step | Status |
|---|---|
| 3a API: queue made API-ready, structured job errors (schema v3, auto-migration), operations (detached workers), FastAPI routes, SSE state, file serving with ranges, `mrforge serve`, generated typed client | done |
| 3b Viewer: NiiVue 0.69.0 chosen after spike (`docs/viewer-decision.md`) | done |
| 3c Design system: Radix Themes, `frontend/src/theme/tokens.ts`, `docs/design-system.md`, CLAUDE.md section 11 | done (look to be judged with the full UI) |
| 3d Redis + RQ | skipped on purpose (`docs/DECISIONS.md`) |
| 3e Screens: workspaces, import (folder picker, series table with decisions, import), anatomical processing with live status, viewer | done |
| 3f Failure UX: plain-language error, View log, Retry step / Resume pipeline, Cancel | done |

Last test status: `pytest -m "not fsl"` 319 passed, 1 failed: `tests/test_cli.py::test_ctrl_c_cancels_the_running_job` (a Stage 1 test) returned exit code 0 instead of 130 once during the full run; it passed 5 of 5 times when run alone (looks like a timing race under load, not investigated further). `pytest -m fsl` was not run this stage. Frontend: `npm test` 7 passed, `tsc --noEmit` clean. ruff and mypy clean.

Checked by hand in the browser pane (real FSL): import of a real zipped session through the UI; `fsl_anat` started from the UI; backend killed and restarted while it ran (job, worker and status survived); job worker killed (shows "Stopped early" with Resume and View log); Resume restarted it; Cancel stopped everything with no leftover processes; page reload mid-job showed the correct state; viewer with grey-matter overlay on the demo result. A full `fsl_anat` run to completion through the UI was not done (about 19 minutes).

## Stage 1 (accepted)
Headless engine: workspace + SQLite, Step contract, job runner with stale-job recovery, provenance and resume, `mrforge` CLI, FakeStep, `bet`, `fsl_anat`. Amendments made at acceptance: subcortical segmentation is opt-in; results use a full BIDS derivatives layout (`derivatives/mrforge/sub-XXX/[ses-YY/]anat/` with BIDS names, native `sub-001_T1w.anat/`, per-step `_runs/<label>/`).

Last test status: `pytest -m "not fsl"` 82 passed; `pytest -m "fsl and not slow"` 6 passed; `pytest -m "fsl and slow"` kill test passed (24 s) and full `fsl_anat` vs manual run passed (18 min 30 s); ruff and mypy clean.

## Stage 2 (Import and BIDS): accepted
| Sub-step | Status |
|---|---|
| 2a Scan + metadata | done |
| 2b Classification (rules, confidence, user decisions) | done |
| 2c Conversion (dcm2niix, checked against the scan) | done |
| 2d BIDS organizer (names, privacy filter, fieldmaps, IntendedFor) | done |
| 2e BIDS validator + plain-language messages | done |
| 2f Import existing NIfTI files / BIDS datasets | done |

Last test status: `pytest -m "not fsl"` 304 passed (includes real-session tests and real-validator tests); `pytest -m "fsl and not slow"` 6 passed; `pytest -m "fsl and slow" -k kill` passed. The slow full `fsl_anat` comparison (about 19 minutes) was not re-run in Stage 2 (the engine and the FSL steps were not changed). ruff and mypy clean.

Demo workspace with your real session imported: `~/Documents/mrforge-workspaces/import-test`.

## Known issues / limits
- The installed BIDS validator (npm `bids-validator` 1.15.0) checks raw datasets fully but predates derivatives support (it rejects `desc-` files), so `derivatives/` is not validated yet; a newer validator would be needed.
- Import: classification rules are derived from one Siemens session; other vendors will need more examples. Fieldmap-to-run pairing is a heuristic (latest fieldmap before a run; editable with `import set --fieldmap`). One subject per DICOM import. Adding a series later that needs renaming already-written files (for example a second run of the same task) is refused; start a new workspace.
- Several full-size copies exist while importing (DICOM copy, converted files, rawbids is hard-linked); `sourcedata/` and `imports/…/converted/` can be removed by hand once an import is final, but MRForge does not do this itself yet.
- One `fsl_anat` per T1 input per subject: two runs with different labels on the same input would share the native `.anat` folder and several result names.
- One `LocalJobQueue` per workspace at a time (two could start the same queued job).
- Pipelines run steps sequentially; per-subject parallelism is Stage 7.
- No QC output yet for `bet`/`fsl_anat` (QC contract exists; real QC arrives in Stage 5).
- `fsl_anat` leaves stray `imcp.e<PID>`/`imcp.o<PID>` files; ignored.
- The claim "fsl_anat on a skull-stripped input skips registration" is from the script source, not an experiment.
- Test data is full-size DICOM, possibly with identifying information.

- Stage 3: no login (by design); `mrforge serve` listens on 127.0.0.1 only unless `--host` is given, with a warning.
- Stage 3: only DICOM import and anatomical processing exist in the UI; NIfTI/BIDS import, QC, batch screens come later. Workspaces created before the BIDS layout (for example `demo`) show no T1 in the Anatomical screen because their input files are not registered as T1w in the database.
- Stage 3: Cancel records the running step as Cancelled, but a step killed by something else is "Stopped early".
- Stage 3: Retry step and Resume pipeline both run the latest pipeline again (finished steps are kept); there is no per-step retry of an older pipeline.
- Stage 3: the main page code is 134 kB gzipped; the viewer (NiiVue, 328 kB gzipped) loads only when opened.

## Open questions
- Revisit later: hard links between `rawbids/` and `imports/…/converted/` (works and is safe; the user may prefer one real copy and a tidier, per-subject `imports/` folder once the project is in order).
- Philips fieldmaps (the "B0 map" series): the user knows a method to use them; implement it when the time comes (import support for that fieldmap form, then Stage 5c). Philips data also has no phase-encoding direction, which must be supplied.
- Real task names for series 19 and 25 of your session (waiting for `mrforge import set <series> --task <name>`).
- Privacy list defaults (`sidecar_privacy.yaml`), `IntendedFor` for diffusion runs: your review.
- Lab members for UX feedback (needed from Stage 3/4).
- Fieldmap handling: your DICOM set contains gradient-echo field maps; types to confirm before Stage 5c.

## Next action
O6 (Jobs history, Settings, bell and failure screens) and O7 (polish, design-system document, manual checklist), then the lab user test. Later stages that plug into full processing: artifact rejection, WM/CSF regression, ROI-to-ROI correlation (add to the stage registry in `backend/mrforge/processing.py`). The Stage 5 REVIEW(domain) items are still open for the user.
