"""Override policy PER-USER (mahasiswa tertentu).

Admin bisa memberi batas khusus untuk satu mahasiswa (kuota, paralel, batas
waktu, VRAM, RAM). Field NULL = ikut policy global.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class UserPolicy(Base):
    __tablename__ = "user_policies"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    daily_gpu_seconds_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_concurrent_jobs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_gpu_memory_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_ram_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cpu_threads: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_storage_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Override model Asisten AI (mis. pimpinan minta model lebih besar). NULL = ikut default peran.
    assistant_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
