# Decisions

Format: date, decision, reason.

| Date | Decision | Reason |
|---|---|---|
| 2026-10-03 | App name is **MRForge** (CLI `mrforge`, outputs in `derivatives/mrforge/`). | User choice. Replaces the `mriapp` placeholder. |
| 2026-10-03 | Python packages are installed in the user's venv `~/progders` (Python 3.13). Project requires Python >= 3.11. | User instruction. |
| 2026-10-03 | Test data lives outside the repo at `~/Documents/mri-test-data/`. | CLAUDE.md section 4: never commit imaging data. |
| 2026-10-03 | Lint/format with ruff, types with mypy (strict), tests with pytest. | CLAUDE.md section 3 offers "mypy or pyright"; mypy chosen as the default. |
| 2026-10-03 | Provenance files are the durable record; SQLite is a rebuildable index. | A broken database must never lose results. |
| 2026-10-03 | File hashes are cached by (path, size, mtime) and recomputed only when those change. | Hashing large 4D scans on every resume check is slow. |
| 2026-10-03 | Interrupted jobs are detected at startup using the recorded process ID plus process start time. | Survives reboots and reused process IDs. |
| 2026-10-03 | FSL is **not** tied to a fixed path. Lookup order: app setting, then `FSLDIR` environment variable, then common install locations. If none works, show a clear message explaining where to set it. The runner builds the FSL environment from the resolved location. | The app must run on other machines. |
| 2026-10-03 | Provenance stores workspace-relative paths. | Workspaces stay movable/copyable. |
| 2026-10-03 | Sessions (`ses-*`) are optional; omitted from paths when absent. | Keeps single-scan workspaces simple. |
| 2026-10-03 | `fsl_anat` is one step; an interrupted run restarts from the beginning. | Simple and safe. |
| 2026-10-03 | The app must work both with and without fieldmap data. Fieldmap correction is offered only when fieldmaps exist (CLAUDE.md principle 9). | User requirement. |
| 2026-10-03 | No user accounts or login system. | Out of scope per CLAUDE.md section 9. |
| 2026-10-03 | Each step run writes `provenance.json` (including failed, interrupted and cancelled runs). The worker deletes the old record before running, so a stale "Completed" record can never be trusted after a crash. | Principle 4 (provenance for every run) and principle 5 (resume must be safe). |
| 2026-10-03 | A previous run is reusable only if its provenance says Completed, it is the latest job for that output folder, version and parameter hash match, input hashes match, outputs exist, pass `validate_outputs` and still match their recorded hashes. | Architecture section 7, plus a tamper check on outputs. |
| 2026-10-03 | Downstream invalidation is two-layered: input hashes (automatic) and, inside a pipeline, any step that reruns forces all steps that use its outputs to rerun, even if the new output is byte-identical. | CLAUDE.md: "if an upstream step changes, downstream steps are invalidated". |
| 2026-10-03 | Output folders are named by a `label` (default: the step name; pipelines use the step id) so one step can appear twice for the same subject. | Needed for pipelines and tests with repeated steps. |
| 2026-10-03 | Pipelines are YAML files with `${stepid.outputfield}` references; they run sequentially and stop at the first failure. Resume = run the same spec again. | Smallest design that supports "fail at step 3, then resume". |
| 2026-10-03 | Only one `LocalJobQueue` should drive a workspace at a time. | Two queues could start the same queued job twice; sufficient for one CLI or API process. |
| 2026-10-03 | `bet` is an **optional, independent** step. Its output is never an input to `fsl_anat`; `fsl_anat` always takes the original T1 with skull. | `fsl_anat` does its own brain extraction (from the non-linear registration to MNI; BET only as a rough mask). Its script (FSL 6.0.7.23, `bin/fsl_anat` lines 536-537) skips registration to standard space when told the input is already brain-extracted ("it requires a non-brain-extracted input image"), and the later planned step 5g needs that registration. Not run empirically; based on the script source. |
| 2026-10-03 | Steps that need FSL declare `requires_fsl`; the worker resolves FSL (app setting, `FSLDIR`, common locations) and builds the environment, and records the FSL version in provenance. `mrforge config fsl <path>` sets the location. | Decision "no fixed FSL path"; non-login shells lack `FSLDIR`. |
| 2026-10-03 | Test T1 for FSL tests: series `2_t1w` (192x256x256, 1 mm) from the DICOM set, converted once with dcm2niix into `mri-test-data/nifti/t1w.nii.gz`. | Stage 1 needs a NIfTI T1; real DICOM import is Stage 2. |
