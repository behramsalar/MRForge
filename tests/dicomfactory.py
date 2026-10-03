"""Build tiny synthetic DICOM files for tests (headers are realistic, images are 2x2 pixels)."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

MR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.4"
ENHANCED_MR = "1.2.840.10008.5.1.4.1.1.4.1"
DICOMDIR_CLASS = "1.2.840.10008.1.3.10"

# Identifying values that must never appear anywhere in what MRForge stores or prints.
SECRET_NAME = "Zzyzx^Quentin"
SECRET_ID = "PATIENT-ID-424242"
SECRET_DATE = "19570321"


def make_dicom(
    path: Path,
    series_uid: str,
    series_number: int,
    description: str = "t1w",
    protocol: str | None = None,
    image_type: tuple[str, ...] = ("ORIGINAL", "PRIMARY", "M", "NONE"),
    position_z: float | None = 0.0,
    frames: int | None = None,
    rows: int = 4,
    columns: int = 4,
    tr_ms: float = 2000.0,
    te_ms: float = 30.0,
    sop_class: str = MR_IMAGE_STORAGE,
) -> Path:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.SeriesDescription = description
    ds.ProtocolName = protocol or description
    ds.ImageType = list(image_type)
    ds.Modality = "MR"
    ds.Rows, ds.Columns = rows, columns
    ds.RepetitionTime = tr_ms
    ds.EchoTime = te_ms
    ds.SliceThickness = 3.0
    if position_z is not None:
        ds.ImagePositionPatient = [0.0, 0.0, position_z]
    if frames is not None:
        ds.NumberOfFrames = frames
    # the identifying part of a real header
    ds.PatientName = SECRET_NAME
    ds.PatientID = SECRET_ID
    ds.PatientBirthDate = SECRET_DATE
    ds.StudyDate = SECRET_DATE
    ds.InstitutionName = "Secret Hospital"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
    ds.SamplesPerPixel, ds.PhotometricInterpretation, ds.PixelRepresentation = 1, "MONOCHROME2", 0
    ds.PixelData = np.zeros((rows, columns), dtype=np.uint16).tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), enforce_file_format=True)
    return path


def new_uid() -> str:
    return f"1.2.826.0.1.{uuid.uuid4().int % 10**20}"


def make_session(root: Path) -> dict[str, str]:
    """A small session: a 3-slice classic T1, a 3-slice x 4-volume classic BOLD run, and an
    enhanced (multi-frame) BOLD run of 5 volumes with 8 slices. Files of the two classic series
    are interleaved in one folder. Returns {name: series uid}."""
    uids = {"t1": new_uid(), "bold": new_uid(), "enh": new_uid()}
    for z in range(3):
        make_dicom(root / "mixed" / f"t1_{z}.dcm", uids["t1"], 2, "t1w", position_z=float(z))
    for vol in range(4):
        for z in range(3):
            make_dicom(
                root / "mixed" / f"bold_{vol}_{z}.dcm",
                uids["bold"],
                6,
                "resting",
                image_type=("ORIGINAL", "PRIMARY", "FMRI", "NONE"),
                position_z=float(z),
            )
    for vol in range(5):
        make_dicom(
            root / "enhanced" / f"vol_{vol}",  # no extension, like many scanner exports
            uids["enh"],
            19,
            "ep2d_bold_moco_p2",
            image_type=("ORIGINAL", "PRIMARY", "FMRI", "NONE"),
            position_z=None,
            frames=8,
            sop_class=ENHANCED_MR,
        )
    return uids
