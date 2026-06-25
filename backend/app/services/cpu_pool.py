"""Kolam core CPU bersama (mirror reservations.py untuk GPU).

Tujuan: izinkan komputasi CPU (mis. Random Forest/ML klasik) TAPI dengan batas
nyata — tiap job/sesi dipesan sejumlah core dari kolam dan di-`cpu_affinity`-kan
ke core itu. Bila kolam penuh, job MASUK ANTRIAN (scheduler menahan di `queued`).

Kenapa affinity (bukan cuma OMP_NUM_THREADS): joblib `n_jobs=-1` men-spawn banyak
PROSES yang TIDAK dibatasi OMP. Dengan mengunci affinity pada proses utama, semua
anak proses mewarisi mask yang sama -> total core benar-benar terbatas (server
bersama aman, satu user tak bisa menyedot semua core).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _nproc() -> int:
    try:
        return os.cpu_count() or 1
    except Exception:  # noqa: BLE001
        return 1


def _assignable_cores() -> list[int]:
    """Daftar index core yang boleh dipakai job platform.

    Selalu menyisakan core indeks rendah untuk OS + user server lain.
    - CPU_POOL_CORES > 0  -> pakai N core teratas: [nproc-N .. nproc-1].
    - CPU_POOL_CORES = 0  -> pakai [CPU_RESERVED_CORES .. nproc-1].
    """
    nproc = _nproc()
    pool = int(settings.CPU_POOL_CORES or 0)
    if pool > 0:
        size = max(1, min(pool, nproc))
        return list(range(nproc - size, nproc))
    reserved = max(0, min(int(settings.CPU_RESERVED_CORES or 0), nproc - 1))
    return list(range(reserved, nproc))


@dataclass
class _Claim:
    cores: list[int]
    kind: str = "job"


_lock = threading.Lock()
_claims: dict[str, _Claim] = {}
_free: set[int] | None = None  # diisi malas saat pertama dipakai


def _ensure_free() -> set[int]:
    global _free
    if _free is None:
        _free = set(_assignable_cores())
    return _free


def total_cores() -> int:
    return len(_assignable_cores())


def used_cores() -> int:
    with _lock:
        _ensure_free()
        return sum(len(c.cores) for c in _claims.values())


def available_cores() -> int:
    with _lock:
        return len(_ensure_free())


def reserve(claim_id: str, n: int, kind: str = "job") -> list[int] | None:
    """Pesan `n` core untuk `claim_id`. Kembalikan daftar core, atau None bila penuh.

    Idempoten: bila claim sudah ada, kembalikan core yang sama.
    """
    n = max(1, int(n))
    with _lock:
        free = _ensure_free()
        existing = _claims.get(claim_id)
        if existing is not None:
            return list(existing.cores)
        # Jangan pernah minta lebih dari kapasitas kolam.
        n = min(n, total_cores())
        if len(free) < n:
            return None
        chosen = sorted(free)[:n]
        for c in chosen:
            free.discard(c)
        _claims[claim_id] = _Claim(cores=chosen, kind=kind)
        return list(chosen)


def release(claim_id: str) -> None:
    with _lock:
        claim = _claims.pop(claim_id, None)
        if claim is None:
            return
        free = _ensure_free()
        for c in claim.cores:
            free.add(c)


def can_fit(n: int) -> bool:
    """True bila `n` core bisa dipesan sekarang."""
    n = max(1, min(int(n), total_cores()))
    return available_cores() >= n


def is_full() -> bool:
    return available_cores() <= 0


def summary() -> dict:
    total = total_cores()
    used = used_cores()
    return {
        "total": total,
        "used": used,
        "free": max(0, total - used),
        "full": (total - used) <= 0,
    }


def pin_process(pid: int, cores: list[int]) -> bool:
    """Kunci proses (dan anak-anak yang mewarisi) ke daftar core. Best-effort."""
    if not cores:
        return False
    try:
        os.sched_setaffinity(pid, set(cores))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gagal set cpu_affinity pid=%s cores=%s: %s", pid, cores, exc)
        return False


def reset() -> None:
    """Kosongkan semua klaim (dipanggil saat shutdown)."""
    global _free
    with _lock:
        _claims.clear()
        _free = None
