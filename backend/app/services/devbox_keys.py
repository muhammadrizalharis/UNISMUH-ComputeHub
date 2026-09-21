"""Kunci SSH devbox: dibuat server, dipasang otomatis di laptop user lewat pemasang.

Kenapa ada: VS Code Desktop menyambung ke devbox lewat Remote-SSH yang di-proxy backend
(WebSocket di domain kampus) — tanpa relay Microsoft dan tanpa LAN/VPN kampus. Supaya
pengguna tidak perlu membuat kunci, menyunting ~/.ssh/config, atau mengetik apa pun,
ComputeHub yang membuat pasangan kunci lalu membungkusnya dalam SATU berkas pemasang.

ATURAN:
  - Kunci PRIVAT hanya bisa diunduh OLEH PEMILIKNYA, dan hanya lewat pemasang; tidak
    pernah dikirim email dan tidak disimpan di /persist (yang ikut di-backup & bisa
    dibuka user lain lewat berbagi berkas).
  - Menerbitkan kunci baru otomatis MENCABUT yang lama (authorized_keys ditulis ulang),
    sehingga laptop yang hilang bisa diputus dari ComputeHub.
  - Tipe ed25519: pendek, cepat, didukung OpenSSH bawaan Windows 10/11, macOS, Linux.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Semua di HOME devbox (di luar /persist): tidak memakan kuota user & tidak ikut
# terbawa saat user membagikan isi ruang kerjanya.
_PRIVATE_NAME = "id_ed25519"
_PUBLIC_NAME = "id_ed25519.pub"


def key_dir(user_id: int) -> Path:
    return settings.devbox_home_root / str(int(user_id)) / "ssh"


def private_path(user_id: int) -> Path:
    return key_dir(user_id) / _PRIVATE_NAME


def public_path(user_id: int) -> Path:
    return key_dir(user_id) / _PUBLIC_NAME


def has_key(user_id: int) -> bool:
    return private_path(user_id).is_file() and public_path(user_id).is_file()


def generate(user_id: int, label: str = "") -> tuple[str, str]:
    """Buat pasangan kunci BARU (mencabut yang lama). Return (privat, publik) OpenSSH."""
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    komentar = label.strip() or f"computehub-{int(user_id)}"
    public = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
        + f" {komentar}"
    )

    folder = key_dir(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    priv = private_path(user_id)
    tmp = priv.with_suffix(".tmp")
    tmp.write_text(private, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(priv)
    public_path(user_id).write_text(public + "\n", encoding="utf-8")
    logger.info("Devbox #%d: kunci SSH baru diterbitkan (kunci lama dicabut).", user_id)
    return private, public


def ensure(user_id: int) -> str:
    """Kunci publik user (dibuat bila belum ada). Dipakai saat devbox dinyalakan."""
    if not has_key(user_id):
        _, public = generate(user_id)
        return public
    return public_path(user_id).read_text(encoding="utf-8").strip()


def read_private(user_id: int) -> str | None:
    try:
        return private_path(user_id).read_text(encoding="utf-8")
    except OSError:
        return None


def fingerprint(user_id: int) -> str:
    """Sidik jari kunci publik yang SEDANG berlaku (dipakai mengikat token akses SSH).

    Token yang membawa sidik jari lama otomatis tidak berlaku begitu user menerbitkan
    kunci baru ("laptop hilang"), tanpa perlu daftar pencabutan terpisah.
    """
    try:
        isi = public_path(user_id).read_text(encoding="utf-8").split()
    except OSError:
        return ""
    if len(isi) < 2:
        return ""
    return hashlib.sha256(isi[1].encode()).hexdigest()[:16]
