"""Pengaturan sistem (policy) yang bisa diubah ADMIN saat runtime.

Satu baris (id=1). Nilai awal diisi dari default config.py, lalu bisa diubah
admin lewat API tanpa restart. Sumber kebenaran kuota/limit saat runtime.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # Alokasi GPU / konkurensi
    enforce_gpu: Mapped[bool] = mapped_column(Boolean, default=True)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, default=2)
    student_max_concurrent_jobs: Mapped[int] = mapped_column(Integer, default=1)

    # Kuota GPU harian mahasiswa (detik, rolling 24 jam; 0 = tanpa batas)
    student_daily_gpu_seconds_quota: Mapped[int] = mapped_column(Integer, default=14400)

    # Batas waktu otomatis (detik)
    default_job_time_limit_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    min_job_time_limit_seconds: Mapped[int] = mapped_column(Integer, default=120)
    max_job_time_limit_seconds: Mapped[int] = mapped_column(Integer, default=7200)
    runtime_safety_factor: Mapped[float] = mapped_column(Float, default=1.5)

    # Plafon resource mahasiswa (0 = tanpa batas keras)
    student_max_gpu_memory_mb: Mapped[float] = mapped_column(Float, default=0.0)
    student_max_ram_mb: Mapped[float] = mapped_column(Float, default=0.0)

    # Lain-lain
    auto_pip_install: Mapped[bool] = mapped_column(Boolean, default=True)

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
