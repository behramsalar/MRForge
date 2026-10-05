# Error catalog

Every `StepError` code is listed here with: **what happened**, **probable cause**, **suggested action**. Raw logs are always linked from the UI.

Codes are stable identifiers: add new ones, do not rename existing ones.

## Engine-level codes (Stage 1b)

### INPUT_MISSING
- **What happened:** An input file a step needs was not found or is empty.
- **Probable cause:** The file was moved, deleted or never created.
- **Suggested action:** Check the file exists, or rerun the step that makes it.

### OUTPUT_MISSING
- **What happened:** The tool finished but an expected result file was not produced.
- **Probable cause:** The tool finished without writing this file.
- **Suggested action:** Open the raw log for details, then retry the step.

### COMMAND_FAILED
- **What happened:** An external tool (for example FSL) stopped with a non-zero exit code.
- **Probable cause:** The input data may be unsuitable, or the tool hit a problem.
- **Suggested action:** Open the raw log for details, then fix the input and retry.

### TOOL_NOT_FOUND
- **What happened:** The program needed by a step could not be found.
- **Probable cause:** The software is not installed or is not on the path.
- **Suggested action:** Run `python scripts/check_env.py` to see what is missing.

### UNKNOWN_STEP
- **What happened:** A step name was requested that does not exist.
- **Probable cause:** The name is misspelled or the step does not exist.
- **Suggested action:** Use one of the listed step names.

### UNEXPECTED_ERROR
- **What happened:** A step failed in a way MRForge did not anticipate.
- **Probable cause:** Probably a bug in MRForge, not a problem with your data.
- **Suggested action:** Open the raw log and report the problem together with the message.

## Job-runner codes (Stage 1c)

### COMMAND_KILLED
- **What happened:** An external tool was stopped by a signal before it finished. The job is shown as Interrupted, not Failed.
- **Probable cause:** The process was killed, for example by a user or the system.
- **Suggested action:** Resume the pipeline to run this step again.

### INTERRUPTED
- **What happened:** A job was marked Running but its worker process no longer exists.
- **Probable cause:** The program was killed or the computer restarted.
- **Suggested action:** Resume to run the step again. Leftover tool processes are cleaned up automatically.

