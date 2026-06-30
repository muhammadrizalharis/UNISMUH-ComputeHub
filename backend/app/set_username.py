"""Ubah username pengguna secara MANUAL (CLI) — untuk admin/super admin atau siapa pun.

Username disimpan di DATABASE (kolom users.username), BUKAN di-hardcode di kode. Skrip ini
mengubahnya langsung & aman (validasi format + cek bentrok). Login via email tetap jalan;
username hanya menambah opsi login.

Pakai (dari folder backend):
    .venv/bin/python -m app.set_username <email | username lama | id> <username-baru>

Contoh:
    .venv/bin/python -m app.set_username muhammadrizalharis@unismuh.ac.id admin
    .venv/bin/python -m app.set_username 105841103223@student.unismuh.ac.id ical
    .venv/bin/python -m app.set_username 1 superadmin

Aman dijalankan saat server hidup (perubahan langsung berlaku untuk login berikutnya).
"""

from __future__ import annotations

import argparse
import asyncio
import re

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User

# Username valid: 3-64 karakter, hanya huruf/angka/titik/garis bawah/strip.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


async def _find_user(session, ident: str) -> User | None:
    """Cari user berdasarkan id (angka), email, atau username lama."""
    if ident.isdigit():
        user = await session.get(User, int(ident))
        if user is not None:
            return user
    return await session.scalar(
        select(User).where((User.email == ident) | (User.username == ident))
    )


async def set_username(ident: str, new_username: str) -> None:
    new_username = (new_username or "").strip()
    if not _USERNAME_RE.match(new_username):
        raise SystemExit(
            "Username tidak valid. Harus 3-64 karakter: huruf, angka, titik, '_' atau '-'."
        )
    async with AsyncSessionLocal() as session:
        user = await _find_user(session, ident)
        if user is None:
            raise SystemExit(f"User '{ident}' tidak ditemukan (cek email/username/id).")
        clash = await session.scalar(
            select(User.id).where(User.username == new_username, User.id != user.id)
        )
        if clash is not None:
            raise SystemExit(
                f"Username '{new_username}' sudah dipakai user lain (id {clash})."
            )
        old = user.username
        user.username = new_username
        await session.commit()
        print(
            f"OK: {user.name} <{user.email}> (id {user.id}) "
            f"username {old!r} -> {new_username!r}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ubah username pengguna (admin/super admin/siapa pun)."
    )
    parser.add_argument("ident", help="email, username lama, atau id pengguna")
    parser.add_argument(
        "username", help="username baru (3-64 karakter: huruf/angka/._-)"
    )
    args = parser.parse_args()
    asyncio.run(set_username(args.ident, args.username))


if __name__ == "__main__":
    main()
