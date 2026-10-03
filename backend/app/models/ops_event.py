"""Model OPS EVENT — bukti operasional (cadangan, restore drill, offsite) yang
tersimpan di DB supaya bisa ditampilkan di web, bukan hanya di email/Telegram.

Ditulis oleh skrip host (scripts/ops_event.py) lewat psql di container Postgres,
dibaca oleh endpoint /admin/ops/*. Tabel additive -> dibuat otomatis saat restart;
skrip juga membuatnya (CREATE TABLE IF NOT EXISTS) dengan DDL yang identik agar
pencatatan berjalan sebelum backend direstart.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class OpsEvent(Base):
    __tablename__ = "ops_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    # 'backup' | 'restore_drill' | 'offsite' | 'watchdog'
    kind: Mapped[str] = mapped_column(String(32), index=True)
    # 'ok' | 'warn' | 'fail'
    status: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    # Teks ringkas untuk manusia (TANPA path rahasia/token).
    detail: Mapped[str] = mapped_column(Text, default="")
    # Angka/flag terstruktur: archive, size, offsite_tar, restic, tables, users, ...
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="")
    # Kunci anti-duplikat untuk rekonstruksi riwayat (NULL utk event langsung).
    dedup_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
