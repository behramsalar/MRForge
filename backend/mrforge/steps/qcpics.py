"""QC pictures drawn with FSL's ``slicer`` and ``pngappend`` (the same views FEAT shows)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mrforge.steps.base import SliceRef, StepContext

FRACTIONS = (0.35, 0.45, 0.55, 0.65)  # the same slice positions FEAT shows
SLICE_FRACTIONS = {"x": FRACTIONS, "y": FRACTIONS, "z": FRACTIONS}  # sagittal, coronal, axial


PLANES = {"x": "sagittal", "y": "coronal", "z": "axial"}


def slices_dir(ctx: StepContext[Any, Any], joined: str) -> Path:
    """Where the single slices of a joined picture are kept (next to it, named after it)."""
    return (ctx.output_dir / joined).parent / f"{Path(joined).stem}_slices"


def known_slices(ctx: StepContext[Any, Any], folder: Path, layer: str) -> list[SliceRef]:
    """The kept slices of one picture row, in reading order (those that exist)."""
    refs: list[SliceRef] = []
    for axis, fractions in SLICE_FRACTIONS.items():
        for k, fraction in enumerate(fractions):
            piece = folder / f"{layer}_{axis}{k}.png"
            if piece.is_file():
                refs.append(
                    SliceRef(
                        plane=PLANES[axis],  # type: ignore[arg-type]
                        position=fraction,
                        layer=layer,
                        path=str(piece.relative_to(ctx.output_dir)),
                    )
                )
    return refs


def slice_row(
    ctx: StepContext[Any, Any],
    base: Path,
    outline: Path,
    out: Path,
    keep: Path | None = None,
    layer: str = "",
) -> None:
    """One row of slices (sagittal, coronal, axial) of ``base`` with the edges of ``outline``
    in red, joined into ``out``. With ``keep``, the single slices stay in that folder as
    ``<layer>_<axis><n>.png``; otherwise they are removed after joining."""
    pieces: list[str] = []
    folder = keep or out.parent
    if keep:
        keep.mkdir(parents=True, exist_ok=True)
    name = layer or out.stem
    argv = ["slicer", str(base), str(outline), "-s", "2"]
    for axis, fractions in SLICE_FRACTIONS.items():
        for k, fraction in enumerate(fractions):
            piece = folder / f"{name}_{axis}{k}.png"
            argv += [f"-{axis}", f"{fraction}", str(piece)]
            pieces.append(str(piece))
    ctx.run_command(argv)
    joined = [arg for piece in pieces for arg in (piece, "+")][:-1]
    ctx.run_command(["pngappend", *joined, str(out)])
    if not keep:
        for piece_name in pieces:
            Path(piece_name).unlink(missing_ok=True)


def stack_rows(ctx: StepContext[Any, Any], rows: list[Path], out: Path) -> None:
    """Put rows of slices on top of each other."""
    joined = [arg for row in rows for arg in (str(row), "-")][:-1]
    ctx.run_command(["pngappend", *joined, str(out)])
