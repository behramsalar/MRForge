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
