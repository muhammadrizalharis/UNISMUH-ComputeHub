"""Registry klaim GPU (VRAM-aware) yang dipakai bersama scheduler & interactive.

Dulu cuma menandai "GPU X dipakai" (boolean) -> 1 beban kerja per GPU. Sekarang
setiap klaim membawa *anggaran VRAM* (budget_mb) sehingga BANYAK beban kerja
(job batch + sesi interaktif) bisa BERBAGI satu GPU selama total anggaran masih
muat (lihat gpu.pick_gpu_for). Proses tunggal (asyncio 1-thread) -> dict biasa
sudah cukup, tak perlu lock antar-thread.

Setiap klaim diidentifikasi `claim_id` unik:
  - sesi interaktif -> session.id (hex uuid)
  - job batch       -> f"job:{job_id}"
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Claim:
    gpu_index: int
    budget_mb: float       # VRAM yang dipesan (plafon yang ditegakkan)
    used_mb: float = 0.0   # VRAM nyata terakhir (diperbarui monitor; untuk tampilan)
    kind: str = "interactive"  # "interactive" | "job"


# claim_id -> _Claim
_claims: dict[str, _Claim] = {}


def reserve(claim_id: str, gpu_index: int, budget_mb: float, kind: str = "interactive") -> None:
    """Catat klaim VRAM `budget_mb` pada `gpu_index`. Idempoten per claim_id."""
    _claims[claim_id] = _Claim(
        gpu_index=int(gpu_index),
        budget_mb=max(0.0, float(budget_mb or 0.0)),
        kind=kind,
    )


def release(claim_id: str) -> None:
    """Lepas klaim (GPU sebagian/seluruhnya bebas kembali)."""
    _claims.pop(claim_id, None)


def update_usage(claim_id: str, used_mb: float) -> None:
    """Perbarui VRAM nyata sebuah klaim (dipanggil sampler) — untuk tampilan."""
    claim = _claims.get(claim_id)
    if claim is not None:
        claim.used_mb = max(0.0, float(used_mb or 0.0))


def planned_mb(gpu_index: int) -> float:
    """Total VRAM yang DIPESAN platform di sebuah GPU.

    Konservatif: pakai max(anggaran, nyata) per klaim supaya tidak overcommit
    (klaim yang belum sempat alokasi tetap dihitung penuh; klaim yang melebihi
    anggaran — mestinya ke-kill — tetap dihitung apa adanya).
    """
    return sum(
        max(c.budget_mb, c.used_mb)
        for c in _claims.values()
        if c.gpu_index == gpu_index
    )


def count(gpu_index: int) -> int:
    """Jumlah beban kerja platform yang memegang sebuah GPU."""
    return sum(1 for c in _claims.values() if c.gpu_index == gpu_index)


def reserved_indices() -> set[int]:
    """Set indeks GPU yang sedang dipegang minimal satu klaim (kompat lama)."""
    return {c.gpu_index for c in _claims.values()}


def per_gpu_summary() -> dict[int, dict]:
    """Ringkasan per-GPU (untuk monitoring admin): jumlah klaim + VRAM dipesan/nyata."""
    out: dict[int, dict] = {}
    for c in _claims.values():
        s = out.setdefault(
            c.gpu_index, {"count": 0, "reserved_mb": 0.0, "used_mb": 0.0}
        )
        s["count"] += 1
        s["reserved_mb"] += c.budget_mb
        s["used_mb"] += c.used_mb
    return out
