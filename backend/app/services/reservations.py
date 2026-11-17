"""Registry klaim GPU (VRAM-aware) yang dipakai bersama scheduler & interactive.

Dulu cuma menandai "GPU X dipakai" (boolean) -> 1 beban kerja per GPU. Sekarang
setiap klaim membawa *anggaran VRAM* (budget_mb) sehingga BANYAK beban kerja
(job batch + sesi interaktif) bisa BERBAGI satu GPU selama total anggaran masih
muat (lihat gpu.pick_gpu_for). Proses tunggal (asyncio 1-thread) -> dict biasa
sudah cukup, tak perlu lock antar-thread.

Setiap klaim diidentifikasi `claim_id` unik:
  - sesi interaktif -> session.id (hex uuid)
  - job batch       -> f"job:{job_id}"

Mode GPU_COUNT_ACTUAL_USAGE (default): slot & anggaran dihitung dari VRAM NYATA.
Klaim yang memegang GPU tapi belum memakai VRAM (devbox/notebook diam) tidak
menghabiskan slot, kecuali masih dalam masa tenggang (baru masuk, belum alokasi)
atau eksklusif (job 2 GPU).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.core.config import settings


@dataclass
class _Claim:
    gpu_index: int
    budget_mb: float       # VRAM yang dipesan (plafon yang ditegakkan)
    used_mb: float = 0.0   # VRAM nyata terakhir (diperbarui monitor; untuk tampilan)
    kind: str = "interactive"  # "interactive" | "job"
    exclusive: bool = False    # job 2 GPU: GPU tertutup utk beban kerja lain
    created: float = field(default_factory=time.monotonic)


# claim_id -> _Claim
_claims: dict[str, _Claim] = {}


def _changed() -> None:
    # Kantong VRAM menyesuaikan target segera (lepas duluan utk penghuni baru).
    try:
        from app.services import vram_pocket

        vram_pocket.on_claims_changed()
    except Exception:  # noqa: BLE001 — registry tak boleh gagal karena kantong
        pass


def reserve(
    claim_id: str,
    gpu_index: int,
    budget_mb: float,
    kind: str = "interactive",
    exclusive: bool = False,
) -> None:
    """Catat klaim VRAM `budget_mb` pada `gpu_index`. Idempoten per claim_id."""
    _claims[claim_id] = _Claim(
        gpu_index=int(gpu_index),
        budget_mb=max(0.0, float(budget_mb or 0.0)),
        kind=kind,
        exclusive=exclusive,
    )
    _changed()


def release(claim_id: str) -> None:
    """Lepas klaim (GPU sebagian/seluruhnya bebas kembali)."""
    if _claims.pop(claim_id, None) is not None:
        _changed()


def _actual_mode() -> bool:
    return bool(settings.GPU_COUNT_ACTUAL_USAGE)


def _in_grace(c: _Claim, now: float) -> bool:
    return (now - c.created) < float(settings.GPU_CLAIM_GRACE_SECONDS)


def _is_active(c: _Claim, now: float) -> bool:
    """Apakah klaim dihitung menempati slot GPU."""
    if not _actual_mode() or c.exclusive:
        return True
    return c.used_mb > 0 or _in_grace(c, now)


def _weight_mb(c: _Claim) -> float:
    if not _actual_mode() or c.exclusive:
        return max(c.budget_mb, c.used_mb)
    return c.used_mb


def update_usage(claim_id: str, used_mb: float) -> None:
    """Perbarui VRAM nyata sebuah klaim (dipanggil sampler) — untuk tampilan."""
    claim = _claims.get(claim_id)
    if claim is not None:
        claim.used_mb = max(0.0, float(used_mb or 0.0))


def planned_mb(gpu_index: int) -> float:
    """Total VRAM yang DIPESAN platform di sebuah GPU.

    Mode lama: max(anggaran, nyata) per klaim (konservatif). Mode pemakaian nyata:
    VRAM yang benar-benar dipakai (klaim eksklusif tetap penuh).
    """
    return sum(_weight_mb(c) for c in _claims.values() if c.gpu_index == gpu_index)


def count(gpu_index: int) -> int:
    """Jumlah beban kerja platform yang menempati slot sebuah GPU."""
    now = time.monotonic()
    return sum(
        1 for c in _claims.values() if c.gpu_index == gpu_index and _is_active(c, now)
    )


def holders(gpu_index: int) -> int:
    """Jumlah klaim yang memegang GPU, aktif maupun diam."""
    return sum(1 for c in _claims.values() if c.gpu_index == gpu_index)


def used_mb(gpu_index: int) -> float:
    """VRAM nyata total beban kerja ComputeHub di sebuah GPU (dari sampler)."""
    return sum(c.used_mb for c in _claims.values() if c.gpu_index == gpu_index)


def has_exclusive(gpu_index: int) -> bool:
    return any(c.exclusive and c.gpu_index == gpu_index for c in _claims.values())


def reserved_indices() -> set[int]:
    """Set indeks GPU yang sedang dipegang minimal satu klaim (kompat lama)."""
    return {c.gpu_index for c in _claims.values()}


def per_gpu_summary() -> dict[int, dict]:
    """Ringkasan per-GPU (untuk monitoring admin): jumlah klaim + VRAM dipesan/nyata."""
    out: dict[int, dict] = {}
    now = time.monotonic()
    for c in _claims.values():
        s = out.setdefault(
            c.gpu_index,
            {"count": 0, "active": 0, "reserved_mb": 0.0, "used_mb": 0.0},
        )
        s["count"] += 1
        s["active"] += 1 if _is_active(c, now) else 0
        s["reserved_mb"] += c.budget_mb
        s["used_mb"] += c.used_mb
    return out
