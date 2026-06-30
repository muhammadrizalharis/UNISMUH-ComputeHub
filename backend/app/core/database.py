"""Setup database async (SQLAlchemy 2.0).

Default SQLite (aiosqlite). Bisa diganti ke PostgreSQL (asyncpg) hanya lewat
DATABASE_URL di `.env`, tanpa mengubah kode.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Base class untuk semua ORM model."""


# SQLite butuh check_same_thread=False untuk dipakai lintas task async.
_connect_args: dict = {}
if settings.is_sqlite:
    _connect_args = {"check_same_thread": False}
elif settings.is_postgres:
    # asyncpg lewat pooler Supabase (pgbouncer mode transaksi) tidak mendukung
    # prepared-statement cache -> matikan. Plus SSL untuk koneksi remote.
    _connect_args = {"statement_cache_size": 0}
    if settings.DB_REQUIRE_SSL:
        _connect_args["ssl"] = "require"

engine = create_async_engine(
    settings.DATABASE_URL,
    **(
        {
            "echo": False,
            "future": True,
            "connect_args": _connect_args,
            # DB remote (Supabase): pre-ping menambah 1 round-trip/req (mahal di jaringan
            # jauh -> /auth/me ~1.1s). Matikan & andalkan pool_recycle agar koneksi basi diganti.
            "pool_pre_ping": False,
            "pool_recycle": 180,
        }
        if settings.is_postgres
        else {
            "echo": False,
            "future": True,
            "connect_args": _connect_args,
            "pool_pre_ping": True,
        }
    ),
)


# Aktifkan WAL + foreign keys untuk SQLite (konkurensi baca/tulis lebih baik).
if settings.is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
        finally:
            cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency FastAPI: sesi database per-request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Buat semua tabel bila belum ada, lalu sinkronkan kolom baru (SQLite)."""
    # Import models agar terdaftar di metadata sebelum create_all.
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrasi ringan additive: tambah kolom baru ke tabel lama (aman data,
        # hanya ADD COLUMN, tak pernah drop/rename). Berlaku SQLite & PostgreSQL.
        from app.core.schema_sync import sync_additive_schema

        applied = await conn.run_sync(
            lambda sync_conn: sync_additive_schema(sync_conn, Base.metadata)
        )
        if applied:
            logger.info(
                "Migrasi skema: %d kolom baru ditambahkan (%s).",
                len(applied),
                ", ".join(applied),
            )
    logger.info("Database siap (%s)", "sqlite" if settings.is_sqlite else "external")


async def dispose_db() -> None:
    """Tutup koneksi engine saat shutdown."""
    await engine.dispose()
