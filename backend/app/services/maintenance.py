"""Mode pemeliharaan — dikendalikan dari LUAR aplikasi lewat sebuah file penanda.

Kenapa file, bukan kolom database?
  * Bisa dinyalakan/dimatikan walau aplikasi sedang bermasalah (tak perlu login,
    tak perlu DB hidup, tak perlu restart) — cocok dipakai bot Telegram pemilik.
  * Tidak kena masalah cache kebijakan per-proses (system_settings di-cache;
    tulis langsung ke DB TIDAK terbaca backend yang sudah jalan).

Efek saat aktif: pekerjaan BARU (submit job / mulai sesi interaktif) ditolak
dengan 503 supaya GPU sepi menjelang restart/pembaruan. Job & kernel yang SEDANG
berjalan TIDAK diganggu, dan admin tetap boleh mengirim pekerjaan (untuk uji
coba setelah pemeliharaan). Membaca data (dashboard, riwayat) tetap normal.

Isi file (opsional) = pesan yang ditampilkan ke pengguna. File kosong -> pesan
bawaan.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

# Cache singkat: endpoint submit bisa dipanggil sering, jangan stat() tiap kali.
_CACHE_TTL_SECONDS = 3.0
_PESAN_BAWAAN = (
    "Platform sedang dalam pemeliharaan. Pekerjaan baru ditahan sementara; "
    "job dan sesi yang sedang berjalan tetap aman. Coba lagi beberapa saat lagi."
)

_cache: tuple[float, "MaintenanceState"] | None = None


@dataclass(frozen=True)
class MaintenanceState:
    active: bool
    message: str
    since: float | None  # epoch detik saat mode dinyalakan (mtime file)


def flag_path() -> Path:
    return settings.maintenance_flag_path


def state() -> MaintenanceState:
    """Kondisi pemeliharaan saat ini (di-cache beberapa detik)."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]

    path = flag_path()
    try:
        stat = path.stat()
    except OSError:
        result = MaintenanceState(active=False, message="", since=None)
    else:
        try:
            pesan = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            pesan = ""
        result = MaintenanceState(
            active=True,
            message=pesan or _PESAN_BAWAAN,
            since=stat.st_mtime,
        )
    _cache = (now, result)
    return result


def is_active() -> bool:
    return state().active


def set_active(active: bool, message: str = "") -> MaintenanceState:
    """Nyalakan/matikan pemeliharaan dari dalam aplikasi (panel admin).

    Memakai berkas yang SAMA dengan pengendali luar, jadi kedua jalur selalu
    melihat kondisi yang sama dan tidak bisa saling bertentangan.
    """
    global _cache
    path = flag_path()
    if active:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((message.strip() or _PESAN_BAWAAN) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    _cache = None  # jangan sampai jawaban endpoint masih memakai nilai lama
    return state()
