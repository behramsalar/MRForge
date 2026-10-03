"""Data models for importing. None of these hold patient names, IDs, dates or file paths
that could identify a person: only acquisition parameters and counts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class SeriesOutput(BaseModel):
    """One image that dcm2niix would write for a series (a series can hold several echoes, or
    a magnitude and a phase image). ``suffix`` is dcm2niix's own tag: '', 'e1', 'e2_ph', ..."""

    suffix: str = ""
    echo_number: int | None = None
    echo_time_s: float | None = None
    repetition_time_s: float | None = None
    image_type: list[str] = []
    phase_encoding_direction: str | None = None  # BIDS style with sign: i, i-, j, j-, k, k-
    total_readout_time_s: float | None = None
    effective_echo_spacing_s: float | None = None


class DicomSeries(BaseModel):
    uid: str  # SeriesInstanceUID (identifies the series across repeated imports)
    number: int | None = None
    description: str = ""
    protocol: str = ""
    sequence_name: str | None = None
    modality: str = ""
    image_type: list[str] = []  # from the DICOM header, e.g. ORIGINAL, PRIMARY, FMRI, NONE
    multiframe: bool = False  # enhanced DICOM: one file holds all slices of one volume
    rows: int | None = None
    columns: int | None = None
    slices: int | None = None  # slices per volume
    volumes: int | None = None  # 3D volumes per image (time points / diffusion directions)
    n_files: int = 0
    repetition_time_s: float | None = None
    echo_time_s: float | None = None
    flip_angle_deg: float | None = None
    slice_thickness_mm: float | None = None
    phase_encoding_direction: str | None = None
    outputs: list[SeriesOutput] = []
    warnings: list[str] = []

    @property
    def matrix(self) -> str:
        """Columns x rows x slices, the way NIfTI and dcm2niix write the image size."""
        dims = [self.columns, self.rows, self.slices]
        return "x".join("?" if d is None else str(d) for d in dims)


Confidence = Literal["High", "Medium", "Low"]
Action = Literal["import", "skip", "ask"]


class Classification(BaseModel):
    """What the rules (or the user) decided a series is, and why."""

    kind: str  # T1w, T2w, bold, dwi, fieldmap-magnitude, fieldmap-phase, localizer, ...
    action: Action  # import, skip, or ask (needs your input; not imported until decided)
    confidence: Confidence
    datatype: str | None = None  # BIDS folder: anat, func, fmap, dwi
    suffix: str | None = None  # BIDS suffix: T1w, bold, magnitude, ...
    entities: dict[str, str] = {}  # e.g. {"task": "rest"}
    needs: list[str] = []  # what is missing before it can be imported, e.g. ["task"]
    reasons: list[str] = []  # plain-language clues, shown to the user
    rule_ids: list[str] = []
    source: Literal["rules", "user"] = "rules"


class Override(BaseModel):
    """A decision the user made for one series (kept separate so re-running the rules never
    loses it)."""

    kind: str | None = None  # a kind from the rules table; None keeps the rules' kind
    skip: bool = False
    entities: dict[str, str] = {}
    decided: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SkippedFile(BaseModel):
    name: str  # file name only (never the folder path)
    reason: str


class SourceInfo(BaseModel):
    name: str  # the folder or ZIP name as given by the user
    kind: Literal["folder", "zip"]
    n_files: int
    fingerprint: str  # hash of the file names and sizes; recognises the same source again


class CommandRecord(BaseModel):
    argv: list[str]  # the input folder is shown as <dicom>, the scratch folder as <scratch>
    return_code: int


class ImportManifest(BaseModel):
    """What was scanned, what the user decided, and how it was converted."""

    schema_version: int = 1
    id: str  # "import-001"
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: SourceInfo
    dicom_dir: str  # workspace-relative folder under sourcedata/dicom/
    subject: str  # e.g. "sub-001"
    session: str | None = None
    series: list[DicomSeries] = []
    classifications: dict[str, Classification] = {}  # by series uid (from the rules)
    overrides: dict[str, Override] = {}  # by series uid (from the user)
    skipped_files: list[SkippedFile] = []
    tool_versions: dict[str, str] = {}
    commands: list[CommandRecord] = []
    warnings: list[str] = []
