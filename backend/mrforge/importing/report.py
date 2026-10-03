"""Plain-text tables of an import manifest (used by the CLI)."""

from __future__ import annotations

from mrforge.importing.models import Classification, Conversion, DicomSeries, ImportManifest


def _fmt(value: float | None, scale: float = 1.0, digits: int = 1) -> str:
    return "-" if value is None else f"{value * scale:.{digits}f}".rstrip("0").rstrip(".")


def describe_plan(c: Classification) -> str:
    """What will happen to a series, in a few words."""
    if c.action == "skip":
        return f"skip ({c.kind})"
    if c.action == "ask":
        if c.needs:
            return f"{c.datatype}/{c.suffix} - NEEDS {', '.join(c.needs)}"
        return "NEEDS YOUR DECISION"
    labels = "".join(f" {k}-{v}" for k, v in c.entities.items())
    return f"import as {c.datatype}/{c.suffix}{labels}"


def _converted(s: DicomSeries, conversions: dict[str, Conversion]) -> str:
    done = conversions.get(s.uid)
    return "-" if done is None else ("yes" if done.status == "ok" else "FAILED")


def _row(
    s: DicomSeries, c: Classification | None, conversions: dict[str, Conversion] | None = None
) -> list[str]:
    kind = "/".join(t for t in s.image_type[2:4] if t) or "-"
    row = [
        "?" if s.number is None else str(s.number),
        s.description or "-",
        kind,
        str(s.n_files),
        s.matrix,
        "-" if s.volumes is None else str(s.volumes),
        _fmt(s.repetition_time_s, 1, 2),
        _fmt(s.echo_time_s, 1000, 1),
        s.phase_encoding_direction or "-",
    ]
    if c is not None:
        row += [describe_plan(c), c.confidence + (" (you)" if c.source == "user" else "")]
    if conversions:
        row.append(_converted(s, conversions))
    return row


HEADER = ["SERIES", "DESCRIPTION", "KIND", "FILES", "MATRIX", "VOLS", "TR(s)", "TE(ms)", "PE"]
CLASS_HEADER = ["WILL BE", "SURE"]


def format_series_table(
    manifest: ImportManifest, classes: dict[str, Classification] | None = None
) -> str:
    header = HEADER + (CLASS_HEADER if classes is not None else [])
    if manifest.conversions:
        header = header + ["CONVERTED"]
    rows = [header] + [
        _row(s, classes.get(s.uid) if classes else None, manifest.conversions)
        for s in manifest.series
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in rows]
    return "\n".join(lines)


def _needs_hint(s: DicomSeries, c: Classification) -> str:
    number = "?" if s.number is None else s.number
    if "task" in c.needs:
        return f"mrforge import set {number} --task <name>      (what task was done?)"
    return f"mrforge import set {number} --type <type> | --skip   (what is this series?)"


def format_manifest(
    manifest: ImportManifest,
    classes: dict[str, Classification] | None = None,
    why: bool = False,
) -> str:
    where = manifest.subject + (f"/{manifest.session}" if manifest.session else "")
    lines = [
        f"{manifest.id}: {manifest.source.kind} '{manifest.source.name}', "
        f"{manifest.source.n_files} files, {len(manifest.series)} series, as {where}",
        "",
        format_series_table(manifest, classes),
    ]
    if classes is not None:
        counts = {"import": 0, "skip": 0, "ask": 0}
        for c in classes.values():
            counts[c.action] += 1
        lines += [
            "",
            f"{counts['import']} to import, {counts['skip']} skipped, "
            f"{counts['ask']} need your input.",
        ]
        asking = [(s, classes[s.uid]) for s in manifest.series if classes[s.uid].action == "ask"]
        if asking:
            lines += ["", "Needs your input (these are NOT imported until you decide):"]
            lines += [f"  {_needs_hint(s, c)}" for s, c in asking]
        medium = [(s, c) for s, c in ((s, classes[s.uid]) for s in manifest.series)
                  if c.confidence == "Medium" and c.action != "ask"]  # fmt: skip
        if medium:
            lines += ["", "Please check (medium confidence):"]
            lines += [f"  series {s.number}: {c.reasons[0]}" for s, c in medium]
        if why:
            lines += ["", "Why:"]
            for s in manifest.series:
                lines.append(f"  series {s.number} ({s.description}):")
                lines += [f"    - {r}" for r in classes[s.uid].reasons]
    notes = [f"series {s.number}: {w}" for s in manifest.series for w in s.warnings]
    notes += manifest.warnings
    if manifest.skipped_files:
        counts2: dict[str, int] = {}
        for skipped in manifest.skipped_files:
            counts2[skipped.reason] = counts2.get(skipped.reason, 0) + 1
        notes += [f"{n} file(s) skipped: {reason}" for reason, n in counts2.items()]
    if notes:
        lines += ["", "Notes:"] + [f"  - {n}" for n in notes]
    return "\n".join(lines)
