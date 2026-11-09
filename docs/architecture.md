# MRForge architecture

Status: **draft for user review (Stage 0)**. Derived from `CLAUDE.md` sections 5 and 6. Anything not in CLAUDE.md is marked **[PROPOSAL]** and listed under Open questions.

## 1. Layers

```text
UI (React)  ->  API (FastAPI)  ->  Services  ->  Step objects  ->  Job runner  ->  FSL / dcm2niix (subprocess)
                                       |                                 |
                                   SQLite (state index)        provenance.json + logs next to outputs
```

- The UI never builds shell commands. Only `Step` classes know command lines.
- The CLI (`mrforge`) and the API both call the same services. Stages 1-2 are CLI only.
- Heavy work runs in worker processes behind a `JobQueue` interface (local process pool first).

## 2. Workspace layout on disk

```text
<workspace>/
    workspace.json             # name, created, schema_version
    db.sqlite                  # state index
    sourcedata/dicom/          # original DICOMs, immutable
    rawbids/                   # BIDS dataset, immutable after creation
    derivatives/mrforge/            # a BIDS derivatives dataset
        dataset_description.json    # DatasetType "derivative"; GeneratedBy lists MRForge and FSL versions
        .bidsignore                 # hides MRForge-only folders (_runs/, *.anat/) from BIDS validators
        sub-XXX/[ses-YY/]anat/      # results with BIDS names, e.g. sub-001_desc-brain_mask.nii.gz
            sub-XXX_T1w.anat/       # native fsl_anat folder, named after the input image
            _runs/<label>/          # one folder per step run: provenance.json, logs/stdout.log, stderr.log
        sub-XXX/[ses-YY/]func/      # the results people open (bold, masks, boldref), plus sorted subfolders:
            qc/  ica/  transforms/  feat/  connectivity/<atlas>/    # see layout.py (rule below)
    imports/import-NNN/manifest.json   # scan results, user decisions, conversion provenance
    reports/
```

Rules: `sourcedata/` and `rawbids/` are never modified after creation. All results go under `derivatives/`. A workspace with one scan is simply `sub-001`.

**Sorted subfolders (func).** `layout.subfolder_for(name, datatype)` decides from the file name alone where a result goes: `*_qc.*`, `*_qc_slices/` and the motion series to `qc/`; components, labels, AROMA and noise-removal files and `*.ica` to `ica/`; `*_xfm.*` to `transforms/`; `*.feat` to `feat/`; every file with a `seg-<atlas>` entity to `connectivity/<atlas>/`; everything else stays in the datatype folder. `StepContext.bids_name()` applies it, so a step's declared output is simply `qc/sub-..._qc.png` and nothing else in a step changes. Only `func` is sorted; `anat` and `dwi` stay flat. `workspace.json` carries `layout_version` (2); older workspaces are moved by `mrforge workspace migrate` (`migrate_layout.py`: files are renamed, recorded paths, hashes of rewritten result files and the database follow; nothing is recomputed) and starting work in an unmigrated workspace is refused with `WORKSPACE_LAYOUT_OLD`.

**Naming.** Result files follow BIDS derivatives naming: entities taken from the input file (`sub`, `ses`, `acq`, `run`, ...) plus `space-`, `desc-`, `label-`, `from-`/`to-`/`mode-` as needed, then a suffix (`T1w`, `mask`, `dseg`, `probseg`, `xfm`). The BIDS-named results of a step are hard links to (or copies of) the tool's native files, so the native folder stays intact for FSL tools that expect it. Each step declares its BIDS datatype folder (`anat`, `func`, ...). The per-step record (`_runs/<label>/`) is MRForge-specific and listed in `.bidsignore`.

## 3. Entities

`Workspace, Subject, Session, Acquisition, File, Pipeline, PipelineRun, ProcessingStep, Job, QCResult, UserDecision, Report, Atlas, ROI`.

Stage 1a implements only Workspace, Subject, File, Job/StepRun. The rest stay as named placeholders until needed.

## 4. Step contract

```python
class Step:
    name: str
    version: str                          # bump on behavior change; part of resume hash
    InputSpec / ParamSpec / OutputSpec    # pydantic v2 models

    def validate_inputs(self, ctx) -> list[Problem]
    def prepare(self, ctx) -> None
    def run(self, ctx) -> StepResult      # builds and executes commands
    def validate_outputs(self, ctx) -> list[Problem]
    def generate_qc(self, ctx) -> list[QCItem]
    def register_outputs(self, ctx) -> None
```

