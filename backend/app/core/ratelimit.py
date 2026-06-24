"""Rate limiter in-memory (sliding window) untuk anti brute-force.

Tanpa dependensi eksternal (Redis dll) agar cocok untuk lingkungan non-admin.
Cukup untuk satu proses uvicorn. Bila kelak di-scale multi-proses, ganti dengan
penyimpanan bersama.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int  # detik sampai boleh mencoba lagi (0 bila diizinkan)


class SlidingWindowRateLimiter:
    """Hitung percobaan GAGAL per kunci; blokir sementara bila melewati batas."""

    def __init__(
        self, max_attempts: int, window_seconds: int, block_seconds: int
    ) -> None:
        self.max_attempts = max(1, max_attempts)
        self.window_seconds = max(1, window_seconds)
        self.block_seconds = max(1, block_seconds)
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}

    def check(self, key: str) -> RateLimitResult:
        """Cek apakah kunci sedang diblokir (dipanggil sebelum verifikasi)."""
        now = time.monotonic()
        blocked = self._blocked_until.get(key)
        if blocked is not None:
            if now < blocked:
                return RateLimitResult(False, int(blocked - now) + 1)
            # Masa blokir habis -> bersihkan.
            self._blocked_until.pop(key, None)
            self._fails.pop(key, None)
        return RateLimitResult(True, 0)

    def record_failure(self, key: str) -> RateLimitResult:
        """Catat satu percobaan gagal; blokir bila melewati batas."""
        now = time.monotonic()
        dq = self._fails[key]
        dq.append(now)
        cutoff = now - self.window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self.max_attempts:
            self._blocked_until[key] = now + self.block_seconds
            dq.clear()
            return RateLimitResult(False, self.block_seconds)
        return RateLimitResult(True, 0)

    def reset(self, key: str) -> None:
        """Reset hitungan (dipanggil setelah login sukses)."""
        self._fails.pop(key, None)
        self._blocked_until.pop(key, None)
