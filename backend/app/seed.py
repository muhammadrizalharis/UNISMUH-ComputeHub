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
    """Buat admin pertama dari settings bila belum ada user sama sekali."""
    total = await session.scalar(select(func.count()).select_from(User))
    if total and total > 0:
        return
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


async def run(demo: bool = False) -> None:
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
    args = parser.parse_args()
    asyncio.run(run(demo=args.demo))


if __name__ == "__main__":
    main()
