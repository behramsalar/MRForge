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
  "subject": "sub-001", "session": null,
  "parameters": {"frac": 0.5},
  "parameter_hash": "sha256:...",
  "inputs": [{"path": "rawbids/sub-001/anat/sub-001_T1w.nii.gz", "sha256": "..."}],
  "outputs": [{"path": "derivatives/mrforge/sub-001/bet/brain.nii.gz", "sha256": "..."}],
  "commands": [{"argv": ["bet", "..."], "return_code": 0}],
  "tool_versions": {"fsl": "6.0.7.23", "mrforge": "0.0.0"},
  "started": "2026-10-03T10:00:00Z", "finished": "2026-10-03T10:00:12Z",
  "status": "Completed",
  "stdout_log": "logs/stdout.log", "stderr_log": "logs/stderr.log"
}
```

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
    code: str                 # e.g. "BET_INPUT_UNREADABLE"
    message: str              # plain language: what happened
    probable_cause: str       # why it likely happened
    suggested_action: str     # what to do next
    log_path: Path | None     # raw log stays one click away
```

All codes are catalogued in `docs/errors.md`. Raw tool output is never the only thing shown.

## 9. Other principles that shape the design

- QC flags, never decides. Accept/Review/Exclude is a recorded `UserDecision` with a required reason.
- Reports and methods text are generated deterministically from provenance.
- Never invent FSL flags; verify against `--help`/docs. Uncertain scientific choices carry `# REVIEW(domain)`.

## 10. Environment notes (this machine)

macOS arm64, FSL 6.0.7.23 at `~/fsl`, project Python venv `~/progders`. Non-login shells do not load `FSLDIR` (set in `~/.zprofile`). **[PROPOSAL]** The job runner builds the subprocess environment explicitly from a configured `FSLDIR` (sourcing `fsl.sh` semantics: `FSLDIR`, `PATH`, `FSLOUTPUTTYPE=NIFTI_GZ`) rather than inheriting whatever shell started the server.

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

1. **Source of truth**: provenance files durable, SQLite rebuildable (as drafted), or the reverse?
2. **Hashing**: SHA-256 of every input on each resume check is slow for large 4D files. OK to cache hashes keyed by (path, size, mtime) and rehash only when those change?
3. **Liveness check**: OK with PID + start time for detecting interrupted jobs (section 5)?
4. **FSL environment**: OK for the runner to construct the FSL environment from a configured `FSLDIR` instead of inheriting the shell (section 10)? Preferred output type `NIFTI_GZ`?
5. **Path style**: workspace-relative paths in provenance (as drafted) so workspaces are movable?
6. **Multi-session**: is `ses-*` needed from the start, or may sessions be optional and omitted from paths when absent (as drafted)?
7. **Step granularity of `fsl_anat`**: wrap as one step (per CLAUDE.md 1h) even though it is internally many stages. Resume inside it is then all-or-nothing. Acceptable?
8. **Scanner/fieldmap types** your lab uses (needed before Stage 5c) and who the lab members for UX feedback are (CLAUDE.md section 0 still blank).
