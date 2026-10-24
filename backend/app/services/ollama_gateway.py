"""Gerbang Ollama: autentikasi kunci API + batas laju/konkurensi + proxy ke Ollama.

Alur: klien (CLI/aplikasi teman) kirim `Authorization: Bearer ch-ollama-...`.
Gerbang memverifikasi kunci (hash), mengecek model yang diizinkan, menerapkan batas
laju & konkurensi per-kunci (in-memory; backend 1 worker), lalu meneruskan ke Ollama
lokal. Endpoint berbahaya (pull/push/delete/create/copy) DIBLOKIR.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import secrets
import time
from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.ollama_key import OllamaApiKey

logger = get_logger(__name__)

KEY_PREFIX = "ch-ollama-"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def generate_key() -> tuple[str, str, str]:
    """Hasilkan (kunci_mentah, prefix_tampilan, hash). Kunci mentah hanya sekali ini."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[: len(KEY_PREFIX) + 6], hash_key(raw)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


async def find_valid_key(session: AsyncSession, raw: str) -> OllamaApiKey | None:
    """Cari kunci aktif & belum kedaluwarsa dari kunci mentah; None bila tidak valid."""
    if not raw or not raw.startswith(KEY_PREFIX):
        return None
    row = (
        await session.scalars(select(OllamaApiKey).where(OllamaApiKey.key_hash == hash_key(raw)))
    ).first()
    if row is None or not row.enabled:
        return None
    if row.expires_at is not None:
        exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=dt.timezone.utc)
        if exp <= _utcnow():
            return None
    return row


class _Limiter:
    """Batas laju (sliding window per menit) + konkurensi per-kunci, di memori."""

    def __init__(self) -> None:
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._inflight: dict[int, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def acquire(self, key_id: int, rate_per_min: int, max_concurrent: int) -> str | None:
        """None bila boleh lanjut; selain itu alasan penolakan (untuk HTTP 429)."""
        now = time.monotonic()
        async with self._lock:
            hits = self._hits[key_id]
            while hits and now - hits[0] >= 60.0:
                hits.popleft()
            if rate_per_min > 0 and len(hits) >= rate_per_min:
                return f"batas {rate_per_min} permintaan/menit terlampaui"
            if max_concurrent > 0 and self._inflight[key_id] >= max_concurrent:
                return f"batas {max_concurrent} permintaan bersamaan terlampaui"
            hits.append(now)
            self._inflight[key_id] += 1
        return None

    async def release(self, key_id: int) -> None:
        async with self._lock:
            if self._inflight[key_id] > 0:
                self._inflight[key_id] -= 1


limiter = _Limiter()
