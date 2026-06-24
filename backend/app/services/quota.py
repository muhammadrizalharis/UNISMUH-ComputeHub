"""Kuota GPU harian per mahasiswa (rolling 24 jam).

Menghitung total durasi GPU (actual_runtime_seconds) job yang selesai dalam
24 jam terakhir. Dipakai untuk membatasi pemakaian mahasiswa secara adil.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.services import policy as policy_svc

WINDOW_HOURS = 24


def _window_start() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=WINDOW_HOURS)


async def gpu_seconds_used(session: AsyncSession, user_id: int) -> float:
    """Total detik GPU yang dipakai user dalam 24 jam terakhir."""
    value = await session.scalar(
        select(func.coalesce(func.sum(Job.actual_runtime_seconds), 0.0)).where(
            Job.user_id == user_id,
            Job.finished_at >= _window_start(),
            Job.actual_runtime_seconds.is_not(None),
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
        "window_hours": WINDOW_HOURS,
        "used_seconds": used_seconds,
        "quota_seconds": quota,
        "remaining_seconds": max(0.0, quota - used_seconds) if enabled else None,
        "quota_enabled": enabled,
    }
