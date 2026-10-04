"""QC pictures drawn with FSL's ``slicer`` and ``pngappend`` (the same views FEAT shows)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mrforge.steps.base import StepContext

FRACTIONS = (0.35, 0.45, 0.55, 0.65)  # the same slice positions FEAT shows
SLICE_FRACTIONS = {"x": FRACTIONS, "y": FRACTIONS, "z": FRACTIONS}  # sagittal, coronal, axial


def slice_row(ctx: StepContext[Any, Any], base: Path, outline: Path, out: Path) -> None:
    """One row of slices (sagittal, coronal, axial) of ``base`` with the edges of ``outline``
    in red. The single slices are written next to ``out`` and joined into it."""
    pieces: list[str] = []
    argv = ["slicer", str(base), str(outline), "-s", "2"]
    for axis, fractions in SLICE_FRACTIONS.items():
        for k, fraction in enumerate(fractions):
            piece = out.with_name(f"{out.stem}_{axis}{k}.png")
            argv += [f"-{axis}", f"{fraction}", str(piece)]
            pieces.append(str(piece))
    ctx.run_command(argv)
    joined = [arg for piece in pieces for arg in (piece, "+")][:-1]
    ctx.run_command(["pngappend", *joined, str(out)])
    for name in pieces:
        Path(name).unlink(missing_ok=True)


def stack_rows(ctx: StepContext[Any, Any], rows: list[Path], out: Path) -> None:
    """Put rows of slices on top of each other."""
    joined = [arg for row in rows for arg in (str(row), "-")][:-1]
    ctx.run_command(["pngappend", *joined, str(out)])
