"""The `mrforge` command line. It only calls the engine; it never builds tool commands."""

import functools
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, TypeVar, get_origin

import typer
from pydantic import BaseModel

from mrforge.config import load_config, save_config
from mrforge.engine import Action, StepOutcome, latest_pipeline_run, run_pipeline, run_step
from mrforge.errors import StepError
from mrforge.fsl_env import find_fsl, looks_like_fsl
from mrforge.importing.bids_validate import (
    find_validator,
    format_report,
    validate_dataset,
)
from mrforge.importing.classify import (
    apply_rules,
    effective_all,
    load_rules,
    set_override,
)
from mrforge.importing.convert import convert_import
from mrforge.importing.existing import format_bids_import, import_bids, import_nifti
from mrforge.importing.manifest import load_manifest, save_manifest
from mrforge.importing.models import ImportManifest
from mrforge.importing.organize import OrganizeSummary, build_plan, organize
from mrforge.importing.report import describe_plan, format_manifest
from mrforge.importing.scan import scan_source
from mrforge.models import JobStatus
from mrforge.pipeline import PipelineSpec, load_pipeline, parse_pipeline
from mrforge.runner.jobs import get_job, list_jobs, recover_stale_jobs
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401  (registers built-in steps)
from mrforge.steps.registry import get_step, list_steps
from mrforge.workspace import Workspace, WorkspaceError

