# Installing MRForge

MRForge runs on **macOS** (tested on Apple silicon) and **Linux** (expected to work, not yet tested). Windows is not supported directly because FSL needs WSL there.

## 1. Requirements

| Needed | Why | How to get it |
|---|---|---|
| Python 3.11 or newer | the engine and the web server | [python.org](https://www.python.org/downloads/) or your package manager |
| Node.js 20.19 or newer, or 22.12 or newer (with npm) | builds the web interface once; also provides the BIDS validator | [nodejs.org](https://nodejs.org/) |
| **FSL** 6.0.7 or newer | all the image processing | [FSL installation guide](https://fsl.fmrib.ox.ac.uk/fsl/docs/#/install/index) |
| dcm2niix | converts DICOM to NIfTI | macOS: `brew install dcm2niix`; Linux: your package manager or the [releases](https://github.com/rordenlab/dcm2niix/releases) |
| BIDS validator | checks the imported dataset | `npm install -g bids-validator` |
| ICA-AROMA (optional) | automatic proposal of noise components | installed by the script in step 4 |
| git | to download and update MRForge | macOS: `xcode-select --install` |

FSL is found in this order: the path set in MRForge's settings, the `FSLDIR` environment variable, then common places (`~/fsl`, `/usr/local/fsl`, `/opt/fsl`, `/usr/share/fsl`). You do not need to load FSL's setup file before starting MRForge. Allow about 5 GB of disk space for the tools and plenty more for your data (a workspace with processed results is several times the size of the raw scans).

## 2. Download and install MRForge

```bash
git clone git@github.com:behramsalar/MRForge.git
cd MRForge
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`".[dev]"` also installs the test tools; use `pip install -e .` if you only want to run the program.

Build the web interface (needed once, and again after updates that change `frontend/`):

```bash
cd frontend
npm install
npm run build
cd ..
```

## 3. Check the computer

```bash
mrforge doctor
```

This lists FSL (with its version and where it was found), dcm2niix, the BIDS validator, ICA-AROMA (optional), Python, CPU cores, memory and free disk space, each marked as passed, failed or optional, with a hint for every failure. The same checks appear on the **System** page of the web interface. Fix everything marked as failed before you continue.

## 4. Optional: ICA-AROMA

With the virtual environment active:

```bash
bash scripts/install_aroma.sh
```

This downloads the reference implementation into `tools/ICA-AROMA` (a pinned version) and installs the one small Python package it needs. `mrforge doctor` then shows it as available, and the "ICA-AROMA proposes" options appear in the artifact-rejection dialog.

## 5. Start the program

```bash
mrforge serve
```

Open <http://127.0.0.1:8000> in a browser. Workspaces are kept in `~/Documents/mrforge-workspaces` by default. The first time, the app asks you to pick or add your name (a name only, no password; it tags who started what).

Options:

- `--port 8080` to use another port.
- `--workspaces /path/to/folder` to use another folder for the workspaces. The environment variable `MRFORGE_WORKSPACES` does the same, and app settings are kept in `~/.config/mrforge/config.json` (`MRFORGE_CONFIG` points to another config file).
- `--host 0.0.0.0` makes it reachable from other computers. **There is no login**, so do this only on a network you trust.

Stop it with Ctrl+C. Jobs run in separate worker processes: if the server stops or the computer restarts, running jobs show as *Interrupted* and can be resumed.

## 6. First use

1. Create a workspace, then **Data → Import** and choose a folder or archive with DICOM files (or NIfTI / BIDS data).
2. Check the table of detected series and fix any that are wrong or uncertain, then import.
3. On the subject's page choose **Process** to run full processing (or use the single steps under *Process*).

## Updating

```bash
git pull
pip install -e ".[dev]"
(cd frontend && npm install && npm run build)
```

Then restart `mrforge serve`. Results made by older versions stay valid; a step is only rerun when its inputs, settings or version changed.

## Troubleshooting

- **`mrforge: command not found`** — activate the virtual environment first (`source .venv/bin/activate`).
- **Only the API answers, no web page** — the interface has not been built; run `npm run build` in `frontend/`.
- **FSL not found although it is installed** — set its folder on the Settings page, or start with `FSLDIR=/path/to/fsl mrforge serve`.
- **Port already in use** — another MRForge is running; stop it or use `--port`.
- **A job failed** — the Jobs page shows what happened, the likely reason and what to do next; the raw log is one click away. The messages are catalogued in [`errors.md`](errors.md).

## Running the tests

```bash
pytest -m "not fsl"      # about 6 minutes, no FSL needed
pytest -m fsl            # needs FSL and test data outside the repository, see TEST_DATA.md
```
