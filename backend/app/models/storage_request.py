"""Permintaan TAMBAHAN KUOTA penyimpanan /persist dari pengguna ke admin.

Alur: user (kuota hampir/penuh) mengajukan jumlah + alasan -> admin menerima
notifikasi (lonceng, Telegram, email) -> admin menyetujui (menetapkan kuota baru
via override user_policies.max_storage_mb) atau menolak dengan catatan -> user
diberi tahu lewat lonceng. Hanya SATU permintaan 'pending' per user.
Tabel additive -> dibuat otomatis saat restart (create_all).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class StorageQuotaRequest(Base):
    __tablename__ = "storage_quota_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    # Denormalisasi agar riwayat tetap terbaca walau akun dihapus.
    user_name: Mapped[str] = mapped_column(String(255), default="")
    user_email: Mapped[str] = mapped_column(String(255), default="")
    user_role: Mapped[str] = mapped_column(String(16), default="")

    current_quota_mb: Mapped[float] = mapped_column(Float, default=0.0)
    used_mb: Mapped[float] = mapped_column(Float, default=0.0)
    requested_mb: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")

    # pending | approved | rejected
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by_email: Mapped[str] = mapped_column(String(255), default="")
    granted_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
