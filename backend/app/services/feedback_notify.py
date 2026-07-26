"""Pemberitahuan SARAN BARU ke pengelola: email semua admin + Telegram.

Dipanggil fire-and-forget (asyncio.create_task) setelah saran tersimpan —
best-effort total: kegagalan email/Telegram TIDAK boleh menggagalkan kiriman
saran itu sendiri (saran sudah aman di database).

Email  : ke SEMUA akun aktif ber-peran admin (termasuk super admin) — alamat
         diambil live dari tabel users, jadi admin baru otomatis ikut.
Telegram: lewat scripts/notify_telegram.py (kredensial di ~/.computehub,
         di luar repo) — dijalankan sebagai subprocess persis seperti pola
         monthly_report.py, supaya token tidak perlu disalin ke backend/.env.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.feedback import Feedback
from app.models.user import User, UserRole
from app.services import email as email_svc

logger = get_logger(__name__)

# SERVER-KAMPUS/scripts/notify_telegram.py (stdlib-only, selalu exit 0).
_NOTIFY_TELEGRAM = Path(__file__).resolve().parents[3] / "scripts" / "notify_telegram.py"

_CATEGORY_LABEL = {"saran": "Saran fitur", "masalah": "Masalah", "lainnya": "Lainnya"}


def _kirim_telegram(judul: str, isi: str) -> None:
    """Blocking — jalankan lewat asyncio.to_thread."""
    if not _NOTIFY_TELEGRAM.exists():
        return
    subprocess.run(
        [sys.executable, str(_NOTIFY_TELEGRAM), judul, isi],
        capture_output=True,
        timeout=30,
        check=False,
    )


async def notify_new_feedback(feedback_id: int) -> None:
    """Kabari pengelola ada saran baru. Best-effort (tak pernah melempar)."""
    try:
        async with AsyncSessionLocal() as session:
            fb = await session.get(Feedback, feedback_id)
            if fb is None:
                return
            # Kiriman uji otomatis (Playwright) TIDAK dikirim ke pengelola —
            # tetap tersimpan & tampil di daftar admin, hanya notifikasinya
            # yang dilewati supaya suite QA tidak menyepam email admin nyata.
            if fb.message.lstrip().startswith("[UJI QA]"):
                return
            rows = await session.execute(
                select(User.email).where(
                    User.role == UserRole.admin, User.is_active.is_(True)
                )
            )
            recipients = sorted({e.strip() for (e,) in rows if e and e.strip()})

        kategori = _CATEGORY_LABEL.get(fb.category, fb.category)
        pengirim = f"{fb.user_name or 'Tanpa nama'} ({fb.user_role or '-'})"
        base = settings.public_base_url
        link = f"{base}/saran" if base else ""
        cuplikan = fb.message.strip()
        if len(cuplikan) > 800:
            cuplikan = cuplikan[:800] + "…"

        # --- Telegram dulu (paling cepat sampai) ---
        try:
            isi = f"Dari    : {pengirim}\nKategori: {kategori}\n\n{cuplikan}"
            if link:
                isi += f"\n\nTinjau: {link}"
            await asyncio.to_thread(
                _kirim_telegram, f"\U0001f4a1 Saran baru #{fb.id} — {settings.PROJECT_NAME}", isi
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Telegram saran #%d gagal: %r", feedback_id, exc)

        # --- Email ke semua admin ---
        if not recipients or not settings.smtp_configured:
            return
        subject = f"Saran baru dari {fb.user_name or 'pengguna'} — {settings.PROJECT_NAME}"
        lines = [
            "Ada masukan baru di menu Saran:",
            "",
            f"  Pengirim : {pengirim}",
            f"  Kategori : {kategori}",
            f"  Waktu    : {fb.created_at:%d-%m-%Y %H:%M} UTC",
            "",
            cuplikan,
        ]
        if link:
            lines += ["", f"Tinjau & ubah status: {link}"]
        try:
            await asyncio.to_thread(
                email_svc.send_email, recipients, subject, "\n".join(lines)
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Email saran #%d gagal: %r", feedback_id, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify_new_feedback #%d gagal total: %r", feedback_id, exc)
