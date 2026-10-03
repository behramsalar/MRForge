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
    derivatives/mrforge/
        sub-XXX/ses-YY/<step-name>/
            <outputs>
            provenance.json
            logs/stdout.log, logs/stderr.log
    reports/
```

Rules: `sourcedata/` and `rawbids/` are never modified after creation. All results go under `derivatives/`. A workspace with one scan is simply `sub-001`.

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
- Max concurrency is configurable. Jobs wait rather than oversubscribe (richer scheduling in Stage 6).

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
