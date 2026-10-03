"""Stage 2e: the BIDS validator, and its messages in plain language.

Tests marked ``bidsvalidator`` run the real validator (skipped when it is not installed) on a
valid dataset that is then broken in specific ways.
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from test_import_organize import fabricate, new_manifest
from typer.testing import CliRunner

from mrforge.cli import app
from mrforge.errors import StepError
from mrforge.importing import bids_validate as bv
from mrforge.importing.bids_validate import (
    ValidationReport,
    find_validator,
    format_report,
    load_messages,
    parse_validator_json,
    validate_dataset,
)
from mrforge.importing.classify import RuleSet, load_rules
from mrforge.importing.manifest import load_manifest
from mrforge.importing.organize import organize
from mrforge.workspace import Workspace

DATA = Path(__file__).parent / "data" / "bids_validator_issues.json"
runner = CliRunner()


@pytest.fixture(scope="module")
def rules() -> RuleSet:
    return load_rules()


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "study")


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRFORGE_CONFIG", str(tmp_path / "config.json"))


# -- the message file ---------------------------------------------------------------------


def test_messages_are_complete_and_match_the_validators_own_list() -> None:
    validator_codes = {i["code"]: i for i in json.loads(DATA.read_text())["issues"]}
    messages = load_messages()
    assert len(messages) >= 55
    for code, msg in messages.items():
        assert code in validator_codes, f"code {code} does not exist in the validator"
        assert validator_codes[code]["key"] == msg.key, f"code {code}: key differs"
        for part in (msg.what, msg.why, msg.action):
            assert part.strip() and part.strip()[0].isupper(), f"code {code}: {part!r}"
            assert part.rstrip().endswith((".", ")")), f"code {code} should end in a full stop"


def test_the_problems_an_mri_import_can_cause_are_all_explained() -> None:
    must_have = {1, 10, 12, 15, 26, 27, 29, 31, 32, 33, 37, 49, 50, 57, 67, 74, 90, 91, 92, 99,
                 101, 113}  # fmt: skip
    assert must_have <= set(load_messages())


def test_a_broken_message_file_is_a_plain_error(tmp_path: Path) -> None:
    bad = tmp_path / "m.yaml"
    bad.write_text("messages:\n  1: {key: A}\n")  # what/why/action missing
    with pytest.raises(StepError) as info:
        load_messages(bad)
    assert info.value.code == "MESSAGES_INVALID"


# -- turning validator output into plain language -----------------------------------------

REAL_SHAPE = {
    "issues": {
        "errors": [
            {
                "key": "INTENDED_FOR", "code": 37, "severity": "error",
                "reason": "technical text", "helpUrl": "https://example.org/37",
                "additionalFileCount": 3,
                "files": [
                    {
                        "key": "INTENDED_FOR", "code": 37, "severity": "error",
                        "evidence": f"func/x{i}.nii.gz",
                        "file": {"relativePath": f"/sub-001/fmap/f{i}.json"},
                    }
                    for i in range(7)
                ],
            },
            {
                "key": "SOMETHING_NEW", "code": 999, "severity": "error",
                "reason": "The validator says something new and technical.",
                "helpUrl": "https://example.org/999", "files": [], "additionalFileCount": 0,
            },
        ],
        "warnings": [
            {
                "key": "NO_AUTHORS", "code": 113, "severity": "warning", "reason": "no authors",
                "helpUrl": "https://example.org/113", "additionalFileCount": 0,
                "files": [{"key": "NO_AUTHORS", "code": 113, "file": None, "evidence": None}],
            }
        ],
    },
    "summary": {"subjects": ["001"], "sessions": [], "tasks": ["rest"], "totalFiles": 25,
                "size": 100, "dataTypes": ["T1w", "bold"]},
}  # fmt: skip


def test_parsing_translates_counts_files_and_orders_errors_first() -> None:
    errors, warnings, summary = parse_validator_json(REAL_SHAPE, load_messages())
    assert [i.code for i in errors] == [37, 999] and [i.code for i in warnings] == [113]
    first = errors[0]
    assert first.translated and "does not exist" in first.what
    assert first.files == [f"sub-001/fmap/f{i}.json" for i in range(5)]  # shown: at most five
    assert first.n_files == 10  # 7 listed by the validator + 3 more it counted
    assert first.details[0] == "sub-001/fmap/f0.json: func/x0.nii.gz"
    assert summary == {"subjects": 1, "sessions": 0, "tasks": ["rest"], "files": 25,
                       "size_bytes": 100, "data_types": ["T1w", "bold"]}  # fmt: skip


def test_unknown_codes_are_shown_honestly_not_hidden() -> None:
    errors, _, _ = parse_validator_json(REAL_SHAPE, load_messages())
    unknown = errors[1]
    assert not unknown.translated
    assert unknown.what == "The validator says something new and technical."
    assert "no plain-language explanation" in unknown.why
    assert "https://example.org/999" in unknown.action


def test_report_text_is_readable() -> None:
    errors, warnings, summary = parse_validator_json(REAL_SHAPE, load_messages())
    report = ValidationReport(validator="bids-validator", version="1.15.0", dataset="rawbids",
                              errors=errors, warnings=warnings, summary=summary)  # fmt: skip
    text = format_report(report)
    assert text.index("Problems that need fixing (2)") < text.index("Worth knowing (1)")
    assert "Why:" in text and "What to do:" in text and "and 5 more" in text
    assert "(BIDS validator code 37: INTENDED_FOR)" in text
    assert "not yet explained in plain language" in text  # for code 999
    assert not report.ok


def test_a_clean_report_says_so() -> None:
    report = ValidationReport(validator="v", version="1", dataset="rawbids", summary={"files": 3})
    assert report.ok and "No problems found" in format_report(report)
    only_warnings = ValidationReport(validator="v", version="1", dataset="rawbids")
    only_warnings.warnings = parse_validator_json(REAL_SHAPE, load_messages())[1]
    text = format_report(only_warnings)
    assert "No errors" in text and "Worth knowing (1)" in text and only_warnings.ok


# -- finding and running the validator (stand-in program) ---------------------------------

STUB = """#!{python}
import json, os, sys
if sys.argv[1:] == ["--version"]:
    print("bids-validator@9.9.9")
    sys.exit(0)
