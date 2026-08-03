"""Cuplikan pemakaian resource per USER OS (bahan riwayat harian).

Satu baris = satu user pada satu waktu cuplik. Akun layanan (mis. `ollama`)
ikut disimpan dan ditandai `is_system` agar beban layanan bersama tetap punya
jejak. Tabel additive -> dibuat otomatis schema_sync saat restart.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class OsUserSample(Base):
    __tablename__ = "os_user_samples"
    # Kueri utama = rentang tanggal untuk satu/semua user.
    __table_args__ = (Index("ix_os_user_samples_user_ts", "username", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True, nullable=False
    )
    username: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0)
    memory_mb: Mapped[float] = mapped_column(Float, default=0.0)
    vram_mb: Mapped[float] = mapped_column(Float, default=0.0)
    processes: Mapped[int] = mapped_column(Integer, default=0)
    # Label workload hasil deteksi (mis. "Jupyter", "diffusion") — konteks cepat.
    activity: Mapped[str] = mapped_column(String(64), default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
