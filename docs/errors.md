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

Step-specific codes (for example for `bet` and `fsl_anat`) are added as those steps are written.
