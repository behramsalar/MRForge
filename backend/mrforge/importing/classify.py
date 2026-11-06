"""Decide what each DICOM series is, from several independent clues, with a confidence level.

Rules live in ``classification_rules.yaml`` (plain text). A series that matches nothing, or
whose matches disagree, is never assigned silently: it becomes "unknown" and waits for the
user (CLAUDE.md 2b). User decisions are stored as overrides, apart from the rule results, so
re-running the rules never loses them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from mrforge.errors import StepError
from mrforge.importing.models import (
    Classification,
    Confidence,
    DicomSeries,
    ImportManifest,
    Override,
)
from mrforge.workspace import Workspace

DEFAULT_RULES = Path(__file__).with_name("classification_rules.yaml")
WORKSPACE_RULES = "imports/classification_rules.yaml"  # a lab's own rules replace the default
ENTITY_VALUE = re.compile(r"[A-Za-z0-9]+")
USER_ENTITIES = ("task", "acq")  # labels the user may set

FIELDS = {
    "description", "protocol", "sequence_name", "text", "image_type", "modality", "rows",
    "columns", "slices", "volumes", "n_files", "repetition_time_s", "echo_time_s",
}  # fmt: skip


# -- relation predicates (how a series relates to the others in the session) ----------------


def _same_shape(a: DicomSeries, b: DicomSeries) -> bool:
    return (a.rows, a.columns, a.slices) == (b.rows, b.columns, b.slices)


def duplicates_raw_sibling(s: DicomSeries, everything: list[DicomSeries]) -> bool:
    """An earlier series with the same protocol and size exists (and is not itself a MoCo copy)."""
    if s.number is None:
        return False
    return any(
        o.uid != s.uid
        and o.number is not None
        and o.number < s.number
        and o.protocol == s.protocol
        and _same_shape(o, s)
        and o.volumes == s.volumes
        and not re.fullmatch(r"(?i)MoCoSeries", o.description)
        for o in everything
    )


def _has_partner(s: DicomSeries, everything: list[DicomSeries], image_kind: str) -> bool:
    return any(
        o.uid != s.uid and o.label == s.label and _same_shape(o, s) and image_kind in o.image_type
        for o in everything
    )


PREDICATES: dict[str, Callable[[DicomSeries, list[DicomSeries]], bool]] = {
    "duplicates_raw_sibling": duplicates_raw_sibling,
    "has_phase_partner": lambda s, all_: _has_partner(s, all_, "P"),
    "has_magnitude_partner": lambda s, all_: _has_partner(s, all_, "M"),
}


# -- the rules file -------------------------------------------------------------------------


def _check_regex(pattern: str) -> None:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"'{pattern}' is not a valid pattern ({exc})") from exc


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str
    say: str
    required: bool = False  # the rule only applies if this clue holds
    field: str | None = None
    regex: str | None = None
    contains_any: list[str] | None = None
    min: float | None = None
    max: float | None = None
    equals: float | None = None
    is_null: bool | None = None
    predicate: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Signal:
        if self.predicate is not None:
            if self.predicate not in PREDICATES:
                raise ValueError(f"unknown predicate '{self.predicate}'")
            return self
        if self.field not in FIELDS:
            raise ValueError(f"unknown field '{self.field}' (use one of {sorted(FIELDS)})")
        tests = [self.regex, self.contains_any, self.min, self.max, self.equals, self.is_null]
        if all(t is None for t in tests):
            raise ValueError("a signal needs a test (regex, contains_any, min, max, equals, ...)")
        if self.regex is not None:
            _check_regex(self.regex)
        return self


class TaskRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regex: str
    task: str

    @field_validator("regex")
    @classmethod
    def _pattern(cls, value: str) -> str:
        _check_regex(value)
        return value

    @field_validator("task")
    @classmethod
    def _label(cls, value: str) -> str:
        if not ENTITY_VALUE.fullmatch(value):
            raise ValueError("a task label may only contain letters and digits")
        return value


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    action: Literal["import", "skip"]
    reason: str
    datatype: str | None = None
    suffix: str | None = None
    min_families: int = 1
    high_families: int = 2
    overrides: list[str] = []
    needs: list[str] = []
    task_from_text: list[TaskRule] = []
    signals: list[Signal]

    @model_validator(mode="after")
    def _check(self) -> Rule:
        if self.action == "import" and not (self.datatype and self.suffix):
            raise ValueError("an import rule needs 'datatype' and 'suffix'")
        if self.high_families < self.min_families:
            raise ValueError("high_families cannot be smaller than min_families")
        return self


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    rules: list[Rule]

    @model_validator(mode="after")
    def _check(self) -> RuleSet:
        ids = [r.id for r in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("two rules share the same id")
        for rule in self.rules:
            for other in rule.overrides:
                if other not in ids:
                    raise ValueError(f"rule '{rule.id}' overrides unknown rule '{other}'")
        return self

    def import_kinds(self) -> dict[str, Rule]:
        """kind -> the import rule that defines it (what a user may set a series to)."""
        return {r.kind: r for r in self.rules if r.action == "import"}


def load_rules(ws: Workspace | None = None, path: Path | None = None) -> RuleSet:
    """The rules to use: an explicit file, else the workspace's own file, else the default."""
    if path is None and ws is not None and (ws.root / WORKSPACE_RULES).is_file():
        path = ws.root / WORKSPACE_RULES
    path = path or DEFAULT_RULES
    try:
        return RuleSet.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        detail = str(exc).strip().splitlines()
        raise StepError(
            code="RULES_INVALID",
            message=f"The classification rules file could not be used: {path.name}",
            probable_cause=(detail[-1] if detail else "unreadable") + ".",
            suggested_action="Correct the rules file (see the comments at its top), or remove it "
            "to use the built-in rules.",
        ) from exc


