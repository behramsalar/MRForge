# MRForge: what the app is and how it works (brief for UI brainstorming)

## In one paragraph
MRForge is a local web app that lets MRI researchers run brain-imaging analysis without using the command line. It wraps tools that are already installed on the lab computer (mainly FSL, plus dcm2niix, the BIDS validator, ICA-AROMA and MRtrix3) in a guided, reliable workflow. The people who use it are lab members, many of them less experienced than the person who built it, and they cannot debug a failed FSL run themselves. So the interface is the product, but the engine under it has to be dependable: it records everything, resumes instead of redoing work, and explains failures in plain language. It runs on one machine (a Mac now, a Linux host later); the browser talks to a local server (`mrforge serve`, http://127.0.0.1:8000). There are no passwords; a researcher just picks a name.

## Who uses it, and what they want
- **Researchers and students** who have scanner data (DICOM folders, or already-converted NIfTI/BIDS datasets) and want clean, analysis-ready data and results (connectivity matrices, a diffusion index) with confidence about what was done.
- Typical anxieties: "Did it work?", "Which of my 40 subjects need attention?", "Is this scan usable?", "What exactly was done to the data?" (they must be able to write a methods section).
- A lab head or collaborator sometimes reads reports and exports, but does not drive the app.

## Core ideas (these shape every screen)
- **Workspace**: a container for one study's data and results. The same app works for one scan, one subject or a hundred. There is no separate "group mode"; dataset-level controls appear automatically when there is more than one subject.
- **Subject** (sub-001...), optionally with **sessions**, each having **recordings** (anatomical T1, resting functional, field maps, diffusion).
- **Raw data is never modified.** Everything the app produces goes into a separate derivatives area.
- **Everything is a step with recorded provenance**: command, settings, input files (with checksums), software versions, outputs, logs, start/finish times. Nothing is a black box.
- **Resume, don't redo**: a completed step with the same settings and inputs is never rerun; a failed pipeline continues from the failed step; changing a setting reruns that step and invalidates what depends on it.
- **Flag, don't decide**: quality checks can warn (high motion, odd signal, low region coverage) but only the researcher accepts, reviews or excludes a subject, and must give a reason that is stored.
- **Plain-language errors**: every failure shows what happened, the probable cause, and what to do next; the raw log is one click away.
- **Safe defaults, advanced options hidden**: only actions whose inputs exist are offered. Scientific defaults are proposals the researcher confirms.
- **Reports and methods text are generated from recorded facts**, never written freehand by an AI.

## The workflow (how a person moves through it)
1. **Create or open a workspace.**
2. **Import**: point at a DICOM folder/ZIP, existing NIfTI files, or an existing BIDS dataset. The app scans the series, classifies each one (T1, BOLD, field map, diffusion...) with a confidence level (High / Medium / Low), shows a table the user can correct, converts with dcm2niix, organises into BIDS, and runs the BIDS validator with warnings translated into plain language. Unknown or low-confidence series are never silently assigned. Importing the same data twice does not duplicate anything; a whole import can be undone.
3. **Process** (the main action). The default is "full processing": choose subjects, press Process, review a confirmation dialog with the stages to include and their settings, and start. Stages in order:
   - **Anatomical**: brain extraction, tissue segmentation, registration (FSL fsl_anat).
   - **Functional preprocessing**: delete initial volumes, motion correction, field-map distortion correction, smoothing, high-pass filter, registration to the T1 (FSL FEAT driven by a design file the app writes).
   - **Artifact rejection (optional)**: ICA (MELODIC) splits the data into components. A researcher labels each as signal / noise / uncertain (or ICA-AROMA proposes labels, in "AROMA proposes, you confirm" or "AROMA decides" modes), then the noise is regressed out. The pipeline can pause in a **"Waiting for you"** state until the labelling is saved, without using the computer.
   - **Standard space**: results resampled once into the MNI template space.
   - **Connectivity (optional)**: mean time series for each region of bundled atlases (Schaefer 100 with 7 or 17 networks, Schaefer + Tian subcortical, AAL3), then region-to-region correlation matrices (Pearson, Fisher z), saved as plain number files ready for group-statistics tools.
   - **Diffusion (optional)**: ALPS index (diffusion along perivascular spaces) from diffusion data, via denoising, TOPUP, eddy-current correction, tensor fitting, registration to a template and region sampling.
   - Presets bundle a whole set of stage settings under a name. Individual stages can also be run alone ("single steps").
4. **Watch progress**: jobs run in the background; status updates live, survives page refresh, shows interrupted jobs after a crash or restart with Retry step / Resume pipeline buttons.
5. **Check quality**: each step produces QC pictures and numbers (motion plot and framewise displacement, registration mosaics with an "open interactively" button, field-map before/after, a whole-brain signal plot that flags sudden brightness changes, ICA component summaries, atlas overlay for connectivity, coverage per region). The researcher records a decision per subject (Accept / Review / Exclude, with a required reason).
6. **Look at results**: a per-subject page (stage-by-stage status, QC summary, buttons: Results, Open in viewer, Process again), a results page built from recorded provenance (pictures, metrics, files per stage), an HTML report per subject, a connectivity matrix heatmap (fixed colour scale, region names on hover, hatched low-coverage regions, network boundaries, distribution of values), results tables with CSV/Excel export for the ALPS index and connectivity file index.
7. **Inspect and trust**: command history / provenance viewer with Copy command and Re-run; a System page listing which tools are installed and their versions.

## Current interface structure (as built)
- **Look**: dark charcoal sidebar with an amber ("forge") accent; light, dark or follow-the-computer theme; built with Radix Themes; all colours/spacing in one tokens file; status colours chosen by meaning (the same word always the same colour); empty states invite an action; advanced options collapsed.
- **App shell**: sidebar of functions (a tree for groups such as Process), a top bar with an activity indicator/bell and the theme switch, researcher profile chooser (a name, no password; tags who started what and lets people resume their own work).
- **Pages**: Dashboard (counts of processed / failed / needs review / excluded, a table of subjects; a row opens that subject's page); Data (import, subjects, files); Viewer (global MRI viewer, NiiVue, with overlays such as brain mask, segmentation, atlas); Process (Pipelines with full processing; single steps: Anatomical; Functional with Preprocessing / Artifact rejection / Standard space; Connectivity; Diffusion); Jobs (history, live status, failures); Settings (tool detection, resources, presets); component review screen for ICA labelling; subject page; results/report pages; design reference page.
- **Subjects table**: search, status filters, paging; used wherever subjects are picked; multi-select for batch runs. Must stay usable with 20 to 100+ subjects.
- **Confirmation dialog** for processing: list of stages with switches, per-stage options (collapsed advanced), atlas checklist for connectivity, preset chooser, plan preview showing what will actually run vs what is already done.
- **Resources**: a scheduler limits simultaneous subjects, CPU threads and memory; presets Balanced / Max performance / Low impact; jobs wait instead of overloading the machine.

## Constraints a designer should know
- Heavy, slow work: a single functional run takes tens of minutes, ICA and diffusion eddy correction can take an hour or more. The UI must make long waits, queueing and "paused waiting for you" states clear and calm.
- Data is large (4D images, hundreds of MB); previews are generated as pictures and the viewer streams NIfTI.
- Single user at a time on a shared lab computer; no accounts or permissions, no cloud.
- Scientific correctness and honesty matter more than flash: never hide a warning, never auto-exclude, always show what was run.
- Everything an action does must be reachable as recorded facts afterwards (provenance), so the UI should make "what happened to this subject?" easy to answer.
- Users are not neuroimaging experts: copy must be plain language, jargon explained.

## Known weak spots and open UX questions (good places for ideas)
- First-time experience: how a new lab member understands the whole flow (Import to Process to QC to Results) at a glance.
- Navigating from "100 subjects" down to "this one scan needs attention": triage views, what the dashboard should lead with.
- Showing a pipeline's progress across many subjects and stages at once (a subject by stage grid?).
- Reviewing QC efficiently: seeing many subjects' registration/motion pictures side by side, accept/exclude flow, keyboard shortcuts.
- The ICA component labelling screen (many components, each with spatial map, time course and spectrum): making it fast and less tiring.
- Connectivity matrices: comparing subjects, reordering by network, clicking a cell to see both regions in the brain viewer, difference between two subjects.
- Explaining errors and the "Waiting for you" state so non-experts act correctly.
- Making the provenance / methods information readable without overwhelming people.
- Settings and choices: how to present scientific defaults, presets and their effects without drowning the user in options.
- Linking the viewer to everything (open any result image from anywhere).

## Not in the app (yet)
Group-level statistics, task fMRI analysis, tractography, logins, cloud/multi-machine compute, AI-written text. Planned later: nuisance regression (WM/CSF/motion), motion scrubbing, more atlases and custom regions, richer matrix visualisation, dataset snapshots and user-built pipelines, advanced QC (DVARS, tSNR, carpet plots), group analysis as a separate product area.
