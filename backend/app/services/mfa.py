"""Layanan 2FA / TOTP (opt-in) untuk login username/password.

Hanya menyentuh akun yang MEMILIH mengaktifkan — login tanpa 2FA tetap berjalan
seperti biasa. Rahasia TOTP disimpan base32 di kolom `users.totp_secret`; kode
pemulihan disimpan sebagai HASH bcrypt (`users.mfa_recovery_codes`) agar sekali
pakai dan tak bisa dibaca balik dari DB.
"""

from __future__ import annotations

import base64
import io
import secrets

import pyotp

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.user import User

ISSUER = "ComputeHub"
RECOVERY_CODE_COUNT = 10
# Jendela toleransi: 1 => menerima kode dari periode sebelum/sesudah (±30 dtk)
# supaya selisih jam ringan tidak menggagalkan login.
VALID_WINDOW = 1


def generate_secret() -> str:
    """Rahasia base32 baru untuk TOTP."""
    return pyotp.random_base32()


def provisioning_uri(user: User, secret: str) -> str:
    """URI `otpauth://` untuk dipindai aplikasi authenticator."""
    label = user.email or user.username or f"user-{user.id}"
    issuer = settings.APP_NAME if getattr(settings, "APP_NAME", None) else ISSUER
    return pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name=issuer)


def qr_svg_data_uri(uri: str) -> str:
    """QR dari `uri` sebagai data URI SVG (tanpa Pillow) untuk <img src=...>."""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def verify_totp(secret: str | None, code: str) -> bool:
    """True bila `code` cocok untuk `secret` dalam jendela toleransi."""
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    try:
        return bool(pyotp.TOTP(secret).verify(code, valid_window=VALID_WINDOW))
    except Exception:  # noqa: BLE001 — kode korup/format aneh => gagal aman
        return False


def _new_recovery_code() -> str:
    """Kode pemulihan mudah disalin: 10 heksadesimal, mis. `7fa3-91c2b`."""
    raw = secrets.token_hex(5)  # 10 hex chars
    return f"{raw[:4]}-{raw[4:]}"


def generate_recovery_codes() -> tuple[list[str], list[str]]:
    """Kembalikan (kode_teks_untuk_ditampilkan_sekali, hash_untuk_disimpan)."""
    plain = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    hashed = [hash_password(c) for c in plain]
    return plain, hashed


def consume_recovery_code(user: User, code: str) -> bool:
    """Pakai satu kode pemulihan (sekali pakai). Menghapus hash yang cocok dari
    `user.mfa_recovery_codes` bila benar, lalu True; selain itu False."""
    if not code:
        return False
    code = code.strip().lower().replace(" ", "")
    stored = list(user.mfa_recovery_codes or [])
    for i, h in enumerate(stored):
        if verify_password(code, h):
            stored.pop(i)
            user.mfa_recovery_codes = stored
            return True
    return False


def disable(user: User) -> None:
    """Matikan 2FA & bersihkan semua rahasia/kode."""
    user.mfa_enabled = False
    user.totp_secret = None
    user.mfa_enrolled_at = None
    user.mfa_recovery_codes = None