app = typer.Typer(help="MRForge: guided MRI analysis on top of FSL.", no_args_is_help=True)
workspace_app = typer.Typer(help="Create and manage workspaces.", no_args_is_help=True)
pipeline_app = typer.Typer(help="Run pipelines of several steps.", no_args_is_help=True)
app.add_typer(workspace_app, name="workspace")
config_app = typer.Typer(help="App settings.", no_args_is_help=True)
app.add_typer(pipeline_app, name="pipeline")
import_app = typer.Typer(help="Bring scans into a workspace.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(import_app, name="import")

WorkspaceOption = Annotated[
    Path,
    typer.Option(
        "--workspace",
        "-w",
        envvar="MRFORGE_WORKSPACE",
        help="Workspace folder (default: the current folder).",
    ),
]

F = TypeVar("F", bound=Callable[..., Any])


def friendly(fn: F) -> F:
    """Show StepError/WorkspaceError as plain-language messages instead of tracebacks."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except StepError as err:
            typer.echo(err.format(), err=True)
            raise typer.Exit(1) from None
        except WorkspaceError as err:
            typer.echo(str(err), err=True)
            raise typer.Exit(1) from None

    return wrapper  # type: ignore[return-value]


def parse_pairs(items: list[str], spec: type[BaseModel]) -> dict[str, Any]:
    """key=value options. Values are read as JSON when possible (0.5, true), else as text.
    Repeating a key builds a list; a single value for a list field is wrapped in a list."""
    out: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise StepError(
                code="BAD_OPTION",
                message=f"'{item}' is not in the form name=value.",
                suggested_action="Write options like --param frac=0.4",
            )
        key, raw = item.split("=", 1)
        try:
            value: Any = json.loads(raw)
        except ValueError:
            value = raw
        if key in out:
            prev = out[key]
            out[key] = [*prev, value] if isinstance(prev, list) else [prev, value]
        else:
            out[key] = value
    for key, value in out.items():
        field = spec.model_fields.get(key)
        if field and get_origin(field.annotation) is list and not isinstance(value, list):
            out[key] = [value]
    return out


def describe(outcome: StepOutcome) -> str:
    line = f"{outcome.step_id}: {outcome.action.value}"
    if outcome.action == Action.FAILED:
        return f"{line}\n{_indent(outcome.reason)}"
    if outcome.action == Action.REUSED:
        return f"{line} ({outcome.reason})"
    return f"{line}. {outcome.reason}" if outcome.reason else line


def _local_time(moment: datetime) -> str:
    """Times are stored in UTC; SQLite returns them without a timezone, so add it back."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _indent(text: str) -> str:
    return "\n".join("    " + ln for ln in text.splitlines())


def _queue(ws: Workspace) -> LocalJobQueue:
    return LocalJobQueue(ws)


def _guard_interrupt(queue: LocalJobQueue, fn: Callable[[], Any]) -> Any:
    """Ctrl-C cancels the running jobs (their tools are stopped too) instead of orphaning them."""
    try:
        return fn()
    except KeyboardInterrupt:
        typer.echo("\nStopping... cancelling running jobs.", err=True)
        queue.cancel_all()
        queue.wait(timeout=15)
        raise typer.Exit(130) from None


@workspace_app.command("create")
@friendly
def workspace_create(
    path: Annotated[Path, typer.Argument(help="Folder to create the workspace in.")],
    name: Annotated[str | None, typer.Option(help="Display name (default: folder name).")] = None,
) -> None:
    ws = Workspace.create(path, name)
    typer.echo(f"Created workspace '{ws.name}' in {ws.root}")


@config_app.command("fsl")
@friendly
def config_fsl(
    path: Annotated[
        Path | None, typer.Argument(help="FSL folder to remember (omit to show what is used).")
    ] = None,
) -> None:
    """Show or set where FSL is installed."""
    if path is not None:
        path = path.expanduser().resolve()
        if not looks_like_fsl(path):
            raise StepError(
                code="NOT_AN_FSL_FOLDER",
                message=f"{path} does not look like an FSL installation.",
                probable_cause="The folder should contain 'etc/fslversion' and the FSL tools.",
                suggested_action="Choose the folder FSL was installed into (often ~/fsl).",
            )
        save_config({**load_config(), "fsldir": str(path)})
        typer.echo(f"MRForge will use FSL in {path}")
        return
    fsl = find_fsl()
    typer.echo(f"FSL {fsl.version} in {fsl.fsldir} (found via {fsl.source})")


@import_app.command("scan")
@friendly
def import_scan(
    source: Annotated[Path, typer.Argument(help="Folder or .zip file with the DICOM files.")],
    workspace: WorkspaceOption = Path("."),
    subject: Annotated[
        str | None, typer.Option("--subject", "-s", help="Subject label (default: next free).")
    ] = None,
    session: Annotated[str | None, typer.Option(help="Session label, e.g. ses-01.")] = None,
) -> None:
    """Copy a DICOM session into the workspace and list the series found in it."""
    ws = Workspace.open(workspace)
    manifest, is_new = scan_source(ws, source, subject, session)
    typer.echo(format_manifest(manifest, effective_all(manifest, load_rules(ws))))
    if not is_new:
        typer.echo(f"\nThis source was already scanned ({manifest.id}); nothing was copied again.")


@import_app.command("show")
@friendly
def import_show(
    import_id: Annotated[
        str | None, typer.Argument(help="e.g. import-001 (default: latest).")
    ] = None,
    workspace: WorkspaceOption = Path("."),
    why: Annotated[bool, typer.Option("--why", help="Explain every decision.")] = False,
) -> None:
    """Show the series table of an import, with what will happen to each series."""
    ws = Workspace.open(workspace)
    manifest = load_manifest(ws, import_id)
    typer.echo(format_manifest(manifest, effective_all(manifest, load_rules(ws)), why))


@import_app.command("set")
@friendly
def import_set(
    series: Annotated[int, typer.Argument(help="Series number (see 'mrforge import show').")],
    workspace: WorkspaceOption = Path("."),
    import_id: Annotated[str | None, typer.Option("--import", help="e.g. import-001.")] = None,
    kind: Annotated[
        str | None, typer.Option("--type", help="What it is: T1w, T2w, bold, dwi, fieldmap-...")
    ] = None,
    task: Annotated[str | None, typer.Option(help="Task name, e.g. rest.")] = None,
    acq: Annotated[str | None, typer.Option(help="Acquisition label, e.g. highres.")] = None,
    skip: Annotated[bool, typer.Option("--skip", help="Do not import this series.")] = False,
    fieldmap: Annotated[
        str | None,
        typer.Option(help="Fieldmap for a BOLD/diffusion run: a series number, or none."),
    ] = None,
) -> None:
    """Tell MRForge what a series is (your decision overrides the rules)."""
    ws = Workspace.open(workspace)
    manifest = load_manifest(ws, import_id)
    rules = load_rules(ws)
    labels = {k: v for k, v in (("task", task), ("acq", acq)) if v is not None}
    now = set_override(manifest, rules, series, kind, skip, labels, fieldmap)
    save_manifest(ws, manifest)
    typer.echo(f"Series {series}: {describe_plan(now)} ({now.confidence}, {now.source}).")
    if fieldmap is not None:
        typer.echo(f"Series {series} will use fieldmap: {fieldmap}.")


@import_app.command("convert")
@friendly
def import_convert(
    import_id: Annotated[
        str | None, typer.Argument(help="e.g. import-001 (default: latest).")
    ] = None,
    workspace: WorkspaceOption = Path("."),
    jobs: Annotated[int, typer.Option("--jobs", "-j", help="Series converted at once.")] = 4,
    force: Annotated[bool, typer.Option(help="Convert again even if already done.")] = False,
) -> None:
    """Convert the series that are set to be imported (DICOM to NIfTI with dcm2niix).
    Series already converted are skipped; one failing series does not stop the others."""
    ws = Workspace.open(workspace)
    manifest = load_manifest(ws, import_id)
    summary = convert_import(ws, manifest, load_rules(ws), jobs, force, typer.echo)
    typer.echo(
        f"\n{len(summary.converted)} converted, {len(summary.up_to_date)} already done, "
        f"{len(summary.failed)} failed."
    )
    if summary.failed:
        typer.echo(
            "Failed series: "
            + ", ".join(map(str, summary.failed))
            + "\nFix the cause (see 'mrforge import show --why'), then run this command again; "
            "only the failed series are converted again."
        )
        raise typer.Exit(1)


def _print_organized(
    ws: Workspace, manifest: ImportManifest, summary: OrganizeSummary, uses: dict[str, list[str]]
) -> None:
    for uid, done in manifest.organized.items():
        series = next((s for s in manifest.series if s.uid == uid), None)
        images = sorted(p for p in done.files if p.endswith(".nii.gz"))
        for path in images:
            label = f"series {series.number} ({series.description})" if series else uid
            typer.echo(f"  {label} -> {path}")
    for label, runs in uses.items():
        pair = label.replace("/", " + ")
        typer.echo(f"  fieldmap series {pair} is used by: {', '.join(runs) if runs else 'no run'}")
    typer.echo(
        f"\nrawbids/: {len(summary.written)} file(s) written, "
        f"{len(summary.in_place)} already in place."
    )
    if summary.updated:
        typer.echo(
            f"  {len(summary.updated)} fieldmap sidecar(s) were updated: only their IntendedFor "
            "list changed, because a run was added."
        )
    for note in summary.notes:
        typer.echo(f"  Note: {note}")


@import_app.command("organize")
@friendly
def import_organize(
    import_id: Annotated[
        str | None, typer.Argument(help="e.g. import-001 (default: latest).")
    ] = None,
    workspace: WorkspaceOption = Path("."),
) -> None:
    """Write the converted series into rawbids/ as a BIDS dataset (never overwrites)."""
    ws = Workspace.open(workspace)
    manifest = load_manifest(ws, import_id)
    rules = load_rules(ws)
    uses = build_plan(ws, manifest, rules).uses
    summary = organize(ws, manifest, rules)
    _print_organized(ws, manifest, summary, uses)


@import_app.command("run")
@friendly
def import_run(
    import_id: Annotated[
        str | None, typer.Argument(help="e.g. import-001 (default: latest).")
    ] = None,
    workspace: WorkspaceOption = Path("."),
    jobs: Annotated[int, typer.Option("--jobs", "-j", help="Series converted at once.")] = 4,
) -> None:
    """Convert the series that are set to import, then write them into rawbids/."""
    ws = Workspace.open(workspace)
    manifest = load_manifest(ws, import_id)
    rules = load_rules(ws)
    pending = [
        s for s, c in zip(manifest.series, effective_all(manifest, rules).values(), strict=True)
        if c.action == "ask"
    ]  # fmt: skip
    summary = convert_import(ws, manifest, rules, jobs, False, typer.echo)
    if summary.failed:
        typer.echo(f"\nConversion failed for series {', '.join(map(str, summary.failed))}.")
        typer.echo("Nothing was written to rawbids/. Fix the cause and run this again.")
        raise typer.Exit(1)
    uses = build_plan(ws, manifest, rules).uses
    written = organize(ws, manifest, rules)
    _print_organized(ws, manifest, written, uses)
    typer.echo("")
    try:
        typer.echo(format_report(validate_dataset(ws)))
    except StepError as err:  # the check is a bonus here: its absence must not undo the import
        typer.echo(f"BIDS check skipped: {err.message}\n{err.suggested_action}")
    if pending:
        typer.echo(
            f"\n{len(pending)} series still need your input and were not imported "
            "(see 'mrforge import show')."
        )


def _bids_check(ws: Workspace) -> None:
    """Show the BIDS check of rawbids/; a missing validator is a note, not a failure."""
    typer.echo("")
    try:
        typer.echo(format_report(validate_dataset(ws)))
    except StepError as err:
        typer.echo(f"BIDS check skipped: {err.message}\n{err.suggested_action}")


@import_app.command("nifti")
@friendly
def import_nifti_command(
    files: Annotated[list[Path], typer.Argument(help="One or more .nii / .nii.gz files.")],
    kind: Annotated[str, typer.Option("--type", help="What they are: T1w, T2w, bold or dwi.")],
    workspace: WorkspaceOption = Path("."),
    subject: Annotated[
        str | None, typer.Option("--subject", "-s", help="Subject label (default: next free).")
    ] = None,
    session: Annotated[str | None, typer.Option(help="Session label, e.g. ses-01.")] = None,
    task: Annotated[str | None, typer.Option(help="Task name (required for bold).")] = None,
    acq: Annotated[str | None, typer.Option(help="Acquisition label, e.g. highres.")] = None,
    tr: Annotated[float | None, typer.Option(help="Repetition time in seconds (bold).")] = None,
) -> None:
    """Import NIfTI files that already exist (no conversion). The files are copied, never moved."""
    ws = Workspace.open(workspace)
    rules = load_rules(ws)
    result = import_nifti(ws, files, kind, rules, subject, session, task, acq, tr)
    manifest = result.manifest
    where = manifest.subject + (f"/{manifest.session}" if manifest.session else "")
    typer.echo(f"{manifest.id}: {len(files)} NIfTI file(s) as {kind}, {where}.")
    for index, path in enumerate(files, start=1):  # file names are shown here, never stored
        typer.echo(f"  file {index} ({path.name})")
    if not result.is_new:
        typer.echo("These files were already imported; nothing was copied again.")
    _print_organized(ws, manifest, result.summary, {})
    for note in result.notes:
        typer.echo(f"  Note: {note}")
    _bids_check(ws)


@import_app.command("bids")
@friendly
def import_bids_command(
    source: Annotated[Path, typer.Argument(help="Top folder of an existing BIDS dataset.")],
    workspace: WorkspaceOption = Path("."),
    allow_errors: Annotated[
        bool, typer.Option(help="Import even if the dataset has BIDS errors.")
    ] = False,
) -> None:
    """Import an existing BIDS dataset into rawbids/ (copied, no conversion)."""
    ws = Workspace.open(workspace)
    result = import_bids(ws, source, allow_errors)
    typer.echo(format_bids_import(result))
    if not result.is_new:
        typer.echo("This dataset was already imported; nothing was changed.")
    _bids_check(ws)


@import_app.command("list")
@friendly
def import_list(workspace: WorkspaceOption = Path(".")) -> None:
    """List the imports in this workspace."""
    from mrforge.importing.manifest import list_manifests

    ws = Workspace.open(workspace)
    manifests = list_manifests(ws)
    if not manifests:
        typer.echo("Nothing has been imported yet.")
    for m in manifests:
        what = {"folder": "DICOM folder", "zip": "DICOM zip", "nifti": "NIfTI", "bids": "BIDS"}
        who = m.subject or "(whole dataset)"
        count = f"{len(m.series)} series" if m.series else f"{m.source.n_files} files"
        typer.echo(f"{m.id}  {what[m.source.kind]:<13} {who:<18} {count}")


@import_app.command("validate")
@friendly
def import_validate(
    workspace: WorkspaceOption = Path("."),
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Check rawbids/ against the BIDS standard and explain any problems in plain language."""
    ws = Workspace.open(workspace)
    report = validate_dataset(ws)
    typer.echo(report.model_dump_json(indent=2) if as_json else format_report(report))
    if not report.ok:
        raise typer.Exit(1)


@import_app.command("classify")
@friendly
def import_classify(
    import_id: Annotated[
        str | None, typer.Argument(help="e.g. import-001 (default: latest).")
    ] = None,
    workspace: WorkspaceOption = Path("."),
    rules_file: Annotated[
        Path | None, typer.Option("--rules", help="Use this rules file instead.")
    ] = None,
) -> None:
    """Run the classification rules again (for example after editing them). Your own
    decisions are kept."""
    ws = Workspace.open(workspace)
    manifest = load_manifest(ws, import_id)
    rules = load_rules(ws, rules_file)
    apply_rules(manifest, rules)
    save_manifest(ws, manifest)
    typer.echo(format_manifest(manifest, effective_all(manifest, rules)))


@config_app.command("bids-validator")
@friendly
def config_bids_validator(
    path: Annotated[
        Path | None, typer.Argument(help="The bids-validator program (omit to show what is used).")
    ] = None,
) -> None:
    """Show or set where the BIDS validator is installed."""
    if path is not None:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise StepError(
                code="NOT_A_VALIDATOR",
                message=f"{path} is not a file.",
                suggested_action="Give the path of the bids-validator program "
                "(find it with 'which bids-validator').",
            )
        save_config({**load_config(), "bids_validator": str(path)})
        typer.echo(f"MRForge will use the BIDS validator at {path}")
        return
    typer.echo(f"BIDS validator: {find_validator()}")


@app.command("steps")
def steps_command() -> None:
    """List the available steps."""
    for name in list_steps():
        step = get_step(name)
        typer.echo(f"{name} (version {step.version})")


@app.command("run")
@friendly
def run_command(
    step: Annotated[str, typer.Argument(help="Step name (see 'mrforge steps').")],
    subject: Annotated[str, typer.Option("--subject", "-s", help="Subject label, e.g. sub-001.")],
    workspace: WorkspaceOption = Path("."),
    input_: Annotated[
        list[str] | None,
        typer.Option("--input", "-i", help="Input file as name=path (relative to the workspace)."),
    ] = None,
    param: Annotated[
        list[str] | None, typer.Option("--param", "-p", help="Setting as name=value.")
    ] = None,
    session: Annotated[str | None, typer.Option(help="Session label, e.g. ses-01.")] = None,
    force: Annotated[bool, typer.Option(help="Run again even if already completed.")] = False,
) -> None:
    """Run one step (skipped if it already completed with the same settings and inputs)."""
    ws = Workspace.open(workspace)
    spec = get_step(step)
    inputs = parse_pairs(input_ or [], spec.InputSpec)
    params = parse_pairs(param or [], spec.ParamSpec)
    queue = _queue(ws)
    outcome = _guard_interrupt(
        queue,
        lambda: run_step(
            ws, queue, step, subject, inputs, params, session, force=force, force_reason="--force"
        ),
    )
    typer.echo(describe(outcome))
    if outcome.job_id is not None:
        typer.echo(f"(job {outcome.job_id}; details: mrforge log {outcome.job_id})")
    if outcome.action == Action.FAILED:
        raise typer.Exit(1)


def _run_spec(ws: Workspace, spec: PipelineSpec) -> None:
    queue = _queue(ws)
    outcomes = _guard_interrupt(queue, lambda: run_pipeline(ws, queue, spec))
    for o in outcomes:
        typer.echo(describe(o))
    if any(o.action == Action.FAILED for o in outcomes):
        typer.echo("\nThe pipeline stopped. Fix the problem, then run 'mrforge resume'.")
        raise typer.Exit(1)
    typer.echo("\nPipeline finished.")


@pipeline_app.command("run")
@friendly
def pipeline_run(
    file: Annotated[Path, typer.Argument(help="Pipeline file (YAML).")],
    workspace: WorkspaceOption = Path("."),
) -> None:
    """Run a pipeline file. Steps that are already completed are skipped."""
    ws = Workspace.open(workspace)
    _run_spec(ws, load_pipeline(file))


@app.command("resume")
@friendly
def resume_command(workspace: WorkspaceOption = Path(".")) -> None:
    """Continue the most recent pipeline where it stopped (finished steps are not rerun)."""
    ws = Workspace.open(workspace)
    last = latest_pipeline_run(ws)
    if last is None:
        raise StepError(
            code="NOTHING_TO_RESUME",
            message="There is no pipeline to resume in this workspace.",
            suggested_action="Start one with 'mrforge pipeline run <file>'.",
        )
    typer.echo(f"Resuming pipeline '{last.name}'.")
    _run_spec(ws, parse_pipeline(last.spec))


@app.command("status")
@friendly
def status_command(workspace: WorkspaceOption = Path(".")) -> None:
    """Show all jobs and their state."""
    ws = Workspace.open(workspace)
    for job_id in recover_stale_jobs(ws):
        typer.echo(
            f"Job {job_id} was left running by a process that no longer exists: Interrupted."
        )
    jobs = list_jobs(ws)
    if not jobs:
        typer.echo("No jobs yet.")
        return
    rows = [("JOB", "STEP", "STATUS", "FINISHED", "PROBLEM")]
    for j in jobs:
        finished = _local_time(j.finished) if j.finished else "-"
        rows.append((str(j.id), j.label or j.step_name, j.status, finished, j.error_code or ""))
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    for r in rows:
        typer.echo("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip())
    problems = [j for j in jobs if j.status in (JobStatus.FAILED, JobStatus.INTERRUPTED)]
    if problems:
        typer.echo(
            "\nSomething stopped. 'mrforge log <job>' explains why; 'mrforge resume' continues."
        )


@app.command("log")
@friendly
def log_command(
    job: Annotated[int, typer.Argument(help="Job number (see 'mrforge status').")],
    workspace: WorkspaceOption = Path("."),
    worker: Annotated[bool, typer.Option(help="Show the worker process log instead.")] = False,
) -> None:
    """Show what happened in a job: the error explanation and the raw tool output."""
    ws = Workspace.open(workspace)
    j = get_job(ws, job)
    typer.echo(f"Job {j.id}: {j.label or j.step_name} - {j.status}")
    if j.error_message:
        typer.echo(f"\n{j.error_message}")
    log_dir = ws.abspath(j.run_dir or "") / "logs"
    names = ["worker.log"] if worker else ["stdout.log", "stderr.log"]
    for name in names:
        path = log_dir / name
        typer.echo(f"\n--- {path} ---")
        typer.echo(path.read_text().rstrip() if path.is_file() else "(no output)")


if __name__ == "__main__":
    app()