record = {{"argv": sys.argv[1:], "path": os.environ["PATH"]}}
open(os.environ["STUB_LOG"], "w").write(json.dumps(record))
print(os.environ.get("STUB_OUTPUT", "not json"))
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""


def make_stub(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / "bids-validator"
    exe.write_text(STUB.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


@pytest.fixture
def stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_config: None) -> Path:
    exe = make_stub(tmp_path / "somewhere")
    monkeypatch.setenv("STUB_LOG", str(tmp_path / "stub.log"))
    monkeypatch.setattr(bv, "FALLBACK_LOCATIONS", ())
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    return exe


def test_validator_is_found_on_path_in_config_or_in_an_nvm_install(
    stub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(StepError) as info:
        find_validator()
    err = info.value
    assert (
        err.code == "VALIDATOR_NOT_FOUND"
        and "npm install -g bids-validator" in err.suggested_action
    )
    assert "mrforge config bids-validator" in err.suggested_action

    monkeypatch.setenv("PATH", f"{stub.parent}:/usr/bin:/bin")
    assert find_validator() == stub  # on PATH
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    nvm = make_stub(tmp_path / "nohome" / ".nvm" / "versions" / "node" / "v22.1.0" / "bin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    assert find_validator() == nvm  # an nvm install, although PATH has no node

    other = make_stub(tmp_path / "configured")
    assert find_validator(setting=str(other)) == other  # the setting wins


def test_validate_runs_the_program_with_node_reachable_and_saves_the_report(
    ws: Workspace, stub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (ws.root / "rawbids").mkdir(exist_ok=True)
    monkeypatch.setenv("STUB_OUTPUT", json.dumps(REAL_SHAPE))
    monkeypatch.setenv("STUB_EXIT", "1")  # the real validator exits 1 when there are errors
    monkeypatch.setenv("PATH", f"{stub.parent}:/usr/bin:/bin")
    report = validate_dataset(ws)
    call = json.loads((tmp_path / "stub.log").read_text())
    assert call["argv"] == ["--json", str(ws.root / "rawbids")]
    assert call["path"].startswith(str(stub.parent))  # node next to the validator is reachable
    assert report.version == "bids-validator@9.9.9" and not report.ok
    saved = ValidationReport.model_validate_json(
        (ws.root / "imports/bids-validation.json").read_text()
    )
    assert [i.code for i in saved.errors] == [37, 999]


def test_garbage_output_and_missing_dataset_are_plain_errors(
    ws: Workspace, stub: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", f"{stub.parent}:/usr/bin:/bin")
    with pytest.raises(StepError) as info:
        validate_dataset(ws)  # no rawbids/ folder yet... create then fail on output
    assert info.value.code in ("NOTHING_TO_VALIDATE", "VALIDATOR_FAILED")
    (ws.root / "rawbids").mkdir(exist_ok=True)
    with pytest.raises(StepError) as info:
        validate_dataset(ws)  # the stub prints 'not json'
    assert info.value.code == "VALIDATOR_FAILED" and "Traceback" not in info.value.format()


def test_cli_config_for_the_validator(stub: Path, tmp_path: Path) -> None:
    missing = runner.invoke(app, ["config", "bids-validator", str(tmp_path / "nope")])
    assert missing.exit_code == 1 and "is not a file" in missing.output
    ok = runner.invoke(app, ["config", "bids-validator", str(stub)])
    assert ok.exit_code == 0 and str(stub) in ok.output
    assert str(stub) in runner.invoke(app, ["config", "bids-validator"]).output


def test_cli_validate_without_a_validator_is_a_plain_error(ws: Workspace, stub: Path) -> None:
    (ws.root / "rawbids").mkdir(exist_ok=True)
    r = runner.invoke(app, ["import", "validate", "-w", str(ws.root)])
    assert r.exit_code == 1 and "VALIDATOR_NOT_FOUND" in r.output and "Traceback" not in r.output


# -- the real validator -------------------------------------------------------------------

try:
    find_validator()
    HAVE_VALIDATOR = True
except StepError:
    HAVE_VALIDATOR = False
needs_validator = pytest.mark.skipif(
    not HAVE_VALIDATOR, reason="the BIDS validator is not installed"
)
RAW = "rawbids/sub-001"


@pytest.fixture
def valid(ws: Workspace, rules: RuleSet) -> Workspace:
    m = new_manifest(ws, rules)
    fabricate(ws, m, rules)
    organize(ws, m, rules)
    return ws


def edit_json(ws: Workspace, rel: str, change) -> None:  # type: ignore[no-untyped-def]
    path = ws.root / "rawbids" / rel
    data = json.loads(path.read_text())
    change(data)
    path.chmod(0o644)
    path.write_text(json.dumps(data))


def codes(report: ValidationReport) -> dict[str, set[int]]:
    return {
        "errors": {i.code for i in report.errors},
        "warnings": {i.code for i in report.warnings},
    }


@pytest.mark.bidsvalidator
@needs_validator
def test_a_dataset_written_by_mrforge_passes(valid: Workspace) -> None:
    report = validate_dataset(valid)
    assert report.ok, format_report(report)
    assert codes(report)["errors"] == set() and codes(report)["warnings"] <= {113}
    assert report.summary["subjects"] == 1 and report.summary["tasks"] == ["rest"]


@pytest.mark.bidsvalidator
@needs_validator
def test_adding_authors_removes_the_only_warning_and_mrforge_keeps_the_edit(
    valid: Workspace, rules: RuleSet
) -> None:
    edit_json(
        valid,
        "dataset_description.json",
        lambda d: d.update(Authors=["A. Researcher", "B. Colleague"]),
    )
    assert codes(validate_dataset(valid))["warnings"] == set()
    organize(valid, load_manifest(valid), rules)  # must not overwrite the edited description
    assert json.loads((valid.root / "rawbids/dataset_description.json").read_text())["Authors"]


def _rename_t1(ws: Workspace) -> None:
    for ext in ("nii.gz", "json"):
        (ws.root / f"{RAW}/anat/sub-001_T1w.{ext}").rename(
            ws.root / f"{RAW}/anat/sub-001_T1w_typo.{ext}"
        )


def _drop_description(ws: Workspace) -> None:
    (ws.root / "rawbids/dataset_description.json").unlink()


def _drop_task_name(ws: Workspace) -> None:
    edit_json(ws, "sub-001/func/sub-001_task-rest_bold.json", lambda d: d.pop("TaskName"))


def _bad_intended_for(ws: Workspace) -> None:
    missing = ["func/sub-001_task-nothing_bold.nii.gz"]
    edit_json(
        ws, "sub-001/fmap/sub-001_acq-fmap_phasediff.json", lambda d: d.update(IntendedFor=missing)
    )


def _invalid_json(ws: Workspace) -> None:
    path = ws.root / f"{RAW}/anat/sub-001_T2w.json"
    path.chmod(0o644)
    path.write_text("{not valid json")


def _short_bval(ws: Workspace) -> None:
    path = ws.root / f"{RAW}/dwi/sub-001_dwi.bval"
    path.chmod(0o644)
    path.write_text("1000 1000 1000\n")


def _no_magnitude(ws: Workspace) -> None:
    for name in ("magnitude1", "magnitude2"):
        for ext in ("nii.gz", "json"):
            (ws.root / f"{RAW}/fmap/sub-001_acq-fmap_{name}.{ext}").unlink()


def _empty_image(ws: Workspace) -> None:
    path = ws.root / f"{RAW}/anat/sub-001_T2w.nii.gz"
    path.unlink()
    path.write_bytes(b"")


def _orphan_sidecar(ws: Workspace) -> None:
    (ws.root / f"{RAW}/anat/sub-001_T1w.nii.gz").unlink()


# name -> (how to break it, codes the validator may answer with, does it count as an error?)
BREAKS = {
    "typo in a file name": (_rename_t1, {1}, True),
    "dataset_description.json deleted": (_drop_description, {57}, True),
    "TaskName removed": (_drop_task_name, {50}, True),
    "IntendedFor points nowhere": (_bad_intended_for, {37}, True),
    "invalid JSON": (_invalid_json, {27}, True),
    "b-value file too short": (_short_bval, {29, 31, 46, 88, 89}, True),
    "empty image file": (_empty_image, {26, 36, 99}, True),
    "image deleted but sidecar left": (_orphan_sidecar, {90}, True),
    # this validator version only warns when the magnitude images of a fieldmap are gone
    "fieldmap magnitude images deleted": (_no_magnitude, {91, 92}, False),
}


@pytest.mark.bidsvalidator
@needs_validator
@pytest.mark.parametrize("name", list(BREAKS))
def test_real_problems_are_found_and_explained_in_plain_language(
    valid: Workspace, name: str
) -> None:
    breaker, expected, is_error = BREAKS[name]
    breaker(valid)
    report = validate_dataset(valid)
    found = codes(report)["errors"] | codes(report)["warnings"]
    assert found & expected, f"{name}: expected one of {expected}, validator said {found}"
    assert report.ok != is_error
    for issue in [*report.errors, *report.warnings]:
        assert issue.translated, f"no plain-language text for code {issue.code} ({issue.key})"
        assert issue.what and issue.why and issue.action
    text = format_report(report)
    assert "Problems that need fixing" in text or "Worth knowing" in text
    assert "What to do:" in text
    assert "NOT_INCLUDED" not in text.split("(BIDS validator code")[0]  # jargon only in the tag


@pytest.mark.bidsvalidator
@needs_validator
def test_cli_validate_on_valid_and_broken_datasets(valid: Workspace) -> None:
    w = str(valid.root)
    good = runner.invoke(app, ["import", "validate", "-w", w])
    assert good.exit_code == 0 and "No errors" in good.output and "authors" in good.output
    as_json = runner.invoke(app, ["import", "validate", "--json", "-w", w])
    assert json.loads(as_json.output)["errors"] == []
    _drop_task_name(valid)
    bad = runner.invoke(app, ["import", "validate", "-w", w])
    assert bad.exit_code == 1 and "no TaskName" in bad.output and "--task" in bad.output


# -- the real session ---------------------------------------------------------------------


@pytest.mark.realdata
@pytest.mark.bidsvalidator
@needs_validator
def test_real_session_passes_the_validator(ws: Workspace) -> None:
    from mrforge.importing.convert import convert_import
    from mrforge.importing.scan import scan_source

    base = Path(os.environ.get("MRFORGE_TEST_DATA", "~/Documents/mri-test-data")).expanduser()
    if not (base / "test").is_dir():
        pytest.skip(f"test session not found: {base / 'test'}")
    rules = load_rules()
    manifest, _ = scan_source(ws, base / "test")
    assert convert_import(ws, manifest, rules).failed == []
    organize(ws, manifest, rules)
    report = validate_dataset(ws)
    assert report.ok, format_report(report)
    assert codes(report)["warnings"] == {113}  # only: no authors listed
    assert report.summary["files"] == 25
