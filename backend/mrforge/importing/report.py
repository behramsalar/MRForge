"""Plain-text tables of an import manifest (used by the CLI)."""

from __future__ import annotations

from mrforge.importing.models import DicomSeries, ImportManifest


def _fmt(value: float | None, scale: float = 1.0, digits: int = 1) -> str:
    return "-" if value is None else f"{value * scale:.{digits}f}".rstrip("0").rstrip(".")


def _row(s: DicomSeries) -> list[str]:
    kind = "/".join(t for t in s.image_type[2:4] if t) or "-"
    return [
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


HEADER = ["SERIES", "DESCRIPTION", "KIND", "FILES", "MATRIX", "VOLS", "TR(s)", "TE(ms)", "PE"]


def format_series_table(manifest: ImportManifest) -> str:
    rows = [HEADER] + [_row(s) for s in manifest.series]
    widths = [max(len(r[i]) for r in rows) for i in range(len(HEADER))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in rows]
    return "\n".join(lines)


def format_manifest(manifest: ImportManifest) -> str:
    where = manifest.subject + (f"/{manifest.session}" if manifest.session else "")
    lines = [
        f"{manifest.id}: {manifest.source.kind} '{manifest.source.name}', "
        f"{manifest.source.n_files} files, {len(manifest.series)} series, as {where}",
        "",
        format_series_table(manifest),
    ]
    notes = [f"series {s.number}: {w}" for s in manifest.series for w in s.warnings]
    notes += manifest.warnings
    if manifest.skipped_files:
        counts: dict[str, int] = {}
        for skipped in manifest.skipped_files:
            counts[skipped.reason] = counts.get(skipped.reason, 0) + 1
        notes += [f"{n} file(s) skipped: {reason}" for reason, n in counts.items()]
    if notes:
        lines += ["", "Notes:"] + [f"  - {n}" for n in notes]
    return "\n".join(lines)