Lifecycle order: validate_inputs -> prepare -> run -> validate_outputs -> register_outputs -> generate_qc. If validate_inputs returns problems, the step does not run. Steps declare dependencies on other steps by naming the upstream outputs they consume (a DAG, not a fixed list), so the UI can look linear while the engine stays modular. Each step lives in its own module; no `preprocess_subject()`.

### Additions made during Stage 1 (see DECISIONS.md)

- `Step.requires_fsl`: the runner then supplies an FSL environment and records the FSL version.
- `Step.tool_versions(ctx)` and `Step.output_relpaths(ctx)` helpers; inputs are workspace-relative file paths (every `str` / `list[str]` field of an InputSpec is a path).
- Output folders are named by a `label` (default: the step name; pipelines use the step id).
- Pipelines are YAML files; later steps refer to earlier results with `${stepid.outputfield}`.

## 5. Jobs

States: `Queued, Running, Completed, Failed, Cancelled, Interrupted`.

```text
Queued -> Running -> Completed | Failed | Cancelled
Running -> Interrupted        (set at startup if a Running job has no live process)
```

- On startup the runner marks stale `Running` jobs `Interrupted`.
- **[PROPOSAL]** Liveness is decided by a recorded PID plus process start time, not just PID, to survive PID reuse after a reboot.
- Max concurrency is configurable. Jobs wait rather than oversubscribe (richer scheduling in Stage 7).

## 6. Provenance

Written as `provenance.json` next to each step's outputs. Fields:

```json
{
  "schema_version": 1,
  "step": {"name": "bet", "version": "1"},
  "job_id": 1,
  "subject": "sub-001", "session": null,
  "parameters": {"frac": 0.5, "robust": false, "mask": true},
  "parameter_hash": "sha256:...",
  "inputs":  [{"path": "rawbids/sub-001/anat/sub-001_T1w.nii.gz", "sha256": "..."}],
  "outputs": [{"path": "derivatives/mrforge/sub-001/bet/brain.nii.gz", "sha256": "..."}],
  "commands": [{"argv": ["bet", "...", "-f", "0.5", "-m"], "return_code": 0,
                "stdout_log": "derivatives/mrforge/sub-001/bet/logs/stdout.log",
                "stderr_log": "derivatives/mrforge/sub-001/bet/logs/stderr.log"}],
  "tool_versions": {"mrforge": "0.0.0", "fsl": "6.0.7.23"},
  "started": "2026-10-03T10:00:00Z", "finished": "2026-10-03T10:00:12Z",
  "status": "Completed", "return_code": 0,
  "error_code": null, "error_message": null
}
```

A record is written for every run, including Failed, Interrupted and Cancelled ones (outputs are empty then). The worker deletes the previous record before running, so a stale "Completed" record is never trusted.

Paths are stored relative to the workspace so a workspace can be moved. The SQLite database is an index; provenance files are the durable record and the database should be rebuildable from them where possible.

## 7. Resume rule

A prior step run is reusable only if **all** hold:

1. status `Completed`
2. same step `version`
3. same `parameter_hash`
4. same input file hashes
5. all registered outputs exist and pass `validate_outputs`

If an upstream step is rerun or invalidated, every downstream step that consumed its outputs is invalidated. Resume starts at the first non-reusable step. A completed, valid step is never rerun.

## 8. Error model

Steps raise structured errors:

```python
class StepError(Exception):
    code: str  # e.g. "BET_INPUT_UNREADABLE"
    message: str  # plain language: what happened
    probable_cause: str  # why it likely happened
    suggested_action: str  # what to do next
    log_path: Path | None  # raw log stays one click away
```

All codes are catalogued in `docs/errors.md`. Raw tool output is never the only thing shown.

## 9. Other principles that shape the design

- QC flags, never decides. Accept/Review/Exclude is a recorded `UserDecision` with a required reason.
- Reports and methods text are generated deterministically from provenance.
- Never invent FSL flags; verify against `--help`/docs. Uncertain scientific choices carry `# REVIEW(domain)`.

## 10. Environment notes (this machine)

macOS arm64, FSL 6.0.7.23 at `~/fsl`, project Python venv `~/progders`. Non-login shells do not load `FSLDIR` (set in `~/.zprofile`). The app must run on other machines, so **no FSL path is hard-coded**. The FSL location is resolved in this order: app setting, then the `FSLDIR` environment variable, then common install locations; if none works the UI shows a plain message about where to set it. The job runner then builds the subprocess environment from the resolved location (`FSLDIR`, `PATH`, `FSLOUTPUTTYPE=NIFTI_GZ`) rather than inheriting whatever shell started the server. (Decided 2026-10-03, see `DECISIONS.md`.)

