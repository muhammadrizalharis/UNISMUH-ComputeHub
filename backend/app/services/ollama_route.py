"""Pilih instance Ollama per-GPU dengan VRAM kosong terbanyak.

Latar: port 11434 di server adalah load balancer (least_conn) ke dua instance Ollama
yang masing-masing dipatok ke satu GPU. Bila GPU itu sedang penuh, Ollama memuat model
di CPU -> jawaban bisa makan beberapa menit dan membebani CPU server bersama.
ComputeHub memilih sendiri instance di GPU yang paling lega. Tanpa setelan
`OLLAMA_GPU_BACKENDS` atau saat gagal baca GPU -> URL bawaan (perilaku lama).
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.services import gpu as gpu_svc

logger = get_logger(__name__)


def backends() -> dict[int, str]:
    """Parse `OLLAMA_GPU_BACKENDS` ("0=http://..:11435,1=http://..:11436")."""
    out: dict[int, str] = {}
    for part in (settings.OLLAMA_GPU_BACKENDS or "").split(","):
        idx, sep, url = part.strip().partition("=")
        if not sep:
            continue
        try:
            out[int(idx.strip())] = url.strip().rstrip("/")
        except ValueError:
            continue
    return {k: v for k, v in out.items() if v}


def pick_base(default: str) -> str:
    """Base URL Ollama (tanpa /v1) di GPU dengan VRAM kosong terbanyak."""
    default = default.rstrip("/")
    peta = backends()
    if not peta:
        return default
    try:
        bebas = {g.index: g.mem_free_mb for g in gpu_svc.list_all_gpus() if g.index in peta}
    except Exception as exc:  # noqa: BLE001
        logger.debug("ollama_route: baca GPU gagal: %r", exc)
        return default
    if not bebas:
        return default
    terpilih = max(bebas, key=lambda i: bebas[i])
    return peta[terpilih]
