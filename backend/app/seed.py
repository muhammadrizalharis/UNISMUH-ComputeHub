"""Pembuatan data awal: admin pertama & data demo.

Dipakai sebagai:
  - fungsi (`ensure_first_admin`) saat startup aplikasi, dan
  - skrip CLI:  python -m app.seed [--demo]
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models.user import User, UserRole

logger = get_logger(__name__)


async def _get_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def ensure_first_admin(session: AsyncSession) -> None:
    """Buat admin pertama dari settings bila belum ada user sama sekali.

    Demi keamanan, instalasi BARU WAJIB menyetel `FIRST_ADMIN_PASSWORD` yang kuat
    di `.env` (tidak ada password default). Bila lemah/kosong, startup dihentikan
    dengan pesan jelas.
    """
    total = await session.scalar(select(func.count()).select_from(User))
    if total and total > 0:
        return
    if not settings.is_first_admin_password_safe:
        raise RuntimeError(
            "FIRST_ADMIN_PASSWORD belum di-set (atau terlalu lemah). "
            "Setel password kuat (>=8 karakter) di backend/.env sebelum menjalankan "
            "instalasi baru. Contoh: FIRST_ADMIN_PASSWORD=<password-rahasia-anda>"
        )
    admin = User(
        name=settings.FIRST_ADMIN_NAME,
        email=settings.FIRST_ADMIN_EMAIL,
        hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD),
        role=UserRole.admin,
        is_active=True,
    )
    session.add(admin)
    await session.commit()
    logger.info("Admin pertama dibuat: %s", settings.FIRST_ADMIN_EMAIL)


async def backfill_usernames(session: AsyncSession) -> None:
    """Isi `username` untuk user LAMA yang belum punya (DB sebelum fitur username ada).

    Aman & idempotent: HANYA menyentuh baris username NULL/kosong (mis. admin & super
    admin bawaan). Username dibuat dari email (CH + bagian lokal) dengan jaminan unik.
    Login via email TETAP berfungsi; ini hanya menambah opsi login via username.
    """
    from app.services import accounts as accounts_svc  # lazy: hindari siklus impor

    users = (
        (
            await session.execute(
                select(User).where(
                    (User.username.is_(None)) | (User.username == "")
                )
            )
        )
        .scalars()
        .all()
    )
    filled = 0
    for u in users:
        u.username = await accounts_svc.generate_unique_username(session, u.email)
        await session.flush()  # agar username yang baru di-set ikut dicek unik
        filled += 1
    if filled:
        await session.commit()
        logger.info("Backfill username: %d akun lama diberi username.", filled)


async def _seed_demo(session: AsyncSession) -> None:
    """Tambah akun demo dosen & mahasiswa (idempotent)."""
    demo_users = [
        ("Dosen Demo", "dosen@unismuh.ac.id", "password123", UserRole.dosen),
        ("Mahasiswa Demo", "mahasiswa@unismuh.ac.id", "password123", UserRole.mahasiswa),
    ]
    created = 0
    for name, email, password, role in demo_users:
        if await _get_by_email(session, email) is not None:
            continue
        session.add(
            User(
                name=name,
                email=email,
                hashed_password=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        created += 1
    if created:
        await session.commit()
    logger.info("Data demo siap (%d akun baru).", created)


async def run(demo: bool = False, force: bool = False) -> None:
    if demo and settings.ENV == "production" and not force:
        raise SystemExit(
            "Penolakan: akun demo TIDAK boleh di-seed saat ENV=production. "
            "Gunakan --force hanya bila benar-benar paham risikonya."
        )
    await init_db()
    async with AsyncSessionLocal() as session:
        await ensure_first_admin(session)
        if demo:
            await _seed_demo(session)
    logger.info("Seeding selesai.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed database UNISMUH AI Cloud")
    parser.add_argument(
        "--demo", action="store_true", help="Tambahkan akun demo dosen & mahasiswa"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Izinkan seed demo walau ENV=production (TIDAK disarankan)",
    )
    args = parser.parse_args()
    asyncio.run(run(demo=args.demo, force=args.force))


if __name__ == "__main__":
    main()