## 11. Glossary

- **Workspace**: container for data and processing state; one scan or a whole dataset.
- **Step**: one operation with declared inputs, params, outputs, validation, QC.
- **Pipeline**: an ordered/dependency-linked set of steps; a **PipelineRun** is one execution.
- **Job**: a queued/running execution of one step for one subject.
- **Provenance**: the machine-readable record of exactly what ran.
- **BIDS**: Brain Imaging Data Structure, the standard folder/naming layout used in `rawbids/`.
- **Derivatives**: all processed outputs, kept apart from raw data.
- **QC item**: an image/plot/metric produced by a step for human review.

## 12. Open questions (for you)

Questions 1-7 (source of truth, hash caching, crash detection, FSL lookup, relative paths, optional sessions, `fsl_anat` as one step) were answered on 2026-10-03; see `DECISIONS.md`. Still open:

1. **Fieldmap types** the lab's scanner produces (needed before Stage 5c). The app must work with and without fieldmaps.
2. **Lab members for UX feedback** (CLAUDE.md section 0; needed from Stage 3/4 only).

## 13. Import (Stage 2)

```text
DICOM folder/zip --scan--> sourcedata/dicom/import-NNN/ (copy) + imports/import-NNN/manifest.json
                  --classify (rules + your decisions: import set)--> what each series is, with confidence
                  --convert (dcm2niix, one series at a time)--> imports/import-NNN/converted/s<series>/
                  --organize--> rawbids/ (BIDS names, privacy-filtered sidecars, read-only)
                  --validate--> imports/bids-validation.json (BIDS validator, plain-language messages)
NIfTI files  ------ import nifti (copy, checks) ----------------^ (same organize step)
BIDS dataset ------ import bids (copy, no conversion) ----------> rawbids/
```

**One entry point in the web interface.** The chosen folder or archive is first looked at (`importing/inspect.py`, route `POST /imports/inspect`, nothing is read or copied) and routed:
- *DICOM* (a folder, or one archive): as above.
- *Several archives in one folder* (`importing/archives.py`): each archive is scanned as its own source (an archive may itself hold several studies); all scans are shown as one group; an unreadable archive is reported and does not stop the others.
- *Loose NIfTI files* (`importing/nifti_scan.py`): a folder (or a `sub-XX` in the file names) is one subject and one scan. Each file is a "series" described from its sidecar and header; the same rule engine proposes a type, unsure files ask. Files of one scanner series (same series number, description and size, e.g. the echoes of a fieldmap) stay together as one series with several images, so fieldmaps work as for DICOM. Files are copied into `imports/import-NNN/converted/` at scan time (source kind `nifti`), `convert_import` only checks shapes and diffusion directions, and `organize` writes `rawbids/` as for DICOM.
- *BIDS dataset*: checked with the validator and copied by `import_bids` as one finished import (no review table).
- A folder that mixes kinds is explained, never guessed.

A diffusion series with a single volume (a reverse phase-encoding b0 for TOPUP) is written to `fmap/..._dir-XX_epi` with `IntendedFor` (see DECISIONS.md 2026-11-06).