# -- evaluating rules -------------------------------------------------------------------------


def series_fields(s: DicomSeries) -> dict[str, Any]:
    return {
        "description": s.description,
        "protocol": s.protocol,
        "sequence_name": s.sequence_name or "",
        "text": " ".join(x for x in (s.description, s.protocol, s.sequence_name or "") if x),
        "image_type": s.image_type,
        "modality": s.modality,
        "rows": s.rows,
        "columns": s.columns,
        "slices": s.slices,
        "volumes": s.volumes,
        "n_files": s.n_files,
        "repetition_time_s": s.repetition_time_s,
        "echo_time_s": s.echo_time_s,
    }


def signal_holds(
    sig: Signal, s: DicomSeries, everything: list[DicomSeries], fields: dict[str, Any]
) -> bool:
    if sig.predicate is not None:
        return PREDICATES[sig.predicate](s, everything)
    value = fields[sig.field or ""]
    if sig.is_null is not None:
        return (value is None) == sig.is_null
    if sig.regex is not None:
        return isinstance(value, str) and re.search(sig.regex, value) is not None
    if sig.contains_any is not None:
        wanted = {w.upper() for w in sig.contains_any}
        return isinstance(value, list) and any(str(v).upper() in wanted for v in value)
    if not isinstance(value, int | float):
        return False
    if sig.min is not None and value < sig.min:
        return False
    if sig.max is not None and value > sig.max:
        return False
    return not (sig.equals is not None and value != sig.equals)


class _Candidate(BaseModel):
    rule: Rule
    confidence: Confidence
    reasons: list[str]


def _match(
    rule: Rule, s: DicomSeries, everything: list[DicomSeries], fields: dict[str, Any]
) -> _Candidate | None:
    held = [sig for sig in rule.signals if signal_holds(sig, s, everything, fields)]
    if any(sig.required and sig not in held for sig in rule.signals):
        return None
    families = {sig.family for sig in held}
    if len(families) < rule.min_families:
        return None
    confidence: Confidence = "High" if len(families) >= rule.high_families else "Medium"
    return _Candidate(rule=rule, confidence=confidence, reasons=[sig.say for sig in held])


def _rank(confidence: Confidence) -> int:
    return {"High": 2, "Medium": 1, "Low": 0}[confidence]


def _entities(rule: Rule, fields: dict[str, Any]) -> dict[str, str]:
    for tr in rule.task_from_text:
        if re.search(tr.regex, fields["text"]):
            return {"task": tr.task}
    return {}


def _from_rule(
    rule: Rule,
    confidence: Confidence,
    reasons: list[str],
    rule_ids: list[str],
    fields: dict[str, Any],
) -> Classification:
    entities = _entities(rule, fields) if rule.action == "import" else {}
    needs = [n for n in rule.needs if n not in entities]
    notes = [rule.reason] + [r[0].upper() + r[1:] for r in reasons]
    if needs:
        notes.append(f"Still needed before it can be imported: {', '.join(needs)}")
    return Classification(
        kind=rule.kind,
        action="ask" if needs else rule.action,
        confidence=confidence,
        datatype=rule.datatype,
        suffix=rule.suffix,
        entities=entities,
        needs=needs,
        reasons=notes,
        rule_ids=rule_ids,
    )


