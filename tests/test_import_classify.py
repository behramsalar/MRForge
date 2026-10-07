"""Stage 2b: series classification, confidence, and the user's own decisions."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mrforge.cli import app
from mrforge.errors import StepError
from mrforge.importing.classify import (
    RuleSet,
    apply_rules,
    classify_all,
    classify_series,
    effective,
    effective_all,
    load_rules,
    set_override,
)
from mrforge.importing.manifest import load_manifest, save_manifest
from mrforge.importing.models import DicomSeries, ImportManifest, SourceInfo
from mrforge.importing.report import format_manifest
from mrforge.workspace import Workspace

DATA = Path(__file__).parent / "data" / "siemens_session_series.json"
runner = CliRunner()

# series number -> (kind, action, confidence, entities)   [the real session, 27 series]
EXPECTED = {
    1: ("localizer", "skip", "High", {}),
    2: ("T1w", "import", "High", {}),
    3: ("T2w", "import", "High", {}),
    4: ("fieldmap-magnitude", "import", "High", {}),
    5: ("fieldmap-phase", "import", "High", {}),
    6: ("bold", "import", "High", {"task": "rest"}),
    7: ("scanner-generated", "skip", "High", {}),  # MoCoSeries: ImageType says ORIGINAL!
    9: ("dwi", "import", "High", {}),
    11: ("scanner-generated", "skip", "High", {}),  # dti_ADC
    12: ("scanner-generated", "skip", "High", {}),  # dti_TRACEW
    13: ("scanner-generated", "skip", "High", {}),  # dti_FA
    14: ("scanner-generated", "skip", "High", {}),  # dti_ColFA
    15: ("scanner-generated", "skip", "High", {}),  # dti_TENSOR (no image at all)
    16: ("scanner-generated", "skip", "High", {}),  # dti_TENSOR_B0
    17: ("fieldmap-magnitude", "import", "High", {}),
    18: ("fieldmap-phase", "import", "High", {}),
    19: ("bold", "ask", "High", {}),  # a BOLD run, but the task name is unknown
    20: ("scanner-generated", "skip", "High", {}),
    22: ("scanner-generated", "skip", "High", {}),  # Design
    23: ("scanner-generated", "skip", "High", {}),  # EvaSeries_GLM
    24: ("scanner-generated", "skip", "High", {}),  # Mean_&_t-Maps
    25: ("bold", "ask", "High", {}),
    26: ("scanner-generated", "skip", "High", {}),
    28: ("scanner-generated", "skip", "High", {}),
    29: ("scanner-generated", "skip", "High", {}),
    30: ("scanner-generated", "skip", "High", {}),
    99: ("scanner-report", "skip", "High", {}),
}


def real_series() -> list[DicomSeries]:
    return [DicomSeries(**s) for s in json.loads(DATA.read_text())["series"]]


def make(number: int, description: str, **kwargs: object) -> DicomSeries:
    defaults: dict[str, object] = {
        "uid": f"uid-{number}",
        "number": number,
        "description": description,
        "protocol": description,
        "image_type": ["ORIGINAL", "PRIMARY", "M", "NONE"],
        "rows": 64,
        "columns": 64,
        "slices": 40,
        "volumes": 1,
        "n_files": 1,
    }
    return DicomSeries(**{**defaults, **kwargs})  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def rules() -> RuleSet:
    return load_rules()


# -- the real session -------------------------------------------------------------------------


def test_all_real_series_are_classified_as_expected(rules: RuleSet) -> None:
    series = real_series()
    assert len(series) == 27 and sorted(s.number or 0 for s in series) == sorted(EXPECTED)
    got = classify_all(series, rules)
    for s in series:
        c = got[s.uid]
        assert (c.kind, c.action, c.confidence, c.entities) == EXPECTED[s.number or 0], (
            f"series {s.number} ({s.description}): {c.kind} {c.action} {c.confidence} {c.reasons}"
        )


def test_summary_counts_and_what_is_asked(rules: RuleSet) -> None:
    got = classify_all(real_series(), rules)
    actions = [c.action for c in got.values()]
    assert (actions.count("import"), actions.count("skip"), actions.count("ask")) == (8, 17, 2)
    asking = [c for c in got.values() if c.action == "ask"]
    assert all(c.needs == ["task"] and c.kind == "bold" for c in asking)


def test_every_decision_comes_with_plain_language_reasons(rules: RuleSet) -> None:
    for c in classify_all(real_series(), rules).values():
        assert len(c.reasons) >= 2 and c.rule_ids
        assert all(r[0].isupper() for r in c.reasons)  # sentences, not codes
    moco = next(
        c
        for s, c in zip(real_series(), classify_all(real_series(), rules).values(), strict=True)
        if s.number == 7
    )
    assert any("MoCoSeries" in r for r in moco.reasons)
    assert any("same protocol and size" in r for r in moco.reasons)


def test_moco_copy_is_found_although_imagetype_says_original(rules: RuleSet) -> None:
    series = {s.number: s for s in real_series()}
    assert series[7].image_type[0] == "ORIGINAL"  # the trap in this session
    c = classify_series(series[7], list(series.values()), rules)
    assert (c.kind, c.action) == ("scanner-generated", "skip")


# -- confidence, unknown and conflicting cases ------------------------------------------------


def test_unknown_series_is_never_assigned(rules: RuleSet) -> None:
    odd = make(5, "weird_sequence_v7", image_type=["ORIGINAL", "PRIMARY", "OTHER", "NONE"])
    c = classify_series(odd, [odd], rules)
    assert (c.kind, c.action, c.confidence) == ("unknown", "ask", "Low")
    assert c.datatype is None and "No rule recognised" in c.reasons[0]


def test_disagreeing_clues_make_it_unknown_and_explain_both_sides(rules: RuleSet) -> None:
    both = make(
        3, "t1w dti", image_type=["ORIGINAL", "PRIMARY", "DIFFUSION", "NONE"], slices=80, volumes=1
    )
    c = classify_series(both, [both], rules)
    assert (c.kind, c.action, c.confidence) == ("unknown", "ask", "Low")
    text = " ".join(c.reasons)
    assert "disagree" in text and "T1w" in text and "dwi" in text


def test_few_slices_alone_never_make_a_localizer(rules: RuleSet) -> None:
    tiny = make(5, "t1w", slices=3)  # small image, but named T1w: not a localizer
    c = classify_series(tiny, [tiny], rules)
    assert c.kind == "T1w"
    named = make(1, "AAHScout", slices=3)  # the name decides
    assert classify_series(named, [named], rules).kind == "localizer"
    nameless = make(2, "x", slices=3)
    assert classify_series(nameless, [nameless], rules).kind == "unknown"


def test_lone_fieldmap_magnitude_is_medium_confidence(rules: RuleSet) -> None:
    lone = make(4, "fmap")  # no phase image anywhere in the session
    c = classify_series(lone, [lone], rules)
    assert (c.kind, c.action, c.confidence) == ("fieldmap-magnitude", "import", "Medium")


def test_moco_name_without_a_raw_sibling_is_still_skipped_at_medium(rules: RuleSet) -> None:
    moco = make(7, "MoCoSeries", image_type=["ORIGINAL", "PRIMARY", "FMRI", "NONE"], volumes=100)
    c = classify_series(moco, [moco], rules)
    assert (c.kind, c.action, c.confidence) == ("scanner-generated", "skip", "Medium")


def test_a_relation_alone_never_marks_a_series_as_scanner_generated(rules: RuleSet) -> None:
    raw = make(6, "resting", image_type=["ORIGINAL", "PRIMARY", "FMRI", "NONE"], volumes=100)
    twin = make(7, "resting", image_type=["ORIGINAL", "PRIMARY", "FMRI", "NONE"], volumes=100)
    c = classify_series(twin, [raw, twin], rules)  # same protocol and size, but not named MoCo
    assert c.kind == "bold" and c.action == "import"


def test_unrecognised_name_with_functional_signals_is_medium_and_asks_for_the_task(
    rules: RuleSet,
) -> None:
    mystery = make(8, "myseq", image_type=["ORIGINAL", "PRIMARY", "FMRI", "NONE"], volumes=100)
    c = classify_series(mystery, [mystery], rules)
    assert (c.kind, c.confidence, c.action, c.needs) == ("bold", "Medium", "ask", ["task"])


def test_task_is_read_from_the_name(rules: RuleSet) -> None:
    for name in ("resting", "rest_state_p2", "Resting_State"):
        s = make(6, name, image_type=["ORIGINAL", "PRIMARY", "FMRI", "NONE"], volumes=200)
        c = classify_series(s, [s], rules)
        assert c.entities == {"task": "rest"} and c.action == "import", name


# -- the rules file ---------------------------------------------------------------------------


def write_rules(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


GOOD = """
version: 1
rules:
  - id: a
    kind: T1w
    action: import
    datatype: anat
    suffix: T1w
    reason: "t1"
    signals:
      - {family: text, say: "x", field: text, regex: "t1"}