### WORKER_CRASHED
- **What happened:** The worker process exited without recording a result.
- **Probable cause:** A bug in MRForge or a broken installation.
- **Suggested action:** Open the worker log (`logs/worker.log` in the step's output folder) and report it.

### CANCELLED
- **What happened:** The user cancelled the job.
- **Suggested action:** None. Run the step again if needed.

### PARAMS_INVALID
- **What happened:** The settings given for a step are missing, misspelled or out of range. The job is not created.
- **Suggested action:** Correct the value and run again.

### UNKNOWN_JOB
- **What happened:** A job number was requested that does not exist.
- **Suggested action:** Run `mrforge status` to see the existing jobs.

### FAKE_FAILURE
- **What happened:** The test-only `fake` step was configured to fail.
- **Suggested action:** Change its `fail_at` parameter. Never occurs with real steps.

## Stage 1e/1g codes

### FSL_NOT_FOUND
- **What happened:** A step needs FSL but MRForge could not find it.
- **Probable cause:** FSL is not installed, or MRForge was not told where it is (the message lists the places that were checked).
- **Suggested action:** Install FSL, or run `mrforge config fsl /path/to/fsl`.

### NOT_AN_FSL_FOLDER
- **What happened:** The folder given to `mrforge config fsl` is not an FSL installation.
- **Suggested action:** Choose the folder FSL was installed into (it contains `etc/fslversion`).

### INPUT_NOT_NIFTI
- **What happened:** An image file could not be read as a NIfTI image.
- **Probable cause:** The file is damaged, incomplete or not a NIfTI (.nii/.nii.gz).
- **Suggested action:** Check the file opens in FSLeyes, or import the scan again.

### PIPELINE_INVALID / PIPELINE_UNREADABLE
- **What happened:** A pipeline file has a mistake (duplicate step id, missing subject, a step using the result of a step listed after it) or could not be read.
- **Suggested action:** Correct the pipeline file and run again.

### BAD_OPTION
- **What happened:** A `--param` or `--input` option was not written as `name=value`.
- **Suggested action:** Write options like `--param frac=0.4`.

### NOTHING_TO_RESUME
- **What happened:** `mrforge resume` was run in a workspace with no earlier pipeline run.
- **Suggested action:** Start one with `mrforge pipeline run <file>`.

Step-specific codes (for example for `bet` and `fsl_anat`) are added as those steps are written.

## Import codes (Stage 2a)

### IMPORT_SOURCE_INVALID
- **What happened:** The path given to `mrforge import scan` is not a folder or a ZIP file.
- **Probable cause:** The path is wrong, or the file is not a ZIP archive.
- **Suggested action:** Give the folder that contains the DICOM files, or a .zip of it.

### IMPORT_ZIP_UNSAFE
- **What happened:** A ZIP file contains a path that points outside its own folder. Nothing was extracted.
- **Probable cause:** The archive is damaged or was built to write elsewhere.
- **Suggested action:** Do not import this file; export the scan again.

### NO_DICOM_FOUND
- **What happened:** The chosen folder or ZIP holds no readable DICOM images. Nothing was copied.
- **Probable cause:** Wrong folder, or the files are not DICOM.
- **Suggested action:** Choose the folder with the scanner's DICOM files (subfolders are searched), or a ZIP of it.

### IMPORT_ALREADY_SCANNED
- **What happened:** The same data was already scanned under another subject or session label.
- **Suggested action:** Use the existing import, or choose a different source.

### BAD_SUBJECT_LABEL / BAD_SESSION_LABEL
- **What happened:** A subject or session label is not valid BIDS (`sub-` or `ses-` followed by letters and digits only).
- **Suggested action:** Use something like `sub-001` or `ses-01`.

### NO_IMPORT / UNKNOWN_IMPORT
- **What happened:** There is nothing imported yet, or the named import does not exist.
- **Suggested action:** Run `mrforge import scan <folder or zip>`, or `mrforge import show` to list imports.

## Classification codes (Stage 2b)

### RULES_INVALID
- **What happened:** The classification rules file could not be used (bad YAML, an invalid pattern, an unknown field or predicate, a duplicate rule id, ...).
- **Probable cause:** A mistake in the rules file; the message names it.
- **Suggested action:** Correct the file (the comments at its top explain the format), or remove it to use the built-in rules.

### UNKNOWN_SERIES / AMBIGUOUS_SERIES
- **What happened:** The series number given to `mrforge import set` does not exist, or is used by more than one series in the import.
- **Suggested action:** Run `mrforge import show` for the numbers; for repeated numbers, import the sessions separately.

### SET_NEEDS_TYPE
- **What happened:** A series that is skipped or unrecognised was set without saying what it is.
- **Suggested action:** Add `--type`, for example `mrforge import set 7 --type bold`.

### UNKNOWN_KIND / BAD_LABEL / SET_CONFLICT
- **What happened:** `mrforge import set` was given a type MRForge cannot import, a label with spaces or dashes, or both `--skip` and a type.
- **Suggested action:** Use one of the listed types, labels of letters and digits only, and either `--skip` or `--type`/`--task`.

## Conversion problems (Stage 2c)

Conversion never stops the whole import for one bad series. Problems are recorded per series (shown by `mrforge import convert` and `mrforge import show`, and stored in the manifest) in plain language:

- **dcm2niix stopped with an error** (exit code N) while converting a series: the last messages are shown, with source paths removed. The full scrubbed log is in `imports/import-NNN/logs/convert-s<number>.log`. *What to do:* fix the cause, then run `mrforge import convert` again; only failed series are converted again.
- **dcm2niix produced no image:** the series may not be a convertible image. *What to do:* check the log, or skip the series with `mrforge import set <series> --skip`.
- **The converted image has size X but the scan says Y / has N volumes but the scan found M / should give the images [...]:** the conversion does not match the scan, so the data may be incomplete or damaged. *What to do:* check the series in the scanner export; do not use it until it matches.
- **The diffusion directions (bval/bvec) are missing, or the number of b-values does not match the volumes:** the series cannot be used for diffusion analysis. *What to do:* re-export the series with its diffusion information.
- **The JSON sidecar is missing:** BIDS needs it. *What to do:* convert again; if it persists, report it.

## Organizing codes (Stage 2d)

### ORGANIZE_NEEDS_CONVERSION
- **What happened:** Some series that are set to be imported are not converted yet, or their conversion failed. Nothing was written to `rawbids/`.
- **Suggested action:** Run `mrforge import convert` and fix any failed series first.

### ORGANIZE_COLLISION
- **What happened:** `rawbids/` already contains different files with the same names.
- **Probable cause:** Another import was already written for this subject and session; raw data is never overwritten. (Or a file in `rawbids/` was edited by hand.)
- **Suggested action:** Import into another subject or session (`mrforge import scan --subject / --session`), or a new workspace.

### ORGANIZE_WOULD_RENAME
- **What happened:** Adding or changing series would change the names of files already in `rawbids/` (for example a second run of the same task needs `run-1` and `run-2`).
- **Suggested action:** Create a new workspace and import again with the final choices.

### FIELDMAP_UNKNOWN / BAD_FIELDMAP / FIELDMAP_NOT_APPLICABLE
- **What happened:** `--fieldmap` named a series that is not a fieldmap to be imported, was not a series number or `none`, or was given for a series that is not a BOLD or diffusion run.
- **Suggested action:** Use the series number of a fieldmap magnitude series, or `none`, on a BOLD or diffusion run. See `mrforge import show`.

### PRIVACY_LIST_INVALID
- **What happened:** The sidecar privacy list could not be used.
- **Suggested action:** Correct the file (it needs a `remove:` list of field names), or remove it to use the built-in list.

## Validation codes (Stage 2e)

BIDS validator problems are shown by `mrforge import validate` in plain language ("what happened / why / what to do"), using the explanations in `backend/mrforge/importing/bids_messages.yaml`. The validator's own number is shown in brackets after each problem. Errors must be fixed; warnings are worth knowing.

### VALIDATOR_NOT_FOUND
- **What happened:** The BIDS validator could not be found.
- **Probable cause:** It is not installed, or MRForge does not know where it is.
- **Suggested action:** Install it with `npm install -g bids-validator`, or run `mrforge config bids-validator /path/to/bids-validator`.

### VALIDATOR_FAILED
- **What happened:** The validator ran but did not give a usable answer.
- **Probable cause:** It crashed, or node is missing.
- **Suggested action:** Run `bids-validator <rawbids folder>` yourself to see why, or reinstall it.

### NOTHING_TO_VALIDATE / NOT_A_VALIDATOR / MESSAGES_INVALID
- **What happened:** There is no `rawbids/` folder yet; the path given to `mrforge config bids-validator` is not a file; or the message file is damaged.
- **Suggested action:** Run `mrforge import run` first; give the path from `which bids-validator`; restore `bids_messages.yaml`.

## Importing existing data (Stage 2f)

### INPUT_NOT_NIFTI / INPUT_JSON_INVALID
- **What happened:** A file given to `mrforge import nifti` does not exist, does not end in `.nii`/`.nii.gz`, is damaged, or its `.json` sidecar is not valid JSON.
- **Suggested action:** Check the file opens in FSLeyes; fix or remove the sidecar.

### NIFTI_WRONG_SHAPE
- **What happened:** The image does not fit the `--type` given (for example a T1w with several volumes, or a bold run with one).
- **Suggested action:** Check the file and the type you gave.

### NIFTI_TYPE_UNSUPPORTED / TASK_NEEDED / TR_NEEDED
- **What happened:** The type cannot be imported from NIfTI files (fieldmaps), or a bold image has no task name or repetition time.
- **Suggested action:** Use T1w, T2w, bold or dwi; add `--task <name>` and `--tr <seconds>`.

### DWI_NEEDS_DIRECTIONS / DWI_DIRECTIONS_MISMATCH
- **What happened:** A diffusion image has no `.bval`/`.bvec` next to it, or they do not match its number of volumes.
- **Suggested action:** Put the b-value and b-vector files exported with the image next to it, with the same name.

### IMPORT_NOT_BIDS / IMPORT_BIDS_IS_DERIVATIVE / IMPORT_BIDS_SELF / IMPORT_BIDS_INVALID
- **What happened:** The folder given to `mrforge import bids` has no `dataset_description.json`, is a derivatives dataset, is this workspace's own `rawbids/`, or has BIDS errors.
- **Suggested action:** Choose the top folder of a raw BIDS dataset; for BIDS errors fix them in the source or use `--allow-errors`.

### NO_FILES
- **What happened:** No NIfTI files were given to `mrforge import nifti`.
- **Suggested action:** Give one or more `.nii`/`.nii.gz` files.

## Removing the DICOM copy

### DICOM_REMOVE_NOT_SAFE
- **What happened:** `mrforge import remove-dicom` was refused because some series that are set to be imported are not safely in `rawbids/` yet (not converted, not organised, or a file is missing or changed). Nothing was deleted.
- **Suggested action:** Run `mrforge import run` first, then try again.

### DICOM_ALREADY_REMOVED / DICOM_NOT_APPLICABLE
- **What happened:** The DICOM copy of this import was already removed, or the import did not come from DICOM files (NIfTI and BIDS imports have no copy).
- **Suggested action:** Nothing to do.

### DICOM_REMOVED
- **What happened:** Some series still need converting, but the workspace's DICOM copy was removed.
- **Suggested action:** Scan the original source again with the same subject (`mrforge import scan <original> --subject sub-001`); the copy is restored.

## API and operation codes (Stage 3a)

Errors from the API arrive as JSON with `code`, `message`, `probable_cause`, `suggested_action`.

### UNKNOWN_WORKSPACE / UNKNOWN_OPERATION / UNKNOWN_FILE / UNKNOWN_SUBJECT
- **What happened:** The page asked for something that does not exist (HTTP 404).
- **Suggested action:** Go back to the list and pick again; reload the page.

### OPERATION_BUSY
- **What happened:** An import or pipeline is already running in this workspace (HTTP 409).
- **Probable cause:** These actions change the same data, so they run one at a time.
- **Suggested action:** Wait for it to finish or cancel it.

### JOBS_RUNNING
- **What happened:** A processing step is still running, so a pipeline cannot be started or resumed yet (HTTP 409).
- **Suggested action:** Wait for it to finish or cancel it.

### OUTSIDE_HOME / NOT_ALLOWED / SOURCE_NOT_FOUND
- **What happened:** The folder browser only opens locations inside your home folder, or the chosen source no longer exists.
- **Suggested action:** Copy the scanner files into your home folder, or pick the source again.

### CONVERSION_FAILED
- **What happened:** One or more series could not be converted to NIfTI; nothing was written to `rawbids/`.
- **Suggested action:** Leave those series out (skip) and import again; converted series are kept.

### PIPELINE_STEP_FAILED
- **What happened:** A step of the pipeline did not finish. The step's own error holds the details.
- **Suggested action:** Fix the cause, then resume; finished steps are not repeated.

## Functional preprocessing codes (Stage 5)

### FIELDMAP_TE_MISSING
- **What happened:** The echo time difference of the fieldmap is not known.
- **Probable cause:** The phase-difference image has no EchoTime1/EchoTime2 in its sidecar.
- **Suggested action:** Enter the echo time difference in milliseconds (often 2.46 on Siemens).

### FEAT_INPUTS_INCOMPLETE / FEAT_FIELDMAP_NEEDS_T1
- **What happened:** Only some of the structural (T1) or fieldmap images were given, or distortion correction was requested without the T1 result.
- **Suggested action:** Provide all of them (or none); run anatomical processing first.

### UNWARP_INFO_MISSING
- **What happened:** Distortion correction needs facts the scan does not record (phase-encoding direction, effective echo spacing or echo time).
- **Probable cause:** The scanner headers do not contain them (typical for some vendors).
- **Suggested action:** Run without distortion correction, or supply the values from your scan protocol.

### BOLD_TOO_SHORT / VOLUME_COUNT_MISMATCH
- **What happened:** Too few volumes remain after discarding the first ones, or the result has an unexpected number of volumes.
- **Suggested action:** Check the scan or reduce the number of discarded volumes; run the step again.

### FEAT_PATH_HAS_SPACES
- **What happened:** FEAT cannot work in a folder whose path contains spaces.
- **Suggested action:** Create the workspace in a folder without spaces in its path.

### FEAT_FIELDMAP_NOT_BRAIN_EXTRACTED / FEAT_BAD_INPUT / FEAT_FILE_MISSING / FEAT_FAILED
- **What happened:** FEAT stopped before it finished. The first three are recognised causes (the fieldmap magnitude still contains the skull; FEAT could not use an input image; a file FEAT needs is missing); FEAT_FAILED is anything else, with the last line of FEAT's own log quoted.
- **Suggested action:** Follow the message; the raw log is one click away.


### BOLD_NOT_4D / MNI_TEMPLATE_MISSING / MNI_RESULT_UNEXPECTED
- **What happened:** The standard-space step was given something that is not a time series, FSL's MNI template was not found, or the result had an unexpected size.
- **Suggested action:** Choose the preprocessed (or cleaned) functional run; check the FSL installation; open the raw log and run the step again.

## Undoing an import (after Stage 5)

### NOTHING_TO_UNDO
- **What happened:** The import has not written anything into the data folder (never imported, or already undone).
- **Suggested action:** Nothing to do; change the decisions and import it.

### UNDO_FILES_CHANGED
- **What happened:** Some imported files were changed after the import, so nothing was removed.
- **Probable cause:** MRForge never edits raw files; they were changed outside it.
- **Suggested action:** Restore the original files, or ask whoever looks after MRForge for help.


## Artifact rejection (Stage 6)

### BOLD_TOO_SHORT_FOR_ICA
- **What happened:** The functional run has too few volumes (fewer than 30) for a component analysis.
- **Probable cause:** A very short run, or the image is not a time series.
- **Suggested action:** Skip artifact rejection for this run, or check the scan.

### MELODIC_FAILED
- **What happened:** MELODIC did not produce any components.
- **Probable cause:** The data could not be decomposed, or MELODIC was given an option it did not accept (MELODIC reports some mistakes in its text but still exits normally).
- **Suggested action:** Open the raw log for MELODIC's message, fix the input, retry.

### ICA_RESULT_INCOMPLETE
- **What happened:** MELODIC finished but the result is incomplete (no components, or component pictures missing).
- **Suggested action:** Open the raw log, then run the step again.

### ICA_LABELS_NEEDED (not a failure: the pipeline waits)
- **What happened:** The pipeline reached the point where you label the ICA components and stopped. Nothing runs while it waits.
- **Suggested action:** Open Process, then Artifact rejection, label the components and save. The pipeline then continues from there.

### ICA_RESULT_OUTDATED
- **What happened:** The components were made by an older version of MRForge and cannot be labelled safely.
- **Suggested action:** Run the component analysis (MELODIC) again for this recording.

### INVALID_LABELS / LABELS_INCOMPLETE
- **What happened:** A label is not signal, noise or uncertain, or some components have no label when saving the final decision.
- **Suggested action:** Reload the page and label the remaining components (uncertain is allowed).

### MIXING_MISMATCH / LABELS_MISMATCH / CLEANED_SHAPE_MISMATCH
- **What happened:** The component time courses do not fit the functional image (different number of volumes), the labels name components that do not exist, or the cleaned image has an unexpected shape.
- **Probable cause:** The components or labels belong to another run of the component analysis.
- **Suggested action:** Run the component analysis (MELODIC) again for this image and label the components again.