def classify_series(
    s: DicomSeries, everything: list[DicomSeries], rules: RuleSet
) -> Classification:
    fields = series_fields(s)
    found = [c for r in rules.rules if (c := _match(r, s, everything, fields)) is not None]
    suppressed = {other for c in found for other in c.rule.overrides}
    found = [c for c in found if c.rule.id not in suppressed]
    by_kind: dict[str, list[_Candidate]] = {}
    for c in found:
        by_kind.setdefault(c.rule.kind, []).append(c)
    if len(by_kind) == 1:
        group = next(iter(by_kind.values()))
        best = max(group, key=lambda c: _rank(c.confidence))
        reasons = list(dict.fromkeys(r for c in group for r in c.reasons))
        return _from_rule(best.rule, best.confidence, reasons, [c.rule.id for c in group], fields)
    if len(by_kind) > 1:
        reasons = ["The clues disagree about what this series is:"]
        for kind, group in by_kind.items():
            why = "; ".join(dict.fromkeys(r for c in group for r in c.reasons))
            reasons.append(f"It could be {kind}: {why}")
        return Classification(
            kind="unknown",
            action="ask",
            confidence="Low",
            reasons=reasons,
            rule_ids=[c.rule.id for c in found],
        )
    return Classification(
        kind="unknown",
        action="ask",
        confidence="Low",
        reasons=["No rule recognised this series."],
    )


def classify_all(series: list[DicomSeries], rules: RuleSet) -> dict[str, Classification]:
    return {s.uid: classify_series(s, series, rules) for s in series}


def apply_rules(manifest: ImportManifest, rules: RuleSet) -> ImportManifest:
    """(Re)run the rules; user overrides are kept."""
    manifest.classifications = classify_all(manifest.series, rules)
    return manifest


# -- user decisions ---------------------------------------------------------------------------


def effective(manifest: ImportManifest, uid: str, rules: RuleSet) -> Classification:
    """The classification in force: the rules' result with the user's override applied."""
    base = manifest.classifications.get(uid)
    if base is None:
        series = next(s for s in manifest.series if s.uid == uid)
        base = classify_series(series, manifest.series, rules)
    override = manifest.overrides.get(uid)
    if override is None:
        return base
    if not (override.skip or override.kind or override.entities):
        return base  # only a fieldmap choice was made; the type is still the rules' result
    when = override.decided.strftime("%Y-%m-%d %H:%M")
    if override.skip:
        return Classification(
            kind="skipped-by-user",
            action="skip",
            confidence="High",
            reasons=[f"You chose to skip this series ({when})"],
            source="user",
        )
    if override.kind:
        rule = rules.import_kinds().get(override.kind)
        if rule is None:  # the rules file changed and no longer has this kind
            return base
        kind, datatype, suffix = override.kind, rule.datatype, rule.suffix
        entities = {**(base.entities if base.kind == kind else {}), **override.entities}
        needs = [n for n in rule.needs if n not in entities]
    else:  # only labels were set (for example a task name): keep the rules' type
        if base.datatype is None:
            return base
        kind, datatype, suffix = base.kind, base.datatype, base.suffix
        entities = {**base.entities, **override.entities}
        needs = [n for n in base.needs if n not in entities]
    return Classification(
        kind=kind,
        action="ask" if needs else "import",
        confidence="High",
        datatype=datatype,
        suffix=suffix,
        entities=entities,
        needs=needs,
        reasons=[f"You set this series ({when}): " + _describe_override(override)],
        rule_ids=base.rule_ids,
        source="user",
    )


def _describe_override(o: Override) -> str:
    parts = ([f"type {o.kind}"] if o.kind else []) + [f"{k} {v}" for k, v in o.entities.items()]
    return ", ".join(parts) or "no change"


def effective_all(manifest: ImportManifest, rules: RuleSet) -> dict[str, Classification]:
    return {s.uid: effective(manifest, s.uid, rules) for s in manifest.series}


