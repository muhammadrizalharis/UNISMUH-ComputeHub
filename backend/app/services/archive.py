"""Validasi & ekstraksi arsip project (ZIP) yang diupload mahasiswa.

Keamanan:
  - Batas ukuran arsip & ukuran hasil ekstrak (anti zip-bomb).
  - Batas jumlah file.
  - Cegah path traversal / zip-slip (entri di luar folder tujuan ditolak).
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MB = 1024 * 1024


def validate_zip(path: Path) -> str | None:
    """Periksa arsip ZIP. Kembalikan pesan error, atau None bila aman."""
    if not zipfile.is_zipfile(path):
        return "File bukan ZIP yang valid."
    try:
        with zipfile.ZipFile(path) as zf:
            members = zf.infolist()
            if len(members) > settings.MAX_UPLOAD_FILES:
                return f"Terlalu banyak file (> {settings.MAX_UPLOAD_FILES})."
            total = sum(m.file_size for m in members)
            if total > settings.MAX_UPLOAD_UNCOMPRESSED_MB * _MB:
                return (
                    f"Ukuran setelah ekstrak melebihi "
                    f"{settings.MAX_UPLOAD_UNCOMPRESSED_MB} MB."
                )
            for m in members:
                name = m.filename
                if name.startswith("/") or ".." in Path(name).parts:
                    return f"Entri arsip tidak aman: {name}"
    except zipfile.BadZipFile:
        return "Arsip ZIP rusak."
    return None


def safe_extract(archive: Path, dest: Path, log: BinaryIO) -> bool:
    """Ekstrak `archive` ke `dest` dengan aman. True bila sukses."""
    if not archive.exists():
        log.write(b"[UPLOAD] arsip tidak ditemukan.\n")
        log.flush()
        return False

    err = validate_zip(archive)
    if err:
        log.write(f"[UPLOAD] Ditolak: {err}\n".encode())
        log.flush()
        return False

    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                target = (dest / member.filename).resolve()
                if not str(target).startswith(str(dest_root)):
                    log.write(
                        f"[UPLOAD] Tolak (zip-slip): {member.filename}\n".encode()
                    )
                    log.flush()
                    return False
            zf.extractall(dest)
        log.write(b"[UPLOAD] Ekstrak project selesai.\n")
        log.flush()
        return True
    except Exception as exc:  # noqa: BLE001
        log.write(f"[UPLOAD] Gagal ekstrak: {exc!r}\n".encode())
        log.flush()
        return False
