"""Pure helpers shared by the diffusion steps (no FSL needed, unit tested).

Port of the acquisition-parameter part of ``alps.sh`` (G. Barisano, MIT; lines 286-380):

* the phase-encoding direction and total readout time come from the BIDS sidecar; on a Philips
  scanner dcm2niix cannot know the sign, so only ``PhaseEncodingAxis`` is used and the readout
  time is assumed to be 0.1 s (the script's own assumption);
* a second acquisition without a sidecar is taken to be the opposite direction with the same
  readout time;
* TOPUP is only possible when the two directions are opposite and both images start with a b = 0
  volume.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PHILIPS_READOUT_S = 0.1  # REVIEW(domain): the script's assumption for Philips scanners
VECTORS = {
    "i": "1 0 0", "i-": "-1 0 0",
    "j": "0 1 0", "j-": "0 -1 0",
    "k": "0 0 1", "k-": "0 0 -1",
}  # fmt: skip


class EncodingError(ValueError):
    """The sidecar does not say how the image was encoded."""


@dataclass(frozen=True)
class Encoding:
    direction: str  # i, i-, j, j-, k, k-
    readout_s: float
    scanner: str = ""

    @property
    def line(self) -> str:
        """One line of an FSL acquisition-parameter file."""
        return f"{VECTORS[self.direction]} {self.readout_s:g}"


def opposite(direction: str) -> str:
    return direction[:-1] if direction.endswith("-") else direction + "-"


def read_encoding(sidecar: dict[str, Any]) -> Encoding:
    """Phase-encoding direction and readout time of one image, as the script reads them."""
    scanner = str(sidecar.get("Manufacturer") or "")
    if "philips" in scanner.lower():
        direction = sidecar.get("PhaseEncodingAxis")
        readout: Any = PHILIPS_READOUT_S
    else:
        direction = sidecar.get("PhaseEncodingDirection")
        readout = sidecar.get("TotalReadoutTime")
    if direction not in VECTORS:
        key = "PhaseEncodingAxis" if "philips" in scanner.lower() else "PhaseEncodingDirection"
        raise EncodingError(f"The sidecar does not give the phase-encoding direction ({key}).")
    try:
        seconds = float(readout)
    except (TypeError, ValueError):
        raise EncodingError("The sidecar does not give the total readout time.") from None
    if seconds <= 0:
        raise EncodingError("The total readout time in the sidecar is not a positive number.")
    return Encoding(str(direction), seconds, scanner)


def reverse_encoding(
    main: Encoding, sidecar: dict[str, Any] | None, *, assume_opposite: bool
) -> Encoding:
    """Encoding of the second acquisition. Without a sidecar: opposite direction, same readout.
    ``assume_opposite`` also turns the second direction around when it is read from a sidecar
    (Philips: the axis has no sign, so two images can look alike although they are opposite)."""
    if sidecar is None:
        return Encoding(opposite(main.direction), main.readout_s, main.scanner)
    found = read_encoding(sidecar)
    if assume_opposite and found.direction == main.direction:
        return Encoding(opposite(found.direction), found.readout_s, found.scanner)
    return found


def acqparams_text(*encodings: Encoding) -> str:
    return "".join(e.line + "\n" for e in encodings)


def starts_with_b0(bval_text: str | None) -> bool:
    """Is the first volume b = 0? No b-value file counts as yes (as in the script)."""
    if bval_text is None:
        return True
    tokens = bval_text.split()
    return bool(tokens) and tokens[0].startswith("0")


def topup_problem(main: Encoding, reverse: Encoding, main_b0: bool, reverse_b0: bool) -> str | None:
    """Why TOPUP cannot be run on these two images (None: it can)."""
    if reverse.direction != opposite(main.direction):
        return (
            f"the two images were not acquired with opposite phase-encoding directions "
            f"({main.direction} and {reverse.direction})"
        )
    if not (main_b0 and reverse_b0):
        return "both images must start with a b = 0 volume"
    return None


def topup_config(n_slices: int) -> str:
    """b02b0.cnf needs an even number of slices; b02b0_1.cnf is FSL's configuration for odd."""
    return "b02b0.cnf" if n_slices % 2 == 0 else "b02b0_1.cnf"
