"""SHA-256 of files, cached in the database by (path, size, mtime).

The cache is only trusted while size and mtime_ns are unchanged (docs/DECISIONS.md).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mrforge.models import File
from mrforge.workspace import Workspace

CHUNK = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(ws: Workspace, relpath: str) -> str:
    """Hash of a workspace file, recomputed only if its size or mtime changed."""
    path = ws.abspath(relpath)
    stat = path.stat()
    with ws.session() as s:
        row = s.scalar(select(File).where(File.relpath == relpath))
        if (
            row is not None
            and row.sha256
            and row.size == stat.st_size
            and row.mtime_ns == stat.st_mtime_ns
        ):
            return row.sha256
    digest = sha256_of(path)
    for _ in range(2):  # a parallel worker may insert the same row first
        try:
            with ws.session() as s:
                row = s.scalar(select(File).where(File.relpath == relpath))
                if row is None:
                    row = File(relpath=relpath)
                    s.add(row)
                row.sha256, row.size, row.mtime_ns = digest, stat.st_size, stat.st_mtime_ns
            break
        except IntegrityError:
            continue
    return digest
