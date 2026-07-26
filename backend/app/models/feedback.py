"""Model SARAN/MASUKAN pengguna (menu Saran) — kanal umpan balik resmi platform.

Semua peran boleh mengirim; admin & super admin meninjau, mengubah status, dan
menghapus spam. Identitas pengirim di-denormalisasi (nama/peran) supaya daftar
tetap terbaca walau akun pengirim kelak dihapus. Tabel additive -> otomatis
dibuat schema_sync saat restart backend.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    # Pengirim (denormalisasi ringan untuk tampilan admin).
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_name: Mapped[str] = mapped_column(String(255), default="")
    user_role: Mapped[str] = mapped_column(String(16), default="")

    # Kategori: saran | masalah | lainnya
    category: Mapped[str] = mapped_column(String(16), default="saran")
    message: Mapped[str] = mapped_column(Text, default="")

    # Status tindak lanjut: baru | ditinjau | selesai
    status: Mapped[str] = mapped_column(String(16), default="baru", index=True)