"""


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("{not yaml", "rules file"),
        (GOOD.replace('regex: "t1"', 'regex: "("'), "unterminated|missing|parenthesis"),
        (GOOD.replace("field: text", "field: colour"), "unknown field"),
        (GOOD.replace("datatype: anat\n    suffix: T1w\n", ""), "datatype"),
        (GOOD + GOOD.split("rules:")[1], "same id"),
        (GOOD.replace("signals:", "overrides: [zzz]\n    signals:"), "unknown rule"),
        (GOOD.replace('field: text, regex: "t1"', "predicate: nope"), "unknown predicate"),
        (GOOD.replace('field: text, regex: "t1"', "field: text"), "needs a test"),
        (GOOD.replace("min_families", "x") + "\nextra: 1", "Extra"),
    ],
)
def test_invalid_rules_files_give_plain_errors(tmp_path: Path, text: str, complaint: str) -> None:
    with pytest.raises(StepError) as info:
        load_rules(path=write_rules(tmp_path / "rules.yaml", text))
    err = info.value
    assert err.code == "RULES_INVALID" and "rules.yaml" in err.message
    assert err.suggested_action and "Traceback" not in err.format()


def test_a_valid_custom_rules_file_loads(tmp_path: Path) -> None:
    rules = load_rules(path=write_rules(tmp_path / "r.yaml", GOOD))
    assert list(rules.import_kinds()) == ["T1w"]


def test_workspace_rules_replace_the_default(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "w")
    assert "bold" in load_rules(ws).import_kinds()  # the built-in rules
    (ws.root / "imports").mkdir()
    write_rules(ws.root / "imports" / "classification_rules.yaml", GOOD)
    assert set(load_rules(ws).import_kinds()) == {"T1w"}  # the lab's own file wins


def test_required_clue_must_hold(rules: RuleSet) -> None:
    custom = RuleSet.model_validate(
        {
            "version": 1,
            "rules": [
                {
                    "id": "r",
                    "kind": "x",
                    "action": "skip",
                    "reason": "r",
                    "signals": [
                        {
                            "family": "text",
                            "required": True,
                            "say": "named x",
                            "field": "description",
                            "regex": "^x$",
                        },
                        {"family": "geometry", "say": "small", "field": "slices", "max": 5},
                    ],
                }
            ],
        }
    )
    only_geometry = make(1, "y", slices=3)
    assert classify_series(only_geometry, [only_geometry], custom).kind == "unknown"
    both = make(1, "x", slices=3)
    assert classify_series(both, [both], custom).confidence == "High"


# -- the user's own decisions -----------------------------------------------------------------


@pytest.fixture
def manifest(rules: RuleSet) -> ImportManifest:
    m = ImportManifest(
        id="import-001",
        source=SourceInfo(name="x", kind="folder", n_files=1, fingerprint="f"),
        dicom_dir="sourcedata/dicom/import-001",
        subject="sub-001",
        series=real_series(),
    )
    return apply_rules(m, rules)


def uid_of(m: ImportManifest, number: int) -> str:
    return next(s.uid for s in m.series if s.number == number)


def test_setting_the_task_makes_the_run_importable(
    manifest: ImportManifest, rules: RuleSet
) -> None:
    now = set_override(manifest, rules, 19, entities={"task": "visual"})
    assert (now.kind, now.action, now.entities, now.source) == (
        "bold", "import", {"task": "visual"}, "user",
    )  # fmt: skip
    assert now.needs == [] and "You set this series" in now.reasons[0]


def test_unknown_series_needs_a_type_before_it_can_be_imported(rules: RuleSet) -> None:
    odd = make(5, "weird")
    m = ImportManifest(
        id="import-001",
        source=SourceInfo(name="x", kind="folder", n_files=1, fingerprint="f"),
        dicom_dir="d",
        subject="sub-001",
        series=[odd],
    )
    apply_rules(m, rules)
    with pytest.raises(StepError) as info:
        set_override(m, rules, 5, entities={"acq": "x"})
    assert info.value.code == "SET_NEEDS_TYPE"
    now = set_override(m, rules, 5, kind="T2w")
    assert (now.kind, now.action, now.datatype, now.suffix) == ("T2w", "import", "anat", "T2w")


def test_a_skipped_scanner_series_can_be_switched_on(
    manifest: ImportManifest, rules: RuleSet
) -> None:
    with pytest.raises(StepError) as info:
        set_override(manifest, rules, 7)  # MoCoSeries: skipped, so a type is required
    assert info.value.code == "SET_NEEDS_TYPE" and "--type" in info.value.suggested_action
    now = set_override(manifest, rules, 7, kind="bold")
    assert now.action == "ask" and now.needs == ["task"]  # a bold run still needs its task
    now = set_override(manifest, rules, 7, entities={"task": "rest"})  # kind is remembered
    assert (now.kind, now.action, now.entities) == ("bold", "import", {"task": "rest"})


def test_skip_overrides_an_import(manifest: ImportManifest, rules: RuleSet) -> None:
    now = set_override(manifest, rules, 2, skip=True)
    assert (now.kind, now.action, now.source) == ("skipped-by-user", "skip", "user")
    back = set_override(manifest, rules, 2, kind="T1w")  # and can be turned back on
    assert back.action == "import" and back.kind == "T1w"


def test_changing_the_type_drops_labels_of_the_old_type(
    manifest: ImportManifest, rules: RuleSet
) -> None:
    set_override(manifest, rules, 6, entities={"task": "memory"})
    now = set_override(manifest, rules, 6, kind="dwi")
    assert now.kind == "dwi" and "task" not in now.entities


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"number": 999}, "UNKNOWN_SERIES"),
        ({"number": 2, "kind": "banana"}, "UNKNOWN_KIND"),
        ({"number": 19, "entities": {"task": "two words"}}, "BAD_LABEL"),
        ({"number": 19, "entities": {"task": "a-b"}}, "BAD_LABEL"),
        ({"number": 19, "entities": {"run": "1"}}, "BAD_LABEL"),
        ({"number": 2, "skip": True, "kind": "T1w"}, "SET_CONFLICT"),
    ],
)
def test_invalid_decisions_are_refused_in_plain_language(
    manifest: ImportManifest, rules: RuleSet, kwargs: dict[str, object], code: str
) -> None:
    with pytest.raises(StepError) as info:
        set_override(manifest, rules, **kwargs)  # type: ignore[arg-type]
    assert info.value.code == code and info.value.suggested_action
    assert not manifest.overrides  # a refused decision changes nothing


def test_ambiguous_series_number_is_reported(rules: RuleSet) -> None:
    twins = [make(4, "a", uid="u1"), make(4, "b", uid="u2")]
    m = ImportManifest(
        id="import-001",
        source=SourceInfo(name="x", kind="folder", n_files=1, fingerprint="f"),
        dicom_dir="d",
        subject="sub-001",
        series=twins,
    )
    with pytest.raises(StepError) as info:
        set_override(m, rules, 4, kind="T1w")
    assert info.value.code == "AMBIGUOUS_SERIES"


def test_decisions_survive_rerunning_the_rules_and_saving(
    manifest: ImportManifest, rules: RuleSet, tmp_path: Path
) -> None:
    set_override(manifest, rules, 19, entities={"task": "visual"})
    set_override(manifest, rules, 2, skip=True)
    apply_rules(manifest, rules)  # e.g. after editing the rules file
    again = ImportManifest.model_validate_json(manifest.model_dump_json())
    got = effective_all(again, rules)
    assert got[uid_of(again, 19)].entities == {"task": "visual"}
    assert got[uid_of(again, 2)].action == "skip"
    assert got[uid_of(again, 6)].source == "rules"  # untouched series stay with the rules


def test_old_manifests_without_classification_still_load() -> None:
    old = {
        "id": "import-001",
        "source": {"name": "x", "kind": "folder", "n_files": 1, "fingerprint": "f"},
        "dicom_dir": "d",
        "subject": "sub-001",
        "series": [json.loads(DATA.read_text())["series"][1]],
    }
    m = ImportManifest.model_validate(old)
    assert m.classifications == {} and m.overrides == {}
    assert effective(m, m.series[0].uid, load_rules()).kind == "T1w"


# -- CLI --------------------------------------------------------------------------------------


@pytest.fixture
def ws_with_import(tmp_path: Path, rules: RuleSet) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    m = ImportManifest(
        id="import-001",
        source=SourceInfo(name="session", kind="folder", n_files=1064, fingerprint="f"),
        dicom_dir="sourcedata/dicom/import-001",
        subject="sub-001",
        series=real_series(),
    )
    save_manifest(ws, apply_rules(m, rules))
    return ws


def test_cli_show_lists_the_plan_and_what_needs_input(ws_with_import: Workspace) -> None:
    out = runner.invoke(app, ["import", "show", "-w", str(ws_with_import.root)]).output
    assert "WILL BE" in out and "import as anat/T1w" in out
    assert "import as func/bold task-rest" in out and "skip (scanner-generated)" in out
    assert "8 to import, 17 skipped, 2 need your input" in out
    assert "mrforge import set 19 --task <name>" in out and "set 25 --task" in out
    assert "Why:" not in out
    why = runner.invoke(app, ["import", "show", "--why", "-w", str(ws_with_import.root)]).output
    assert "Why:" in why and "It is named MoCoSeries" in why


def test_cli_set_corrects_a_series_and_the_correction_is_used(ws_with_import: Workspace) -> None:
    w = str(ws_with_import.root)
    r = runner.invoke(app, ["import", "set", "19", "--task", "visual", "-w", w])
    assert r.exit_code == 0 and "func/bold task-visual" in r.output and "user" in r.output
    shown = runner.invoke(app, ["import", "show", "-w", w]).output
    assert "import as func/bold task-visual" in shown and "High (you)" in shown
    assert "9 to import, 17 skipped, 1 need your input" in shown
    # the correction is stored in the manifest, with the rules' result kept apart
    stored = load_manifest(ws_with_import)
    assert len(stored.overrides) == 1 and stored.classifications
    # and survives re-running the rules
    again = runner.invoke(app, ["import", "classify", "-w", w]).output
    assert "import as func/bold task-visual" in again


def test_cli_set_errors_are_plain(ws_with_import: Workspace) -> None:
    w = str(ws_with_import.root)
    for args, text in (
        (["set", "7"], "--type"),
        (["set", "2", "--type", "banana"], "Use one of"),
        (["set", "19", "--task", "a b"], "letters and digits"),
        (["set", "123", "--skip"], "no series number 123"),
    ):
        r = runner.invoke(app, ["import", *args, "-w", w])
        assert r.exit_code == 1 and text in r.output and "Traceback" not in r.output, args
    assert load_manifest(ws_with_import).overrides == {}


def test_cli_classify_with_a_rules_file(ws_with_import: Workspace, tmp_path: Path) -> None:
    rules = write_rules(tmp_path / "mine.yaml", GOOD)
    r = runner.invoke(
        app, ["import", "classify", "--rules", str(rules), "-w", str(ws_with_import.root)]
    )
    assert r.exit_code == 0 and "need your input" in r.output  # almost everything is unknown now
    broken = write_rules(tmp_path / "bad.yaml", "version: 1\nrules: oops")
    bad = runner.invoke(
        app, ["import", "classify", "--rules", str(broken), "-w", str(ws_with_import.root)]
    )
    assert bad.exit_code == 1 and "RULES_INVALID" in bad.output


def test_format_without_classification_still_works(rules: RuleSet) -> None:
    m = ImportManifest(
        id="import-001",
        source=SourceInfo(name="x", kind="folder", n_files=1, fingerprint="f"),
        dicom_dir="d",
        subject="sub-001",
        series=real_series(),
    )
    assert "WILL BE" not in format_manifest(m)


# -- other scanners and protocols (real sessions, written from what each series is) -------------

DATA_DIR = Path(__file__).parent / "data"
SKIP = ("scanner-generated", "skip")

# series number -> (kind, action).  Series 0 appears several times (non-image objects).
SIEMENS2 = {
    1: ("localizer", "skip"),
    3: SKIP,  # diffusion trace map made by the scanner
    4: SKIP,  # diffusion ADC map
    8: ("T1w", "import"),
    9: SKIP,  # multi-planar reformat (MPR) of the T1, flagged DERIVED
    10: SKIP,
}
PHILIPS = {
    401: ("T1w", "import"),
    501: ("bold", "import"),  # an acquisition stopped early: still a functional run
    601: ("bold", "import"),
    701: ("bold", "import"),
    801: ("dwi", "import"),
}
PHILIPS2 = {
    101: ("localizer", "skip"),  # named "Survey"
    201: ("T1w", "import"),
    301: ("T1w", "import"),
    401: ("bold", "ask"),  # FE_EPI: a functional run, but the task is unknown
    501: ("T2w", "import"),
    601: ("unknown", "ask"),  # "B0 map": a Philips fieldmap; not supported, so it asks
    701: ("T2w", "import"),
    801: ("FLAIR", "import"),
    901: ("dwi", "import"),  # only two volumes (b=0 and one b-value)
    902: SKIP,  # dADC map
    1001: ("T2w", "import"),
}


def load_session(name: str) -> list[DicomSeries]:
    return [DicomSeries(**s) for s in json.loads((DATA_DIR / name).read_text())["series"]]


@pytest.mark.parametrize(
    ("fixture", "expected", "n_series"),
    [
        ("siemens_session2_series.json", SIEMENS2, 6),
        ("philips_session_series.json", PHILIPS, 8),
        ("philips_session2_series.json", PHILIPS2, 13),
    ],
    ids=["siemens-2", "philips-1", "philips-2"],
)
def test_other_scanners_are_classified_correctly(
    rules: RuleSet, fixture: str, expected: dict[int, tuple[str, str]], n_series: int
) -> None:
    series = load_session(fixture)
    assert len(series) == n_series
    got = classify_all(series, rules)
    for s in series:
        c = got[s.uid]
        if s.number == 0:  # scanner objects without an image: never imported, never asked about
            assert (c.kind, c.action) == SKIP, f"{s.label}: {c.kind} {c.action}"
            continue
        assert (c.kind, c.action) == expected[s.number or 0], (
            f"series {s.number} ({s.label}): {c.kind} {c.action} {c.confidence} {c.reasons}"
        )
        assert c.reasons and (c.action != "import" or c.confidence in ("High", "Medium"))


def test_philips_functional_runs_get_a_task_from_their_resting_state_name(rules: RuleSet) -> None:
    got = classify_all(load_session("philips_session_series.json"), rules)
    series = {s.number: s for s in load_session("philips_session_series.json")}
    for number in (501, 601, 701):  # RSTNG_FE_EPI1 / EPI2: Philips for resting state
        assert got[series[number].uid].entities == {"task": "rest"}
    assert all(got[series[n].uid].confidence == "Medium" for n in (501, 601, 701))  # no FMRI type


def test_an_unnamed_functional_run_asks_for_its_task_and_is_not_imported(rules: RuleSet) -> None:
    series = {s.number: s for s in load_session("philips_session2_series.json")}
    c = classify_all(list(series.values()), rules)[series[401].uid]
    assert (c.kind, c.action, c.needs, c.confidence) == ("bold", "ask", ["task"], "Medium")


def test_unsupported_scanner_fieldmaps_are_asked_about_not_guessed(rules: RuleSet) -> None:
    series = load_session("philips_session2_series.json")
    b0 = next(s for s in series if s.label == "B0 map")
    c = classify_all(series, rules)[b0.uid]
    assert (c.kind, c.action, c.confidence) == ("unknown", "ask", "Low")


def test_reformats_are_found_by_name_but_mprage_is_not_a_reformat(rules: RuleSet) -> None:
    mprage = make(8, "t1_mprage_sag_p2_iso", slices=192)
    mpr = make(9, "t1_mprage_sag_p2_iso_MPR_tra", slices=184)  # name only (not flagged DERIVED)
    got = classify_all([mprage, mpr], rules)
    assert got[mprage.uid].kind == "T1w" and got[mprage.uid].action == "import"
    assert (got[mpr.uid].kind, got[mpr.uid].action) == SKIP
    assert got[mpr.uid].confidence == "Medium"  # the name alone: please check
    derived = make(10, "t1_mprage_MIP_cor", slices=100, image_type=["DERIVED", "PRIMARY", "M"])
    assert classify_all([derived], rules)[derived.uid].confidence == "High"


def test_a_derived_flag_alone_is_not_enough_to_drop_a_t1(rules: RuleSet) -> None:
    flagged = make(3, "t1w_3d", slices=180, image_type=["DERIVED", "PRIMARY", "M", "NONE"])
    c = classify_series(flagged, [flagged], rules)
    assert (c.kind, c.action, c.confidence) == ("unknown", "ask", "Low")  # the clues disagree


def test_objects_without_an_image_are_skipped(rules: RuleSet) -> None:
    blank = {"rows": None, "columns": None, "slices": None, "volumes": None}
    exam = make(0, "ExamCard", uid="exam", modality="MR", **blank)
    state = make(0, "x", uid="state", modality="PR", **blank)
    got = classify_all([exam, state], rules)
    assert got[exam.uid].action == "skip" and got[exam.uid].confidence == "Medium"
    assert got[state.uid].action == "skip" and got[state.uid].confidence == "High"


def test_flair_dwi_localizer_and_philips_names(rules: RuleSet) -> None:
    flair = make(8, "3D_Brain_VIEW_FLAIR_SHC", slices=381)
    assert classify_series(flair, [flair], rules).kind == "FLAIR"
    two = make(9, "DWI_og", volumes=2, slices=24, image_type=["ORIGINAL", "PRIMARY", "M_SE", "M"])
    assert (classify_series(two, [two], rules).kind, classify_series(two, [two], rules).action) == (
        "dwi",
        "import",
    )
    survey = make(
        1, "Survey", slices=12, volumes=None, image_type=["ORIGINAL", "PRIMARY", "M_FFE", "M"]
    )
    assert classify_series(survey, [survey], rules).kind == "localizer"
    philips_t1 = make(401, "", slices=190)
    philips_t1.protocol = "sT1W_3D_TFE_v2 SENSE"  # an 's' in front of T1W
    assert classify_series(philips_t1, [philips_t1], rules).kind == "T1w"
    adc = make(902, "dADC DWI_og", volumes=1, slices=24, image_type=["ADC_UNSPECIFIED", "ADC"])
    assert classify_series(adc, [adc], rules).confidence == "High"


def number_zero_manifest() -> ImportManifest:
    """Two scanner objects that both carry series number 0 (Philips ExamCard, presentation
    state) next to a real T1."""

    def make(
        uid: str, number: int, description: str, modality: str, rows: int | None
    ) -> DicomSeries:
        return DicomSeries(uid=uid, number=number, description=description, modality=modality, n_files=1,
                           rows=rows, columns=rows, slices=1 if rows else None, image_type=["ORIGINAL"] if rows else [])  # fmt: skip

    series = [
        make("uid-a", 0, "ExamCard", "MR", None),
        make("uid-b", 0, "T2W_DRIVE", "PR", None),
        make("uid-c", 501, "sT1W_3D_TFE", "MR", 64),
    ]
    manifest = ImportManifest(
        id="import-001", source=SourceInfo(name="x", kind="folder", n_files=3, fingerprint="f"),
        subject="sub-001", series=series,
    )  # fmt: skip
    return manifest


def test_series_that_share_a_number_are_decided_one_by_one_through_their_id() -> None:
    rules = load_rules(None)  # type: ignore[arg-type]
    manifest = number_zero_manifest()
    apply_rules(manifest, rules)
    both_skipped = {s.uid: effective(manifest, s.uid, rules).action for s in manifest.series}
    assert both_skipped["uid-a"] == "skip" and both_skipped["uid-b"] == "skip"
    # By number it is ambiguous, and the message tells them apart.
    with pytest.raises(StepError) as err:
        set_override(manifest, rules, 0, skip=True)
    assert (
        err.value.code == "AMBIGUOUS_SERIES"
        and "ExamCard" in err.value.probable_cause
        and "T2W_DRIVE" in err.value.probable_cause
    )
    assert "--uid" in err.value.suggested_action
    # By id it is exact, and only that series changes.
    now = set_override(manifest, rules, None, kind="T2w", uid="uid-b")
    assert now.kind == "T2w" and now.action == "import"
    assert effective(manifest, "uid-a", rules).action == "skip"


def test_a_series_that_is_not_there_is_reported_when_asked_by_id() -> None:
    rules = load_rules(None)  # type: ignore[arg-type]
    manifest = number_zero_manifest()
    with pytest.raises(StepError) as err:
        set_override(manifest, rules, None, skip=True, uid="nope")
    assert err.value.code == "UNKNOWN_SERIES"


def test_the_hint_for_series_zero_uses_the_id(tmp_path: Path) -> None:
    rules = load_rules(None)  # type: ignore[arg-type]
    manifest = number_zero_manifest()
    apply_rules(manifest, rules)
    manifest.overrides = {}
    text = format_manifest(manifest, effective_all(manifest, rules))
    assert "uid-" in text or "needs your input" not in text  # no ambiguous 'set 0' hint is printed
