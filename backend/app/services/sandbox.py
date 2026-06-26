"""Batas resource keras (rlimit) untuk subprocess job & kernel — mitigasi DoS non-root.

Dipakai sebagai `preexec_fn` saat spawn subprocess: fungsi ini berjalan di proses
ANAK setelah fork dan sebelum exec, sehingga batasnya berlaku untuk kode user
(dan diwariskan ke anak-anaknya).

CATATAN PENTING: SENGAJA TIDAK menyetel RLIMIT_AS / RLIMIT_DATA (memori virtual)
karena CUDA/PyTorch mereservasi address space sangat besar — membatasinya akan
membuat job GPU crash. Plafon memori ditegakkan terpisah lewat sampler (advisory).
Tujuan modul ini: mencegah fork bomb, core dump, dan file raksasa memenuhi disk.
"""

from __future__ import annotations

import resource

from app.core.config import settings


def _set(res: int, value: int) -> None:
    """Pasang soft=hard=value; abaikan bila tak didukung / melebihi hard limit."""
    try:
        resource.setrlimit(res, (value, value))
    except (ValueError, OSError):
        # Jangan gagalkan job hanya karena satu limit tak bisa dipasang.
        pass


def apply_rlimits() -> None:
    """preexec_fn: pasang batas proses/file/core untuk kode user."""
    if settings.JOB_RLIMIT_NO_CORE:
        _set(resource.RLIMIT_CORE, 0)
    if settings.JOB_RLIMIT_NPROC > 0:
        _set(resource.RLIMIT_NPROC, settings.JOB_RLIMIT_NPROC)
    if settings.JOB_RLIMIT_FSIZE_MB > 0:
        _set(resource.RLIMIT_FSIZE, settings.JOB_RLIMIT_FSIZE_MB * 1024 * 1024)
    if settings.JOB_RLIMIT_NOFILE > 0:
        _set(resource.RLIMIT_NOFILE, settings.JOB_RLIMIT_NOFILE)