def find_series(
    manifest: ImportManifest, number: int | None, uid: str | None = None
) -> DicomSeries:
    """The series a decision is about. Series are told apart by their unique id; the number
    is only a convenience (the command line) and must then be unique: scanners repeat numbers
    (Philips gives several non-image objects number 0)."""
    if uid is not None:
        found = next((s for s in manifest.series if s.uid == uid), None)
        if found is None:
            raise StepError(
                code="UNKNOWN_SERIES",
                message=f"There is no such series in {manifest.id}.",
                suggested_action="Reload the page to see the current list.",
            )
        return found
    matches = [s for s in manifest.series if s.number == number]
    if not matches:
        raise StepError(
            code="UNKNOWN_SERIES",
            message=f"There is no series number {number} in {manifest.id}.",
            suggested_action="Run 'mrforge import show' to see the series numbers.",
        )
    if len(matches) > 1:
        raise StepError(
            code="AMBIGUOUS_SERIES",
            message=f"Series number {number} is used by more than one series in {manifest.id}.",
            probable_cause="The scanner repeats series numbers: "
            + "; ".join(
                f"{s.description or '(no name)'} ({s.modality}, {s.n_files} files)" for s in matches
            )
            + ".",
            suggested_action="Choose the series from the list in the web page, or on the command "
            "line add --uid with the series' unique id (see 'mrforge import show --why').",
        )
    return matches[0]


def set_override(
    manifest: ImportManifest,
    rules: RuleSet,
    number: int | None,
    kind: str | None = None,
    skip: bool = False,
    entities: dict[str, str] | None = None,
    fieldmap: str | None = None,
    uid: str | None = None,
) -> Classification:
    """Record a user decision for one series and return the classification now in force."""
    series = find_series(manifest, number, uid)
    entities = entities or {}
    kinds = rules.import_kinds()
    if skip and (kind or entities):
        raise StepError(
            code="SET_CONFLICT",
            message="A series cannot be skipped and set to a type at the same time.",
            suggested_action="Use either --skip, or --type / --task.",
        )
    if kind is not None and kind not in kinds:
        raise StepError(
            code="UNKNOWN_KIND",
            message=f"'{kind}' is not a type MRForge can import.",
            probable_cause="The type is misspelled.",
            suggested_action=f"Use one of: {', '.join(sorted(kinds))}.",
        )
    for key, value in entities.items():
        if key not in USER_ENTITIES or not ENTITY_VALUE.fullmatch(value):
            raise StepError(
                code="BAD_LABEL",
                message=f"'{key}={value}' is not a valid label.",
                probable_cause="Labels may only contain letters and digits (no spaces or dashes).",
                suggested_action="Use something like --task rest or --acq highres.",
            )
    if fieldmap is not None and fieldmap != "none" and not fieldmap.isdigit():
        raise StepError(
            code="BAD_FIELDMAP",
            message=f"'{fieldmap}' is not a fieldmap choice.",
            probable_cause="Give the series number of a fieldmap, or 'none'.",
            suggested_action="For example 'mrforge import set 6 --fieldmap 4', or --fieldmap none.",
        )
    current = effective(manifest, series.uid, rules)
    only_fieldmap = fieldmap is not None and kind is None and not entities and not skip
    if only_fieldmap and current.datatype not in ("func", "dwi"):
        raise StepError(
            code="FIELDMAP_NOT_APPLICABLE",
            message=f"Series {number} is not a functional or diffusion run ({current.kind}), "
            "so it has no fieldmap.",
            suggested_action="Only BOLD and diffusion runs use a fieldmap.",
        )
    if not skip and kind is None and current.datatype is None and not only_fieldmap:
        raise StepError(
            code="SET_NEEDS_TYPE",
            message=f"Series {number} is not recognised as importable data ({current.kind}).",
            probable_cause="To import it MRForge needs to know what it is.",
            suggested_action=f"Add --type, for example 'mrforge import set {number} --type bold'.",
        )
    previous = manifest.overrides.get(series.uid)
    chosen_fieldmap = None if skip else fieldmap
    if chosen_fieldmap is None and previous is not None and not skip:
        chosen_fieldmap = previous.fieldmap  # an earlier fieldmap choice is kept
    keep_previous = previous is not None and not skip and (kind is None or kind == previous.kind)
    kept = previous.entities if previous is not None and keep_previous else {}
    manifest.overrides[series.uid] = Override(
        kind=kind if kind is not None else (previous.kind if keep_previous and previous else None),
        skip=skip,
        entities={**kept, **entities},  # labels of an earlier type do not carry over
        fieldmap=chosen_fieldmap,
    )
    return effective(manifest, series.uid, rules)
