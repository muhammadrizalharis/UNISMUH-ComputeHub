"""Model peringatan (alert) batas resource.

- AlertConfig: satu baris (id=1) — ambang batas + penerima email, diatur admin.
- Alert: riwayat pelanggaran yang terdeteksi + status pengiriman email.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AlertConfig(Base):
    __tablename__ = "alert_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Ambang batas per user OS (lewat = peringatan).
    cpu_cores: Mapped[float] = mapped_column(Float, default=16.0)   # core-equivalent
    ram_gb: Mapped[float] = mapped_column(Float, default=64.0)
    vram_gb: Mapped[float] = mapped_column(Float, default=40.0)
    disk_percent: Mapped[float] = mapped_column(Float, default=90.0)  # filesystem '/'

    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    email_on_breach: Mapped[bool] = mapped_column(Boolean, default=True)
    # Penerima email (dipisah koma); kosong = fallback ke email admin.
    email_to: Mapped[str] = mapped_column(Text, default="")

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    scope: Mapped[str] = mapped_column(String(20), default="os_user")  # os_user|system
    subject: Mapped[str] = mapped_column(String(120), index=True)       # username / "system"
    metric: Mapped[str] = mapped_column(String(20))                     # cpu|ram|vram|disk
    value: Mapped[float] = mapped_column(Float, default=0.0)
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")

    emailed: Mapped[bool] = mapped_column(Boolean, default=False)
    email_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
