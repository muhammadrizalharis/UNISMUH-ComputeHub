"""Kuota GPU harian per pengguna (reset tiap pergantian hari).

Menghitung total durasi GPU (actual_runtime_seconds) job yang selesai SEJAK
tengah malam waktu setempat. Jadi kuota selalu penuh lagi di hari berikutnya,
bukan menunggu 24 jam sejak pemakaian terakhir.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.job import Job
from app.services import policy as policy_svc


def _window_start() -> dt.datetime:
    """Tengah malam hari ini menurut waktu setempat, dalam UTC (kolom DB memakai UTC)."""
    try:
        tz = ZoneInfo(settings.REPORT_TIMEZONE or "UTC")
    except Exception:  # noqa: BLE001  (nama zona salah -> jangan sampai kuota rusak)
        tz = dt.timezone.utc
    lokal = dt.datetime.now(tz)
    awal_hari = lokal.replace(hour=0, minute=0, second=0, microsecond=0)
    return awal_hari.astimezone(dt.timezone.utc)


def quota_reset_at() -> dt.datetime:
    """Kapan kuota berikutnya penuh lagi (tengah malam berikutnya), dalam UTC."""
    return _window_start() + dt.timedelta(days=1)


async def gpu_seconds_used(session: AsyncSession, user_id: int) -> float:
    """Total detik GPU yang dipakai user hari ini."""
    value = await session.scalar(
        select(func.coalesce(func.sum(Job.actual_runtime_seconds), 0.0)).where(
            Job.user_id == user_id,
            Job.finished_at >= _window_start(),
            Job.actual_runtime_seconds.is_not(None),
            Job.gpu_index.is_not(None),  # hanya job GPU yang kena kuota GPU
        )
    )
    return float(value or 0.0)


async def gpu_seconds_used_map(
    session: AsyncSession, user_ids: set[int]
) -> dict[int, float]:
    """Versi batch: {user_id: detik terpakai} untuk banyak user."""
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            select(
                Job.user_id,
                func.coalesce(func.sum(Job.actual_runtime_seconds), 0.0),
            )
            .where(
                Job.user_id.in_(user_ids),
                Job.finished_at >= _window_start(),
                Job.actual_runtime_seconds.is_not(None),
                Job.gpu_index.is_not(None),  # hanya job GPU yang kena kuota GPU
            )
            .group_by(Job.user_id)
        )
    ).all()
    return {uid: float(secs or 0.0) for uid, secs in rows}


def quota_enabled() -> bool:
    return policy_svc.get().student_daily_gpu_seconds_quota > 0


def usage_summary(used_seconds: float) -> dict:
    quota = policy_svc.get().student_daily_gpu_seconds_quota
    enabled = quota > 0
    return {
        # Dipertahankan demi kompatibilitas klien lama; kuota kini per hari kalender.
        "window_hours": 24,
        "used_seconds": used_seconds,
        "quota_seconds": quota,
        "remaining_seconds": max(0.0, quota - used_seconds) if enabled else None,
        "quota_enabled": enabled,
        "resets_at": quota_reset_at().isoformat(),
    }
