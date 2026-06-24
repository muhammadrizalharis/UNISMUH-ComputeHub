"""Registry GPU yang dipakai sesi INTERAKTIF (kernel hidup).

Dipakai bersama oleh scheduler (agar job batch tidak memakai GPU yang sedang
dipegang sesi interaktif) dan oleh interactive manager. Proses tunggal (asyncio)
sehingga dict biasa sudah cukup; tidak perlu lock antar-thread.
"""

from __future__ import annotations

# gpu_index -> jumlah sesi yang memegangnya (umumnya 1).
_reserved: dict[int, int] = {}


def reserve(gpu_index: int) -> None:
    _reserved[gpu_index] = _reserved.get(gpu_index, 0) + 1


def release(gpu_index: int) -> None:
    remaining = _reserved.get(gpu_index, 0) - 1
    if remaining <= 0:
        _reserved.pop(gpu_index, None)
    else:
        _reserved[gpu_index] = remaining


def reserved_indices() -> set[int]:
    """Set indeks GPU yang sedang dipegang sesi interaktif."""
    return set(_reserved.keys())
