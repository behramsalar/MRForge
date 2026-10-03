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

Step-specific codes (for example for `bet` and `fsl_anat`) are added as those steps are written.
