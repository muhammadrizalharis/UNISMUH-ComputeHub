"""Keamanan: hashing password (bcrypt) & JWT (PyJWT)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

# bcrypt membatasi input maksimal 72 byte.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """Hash password dengan bcrypt."""
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


# Password lemah/umum yang ditolak (daftar ringkas; pelengkap aturan kekuatan).
_WEAK_PASSWORDS = frozenset({
    "password", "password1", "password123", "12345678", "123456789", "1234567890",
    "qwerty", "qwerty123", "admin", "admin123", "changeme", "welcome", "iloveyou",
    "unismuh", "computehub", "letmein", "abc12345", "rahasia", "qwertyuiop",
})


def validate_password_strength(
    password: str, *, identifiers: list[str] | None = None
) -> None:
    """Validasi kekuatan password USER-PILIH; raise ValueError(pesan) bila lemah.

    Aturan: minimal 8 karakter, TIDAK hanya angka (mis. NIM), bukan password umum,
    dan tidak sama/memuat identitas mudah ditebak (NIM/email/username).
    """
    pw = (password or "").strip()
    if len(pw) < 8:
        raise ValueError("Password minimal 8 karakter.")
    if pw.isdigit():
        raise ValueError(
            "Password tidak boleh hanya angka (mis. NIM). Campur huruf & angka."
        )
    if pw.lower() in _WEAK_PASSWORDS:
        raise ValueError("Password terlalu umum/mudah ditebak. Pilih yang lain.")
    low = pw.lower()
    for ident in identifiers or []:
        idt = (ident or "").strip().lower()
        if len(idt) >= 4 and (idt == low or idt in low):
            raise ValueError(
                "Password tidak boleh memuat NIM/email/username. Pilih yang lebih unik."
            )


def verify_password(password: str, hashed: str) -> bool:
    """Verifikasi password terhadap hash bcrypt."""
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:_BCRYPT_MAX_BYTES],
            hashed.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str,
    role: str,
    session_id: str | None = None,
    expires_minutes: int | None = None,
) -> str:
    """Buat JWT access token.

    `session_id` (klaim `sid`) dipakai untuk penegakan sesi tunggal: hanya token
    dengan sid yang cocok dengan `users.session_token` terakhir yang dianggap sah.
    """
    now = dt.datetime.now(dt.timezone.utc)
    expire = now + dt.timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": expire,
    }
    if session_id is not None:
        payload["sid"] = session_id
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    subject: str,
    role: str,
    session_id: str,
    expires_minutes: int,
) -> str:
    """Buat JWT refresh token (umur panjang) untuk menukar access token baru.

    Membawa klaim `type=refresh` + `sid` (sesi tunggal). Refresh hanya sah selama
    sid masih sama dengan `users.session_token` (login di perangkat lain -> gugur).
    """
    now = dt.datetime.now(dt.timezone.utc)
    expire = now + dt.timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": "refresh",
        "sid": session_id,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode & validasi JWT. Melempar jwt.PyJWTError bila invalid/expired."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
