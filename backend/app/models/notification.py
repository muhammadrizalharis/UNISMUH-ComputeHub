"""Notifikasi in-app per-user (ikon lonceng): job selesai/gagal, kuota, dsb.

Baris kecil & best-effort — dibuat oleh service lain (mis. job_notify) tanpa
mengganggu alur utama. Dibaca user lewat GET /notifications (poll ringan).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String, Text

from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    # Jenis: job_succeeded | job_failed | quota_warning | info
    type: Mapped[str] = mapped_column(String(32), default="info")
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    # Tautan relatif di aplikasi (mis. /jobs/123) — opsional.
    link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
