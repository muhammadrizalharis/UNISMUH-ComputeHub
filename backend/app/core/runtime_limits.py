"""Batas pemakaian CPU untuk proses platform (orkestrasi).

Tujuan: server dipakai bersama banyak user. Proses platform ini HARUS ringan
& "mengalah" — tidak boleh membebani CPU sehingga mengganggu user lain.

Diterapkan sekali saat startup:
  1. Plafon thread BLAS/OpenMP/torch (env vars) — cegah komputasi multi-core
     tak sengaja (mis. numpy/torch yang ter-import).
  2. `nice` tinggi — kernel hanya memberi CPU saat core idle.
  3. (Opsional) CPU affinity — kurung proses ke sebagian core saja.
"""

from __future__ import annotations

import os

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def _parse_affinity(spec: str) -> list[int]:
    """Parse "0-3,6" -> [0,1,2,3,6]."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            try:
                out.update(range(int(lo), int(hi) + 1))
            except ValueError:
                continue
        else:
            try:
                out.add(int(part))
            except ValueError:
                continue
    return sorted(out)


def apply_cpu_limits() -> None:
    """Terapkan plafon thread + nice + affinity ke proses saat ini."""
    threads = max(1, int(settings.PLATFORM_CPU_THREADS))
    for var in _THREAD_ENV_VARS:
        os.environ.setdefault(var, str(threads))

    # Coba batasi thread torch bila kebetulan sudah ter-import.
    try:  # pragma: no cover
        import sys

        torch = sys.modules.get("torch")
        if torch is not None:
            torch.set_num_threads(threads)
    except Exception:  # noqa: BLE001
        pass

    nice_val = None
    affinity = None
    try:
        import psutil

        proc = psutil.Process()

        nice_target = int(settings.PLATFORM_NICE)
        if nice_target:
            try:
                proc.nice(nice_target)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Gagal set nice: %s", exc)
        nice_val = proc.nice()

        aff = _parse_affinity(settings.PLATFORM_CPU_AFFINITY)
        if aff and hasattr(proc, "cpu_affinity"):
            try:
                proc.cpu_affinity(aff)
                affinity = proc.cpu_affinity()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Gagal set CPU affinity: %s", exc)
    except Exception as exc:  # noqa: BLE001
        # Fallback: minimal pakai os.nice.
        try:
            os.nice(max(0, int(settings.PLATFORM_NICE)))
        except Exception:  # noqa: BLE001
            pass
        logger.debug("psutil tidak tersedia untuk batas CPU: %s", exc)

    logger.info(
        "Batas CPU platform aktif: nice=%s, threads<=%s, affinity=%s",
        nice_val if nice_val is not None else settings.PLATFORM_NICE,
        threads,
        affinity or "semua core",
    )
