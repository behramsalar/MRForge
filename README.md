# MRForge

A web application that guides researchers through MRI/fMRI analysis with tools that are already on the computer, mainly [FSL](https://fsl.fmrib.ox.ac.uk/fsl/docs/), plus dcm2niix, the BIDS validator and (optionally) ICA-AROMA. It is made for lab members who are not FSL experts: the interface shows only what can be done next, explains errors in plain language, and records exactly what was run.

> **Status:** version 0.1 (MVP 1). Used so far on macOS (Apple silicon). Linux should work but has not been tested. There is no login: run it only on your own computer or a network you trust. No license has been chosen yet.

## What it does

- **Import** DICOM folders, ZIP/tar archives, NIfTI files and existing BIDS datasets. Series are classified automatically with a confidence level; uncertain ones are never assigned silently. The result is a [BIDS](https://bids.neuroimaging.io/) dataset.
- **Anatomical processing** with `fsl_anat` (optionally resampling a very high-resolution T1 to 1 mm first), plus optional `bet`.
- **Functional preprocessing** with FEAT (motion correction, field-map distortion correction, smoothing, high-pass filtering, registration), with quality-check pictures and motion metrics.
- **Artifact rejection**: MELODIC, a component review screen (signal / noise / uncertain), `fsl_regfilt`, and optional ICA-AROMA.
- **Standard (MNI) space** in a single resampling step.
- **Full processing** of one subject or a batch, with presets, resource limits so the computer stays usable, and resume after a crash or restart.
- **Quality decisions** (accept / review / exclude with a reason) that only the researcher makes; the app flags, it never excludes.
- **Reports** per subject (in the app and as a saved HTML file), a command history with exact commands, and a system page that checks the installed tools.
- A built-in **viewer** (NiiVue) for the images and overlays.

## Principles

Raw data is never modified; everything goes to `derivatives/`. Every run records its command, parameters, input hashes, outputs, tool versions and logs (`provenance.json`). Finished steps are not rerun; a failed pipeline resumes where it stopped. Reports are generated from the recorded facts, never written by a language model. See [`CLAUDE.md`](CLAUDE.md) for the full list and [`docs/architecture.md`](docs/architecture.md) for the design.

## Quick start

Full instructions, including installing FSL and the other tools, are in **[`docs/INSTALL.md`](docs/INSTALL.md)**. In short:

```bash
git clone git@github.com:behramsalar/MRForge.git && cd MRForge
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
(cd frontend && npm install && npm run build)
mrforge doctor        # checks FSL, dcm2niix, the BIDS validator ...
mrforge serve         # then open http://127.0.0.1:8000
```

## Documentation

| File | Contents |
|---|---|
| [`docs/INSTALL.md`](docs/INSTALL.md) | Installation, first run, updating, troubleshooting |
| [`docs/architecture.md`](docs/architecture.md) | Steps, workspace layout, provenance, resume rule, errors |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Dated decisions and their reasons (including scientific defaults to review) |
| [`docs/errors.md`](docs/errors.md) | Error catalog: what each error means and what to do |
| [`docs/design-system.md`](docs/design-system.md) | Interface rules, colours, components |
| [`docs/TEST_DATA.md`](docs/TEST_DATA.md) | What test data the tests use (none is included in this repository) |
| [`PROGRESS.md`](PROGRESS.md) | Current state of the project |

## Development

```bash
pytest -m "not fsl"                  # unit tests, no FSL needed
pytest -m fsl                        # tests that run real FSL (slow; need test data, see docs/TEST_DATA.md)
ruff check . && ruff format .        # lint and format
mypy                                 # types
cd frontend && npm test && npx tsc --noEmit
```

For frontend work run `mrforge serve --port 8000` and, in `frontend/`, `npm run dev` (port 5173). After changing the API, regenerate the typed client with `npm run gen:api` in `frontend/` while the server runs.

## Data and privacy

No imaging data is stored in this repository, and none should ever be committed (`.gitignore` excludes the usual formats and workspaces). Scanner data can contain patient information in DICOM headers: keep workspaces and test data outside the repository.
