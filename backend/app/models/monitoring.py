"""Model ResourceSample (time-series monitoring CPU/RAM/GPU)."""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class SampleScope(str, enum.Enum):
    system = "system"  # snapshot seluruh node
    job = "job"        # snapshot 1 job


class ResourceSample(Base):
    __tablename__ = "resource_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True, nullable=False
    )
    scope: Mapped[SampleScope] = mapped_column(
        SAEnum(SampleScope, native_enum=False, length=10),
        default=SampleScope.system,
        index=True,
        nullable=False,
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # CPU / RAM
    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0)
    memory_used_mb: Mapped[float] = mapped_column(Float, default=0.0)
    memory_total_mb: Mapped[float] = mapped_column(Float, default=0.0)

    # GPU
    gpu_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_util_percent: Mapped[float] = mapped_column(Float, default=0.0)
    gpu_mem_used_mb: Mapped[float] = mapped_column(Float, default=0.0)
    gpu_mem_total_mb: Mapped[float] = mapped_column(Float, default=0.0)
    gpu_temperature_c: Mapped[float] = mapped_column(Float, default=0.0)
    gpu_power_w: Mapped[float] = mapped_column(Float, default=0.0)
