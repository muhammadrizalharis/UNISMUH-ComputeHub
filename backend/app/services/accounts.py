"""Helper akun pengguna: generate username & password awal, kirim kredensial via email.

Dipakai saat admin membuat user (router users): admin cukup input nama + email + role,
sistem menghasilkan username (`CH` + bagian lokal email) dan password acak kuat (di-hash
oleh pemanggil), lalu mengirim kredensial ke email user (best-effort).
"""

from __future__ import annotations

import asyncio
import re
import secrets
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.user import User
from app.services import email as email_svc

logger = get_logger(__name__)

USERNAME_PREFIX = "CH"
# Alfabet password acak: huruf + angka + simbol (kekuatan tinggi).
_PW_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+?"


def generate_password(length: int = 16) -> str:
    """Password acak kuat (cryptographically secure via secrets)."""
    length = max(12, length)
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def username_base(email: str) -> str:
    """`CH` + bagian lokal email (sebelum '@'), disanitasi ke [A-Za-z0-9._-]."""
    local = (email or "").split("@", 1)[0]
    local = re.sub(r"[^A-Za-z0-9._-]", "", local)
    return f"{USERNAME_PREFIX}{local}" if local else USERNAME_PREFIX


async def generate_unique_username(session: AsyncSession, email: str) -> str:
    """Username unik berbasis email; tambah sufiks angka bila bentrok."""
    base = username_base(email)
    candidate = base
    suffix = 1
    while (
        await session.scalar(select(User.id).where(User.username == candidate))
    ) is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


def _login_url() -> str:
    """URL login publik: APP_PUBLIC_URL bila diset, else origin https pertama di CORS."""
    if settings.APP_PUBLIC_URL.strip():
        return settings.APP_PUBLIC_URL.strip().rstrip("/")
    for origin in settings.cors_origins:
        if origin.startswith("https://"):
            return origin
    return ""


async def send_credentials_email(
    *, to: str, name: str, username: str, password: str
) -> bool:
    """Kirim email kredensial awal (BEST-EFFORT). True bila terkirim.

    TIDAK pernah melempar: kegagalan email tidak boleh menggagalkan pembuatan akun.
    """
    if not settings.smtp_configured:
        logger.warning("SMTP belum dikonfigurasi -> lewati email kredensial ke %s", to)
        return False

    login_url = _login_url()
    body_lines = [
        f"Halo {name},",
        "",
        f"Akun {settings.PROJECT_NAME} Anda telah dibuat. Berikut kredensial login Anda:",
        "",
        f"  Username : {username}",
        f"  Password : {password}",
        "",
        "Demi keamanan, segera login lalu ganti password Anda lewat menu Ubah Password.",
    ]
    if login_url:
        body_lines += ["", f"Login di: {login_url}"]
    body_lines += ["", f"— Tim {settings.PROJECT_NAME}"]
    body = "\n".join(body_lines)

    try:
        await asyncio.to_thread(
            email_svc.send_email,
            [to],
            f"Kredensial akun {settings.PROJECT_NAME}",
            body,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort; jangan gagalkan pembuatan akun
        logger.warning("Gagal kirim email kredensial ke %s: %r", to, exc)
        return False