- **Manifest** (`imports/import-NNN/manifest.json`): the scan result (series table, no patient information), the rules' classification, the user's overrides, the conversion records (command, tool version, file hashes) and what was written to `rawbids/`. It is the provenance of an import and can change; `rawbids/` itself never does.
- **Rules** (`classification_rules.yaml`): plain-text clues grouped in families (name, image type, geometry, relation to other series); confidence counts how many families agree. Unknown or conflicting series are never imported until the user decides.
- **Immutability of rawbids/**: files are read-only; nothing is overwritten or renamed; all checks run before the first file is written. Only exception: a fieldmap sidecar may gain `IntendedFor` entries when a run is added later.
- **Privacy**: only acquisition tags are read from DICOM; source folder and file names are never stored; JSON sidecars lose site, device and study-description fields (`sidecar_privacy.yaml`).
- **External files are copied, never linked**; files inside the workspace (converted to rawbids) are hard-linked, so there is no second copy on disk.


## 14. Reports, history and system checks (Stage 8)
- **Report** (`backend/mrforge/report.py`): `build_report(ws, subject)` returns a `SubjectReport` from the latest completed run of every step instance (one per results folder) whose registered outputs still exist, the import manifests (acquisition: only series that went into `rawbids/`) and the quality-decision history. Sections: structural, functional, artifact rejection, standard space, other. API: `GET /subjects/{label}/report`, `POST .../report/export` (writes `reports/<subject>/<subject>_report_<time>.html`), `GET /reports`. CLI: `mrforge report <subject> [--json | --html]`.
- **QC slices:** a `QCItem` may carry `slices` (plane, position, layer, path relative to the step output folder) next to the joined picture.
- **Step record** (`history.py`): `GET /jobs/{id}/record` (settings, files with hashes, commands as shell-quoted strings, tool versions; only provenance of that very job is used). `POST /jobs/{id}/rerun {force}` starts operation kind `rerun`.
- **System** (`system_check.py`): `GET /api/system`, `mrforge doctor`, `scripts/check_env.py`.

## 15. Optional T1 resampling before fsl_anat
- **Step `resample_t1`** (`steps/resample_t1.py`): `flirt -in T1 -ref T1 -applyisoxfm 1 -interp spline`, result `sub-XXX_desc-1mm_T1w.nii.gz` in `derivatives/.../anat/`; the raw T1 is never changed. It validates that the output voxels are exactly the target size and reports the original and new matrix and a warning if spline overshoot created negative values.
- **When it runs:** only when the option `resample_to_1mm` is on (off by default) and a spatial voxel side is finer than 1 mm (`needs_resampling`). Otherwise the step is not planned and the plan shows why. The anatomical stage (`processing.py`) then gives `fsl_anat` the input `${resample_t1.result}`; its native folder is named after that input (`sub-XXX_desc-1mm_T1w.anat`). All BIDS-named fsl_anat results keep their names, so the functional stages and result lookups are unchanged.
- **Where to choose it:** the full-processing dialog (anatomical options), the Anatomical page (advanced options), `POST /anat` field `resample_to_1mm`.

## 16. Diffusion and the ALPS index (Stage 9)
Port of the lab's `alps.sh` (G. Barisano, MIT). Each part is a separate `Step` (`datatype = "dwi"`, results in `derivatives/mrforge/sub-XXX/[ses-YY/]dwi/`, records in `_runs/<label>/`):
`dwi_denoise` (`dwidenoise`) and `dwi_unring` (`mrdegibbs`), both MRtrix3 and optional; `dwi_topup` (acquisition parameters from the sidecars, `topup`, b0 mean and brain mask); `dwi_eddy` (`eddy_cpu`/`eddy`/`eddy_cuda`/`eddy_correct`; `--nthr` from the step parameter or the Settings resource policy, which is not part of the resume hash); `dwi_dtifit` (`dtifit --save_tensor`); `dwi_qc` (FA picture, eddy motion metrics and plot; reported only); `dwi_to_template` (native, linear, fnirt, linear+fnirt, or T1/T2-guided; the tensor moved with flirt or `vecreg`); `alps_rois` (packaged ROIs in `backend/mrforge/data/alps_rois/`, the legacy 5 mm set, a sphere of any radius, or four custom files); `alps_index` (ALPS left/right/mean, FA and MD per region; writes `alps.json` and the script's two CSV files).
- **Stage** (`DiffusionStage` in `processing.py`, last in `STAGES`, off by default, no dependency on the anatomical or functional stages): one chain per diffusion series found by `diffusion.py` (`.bval`/`.bvec`/sidecar present; the opposite phase-encoding image is an `epi` field map, preferring one whose `IntendedFor` lists the series, or a second diffusion series). Without an opposite image TOPUP is left out and `alps.json` carries the note "no distortion correction". Without MRtrix3 the two MRtrix steps are left out and the skip is a recorded note. Options: `DiffusionOptions` (in `FullOptions`, `BatchOptions`, presets).
- **Results** (`alps_results.py`): the table is built only from the recorded `alps.json` files (plus the `dwi_qc` motion metric and the researcher's QC decision). `GET /alps-results`, `POST /alps-results/export` (`leave_out_excluded`), `GET /alps-results/exports`. The export writes `reports/alps/alps_results_<time>.csv` and `.xlsx`. Flags warn, never exclude.
- **Optional dependency:** MRtrix3 (`mrtrix_env.py`: `MRFORGE_MRTRIX`, then PATH); shown in Settings, System and `mrforge doctor` as optional.
- **REVIEW(domain):** see the list at the end of the Stage 9 entry in `PROGRESS.md`.
- **Region sets side by side:** `alps_rois` and `alps_index` carry a tag of the chosen set in their step label (`alps_rois_legacy5`, `alps_index_sphere3p5`; the packaged 2.5 mm set has no tag and keeps the old names). That gives each set its own result files (`desc-alpslegacy5`), run record and resume state, while everything before the regions (denoise to registration) is shared and not repeated. The results table and export have one row per series and region set.

