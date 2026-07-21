"""Model AUDIT LOG — jejak aksi penting admin (akuntabilitas multi-admin).

Dicatat: siapa (aktor), melakukan apa (action), pada apa (target), kapan, dan detail
ringkas. Tabel additive -> otomatis dibuat oleh schema_sync saat restart.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    # Aktor (di-denormalisasi supaya jejak tetap terbaca walau user dihapus).
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="")

    # Aksi (mis. 'user.create', 'user.delete', 'policy.update', 'settings.update',
    # 'job.purge', 'password.reset') + target ('user'/'job'/'settings' + id).
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")

    # Ringkasan perubahan (teks pendek, TANPA rahasia/password).
    detail: Mapped[str] = mapped_column(Text, default="")
