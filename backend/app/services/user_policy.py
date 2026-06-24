"""Resolusi policy efektif per-user (override per-mahasiswa + fallback global)."""

from __future__ import annotations

import dataclasses

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_policy import UserPolicy
from app.services import policy as policy_svc

OVERRIDE_FIELDS = (
    "daily_gpu_seconds_quota",
    "max_concurrent_jobs",
    "max_time_limit_seconds",
    "max_gpu_memory_mb",
    "max_ram_mb",
)


@dataclasses.dataclass
class EffectiveUserPolicy:
    daily_gpu_seconds_quota: int
    max_concurrent_jobs: int
    max_time_limit_seconds: int
    max_gpu_memory_mb: float
    max_ram_mb: float


def _merge(glob: policy_svc.Policy, ov: UserPolicy | None) -> EffectiveUserPolicy:
    def pick(attr: str, fallback):
        value = getattr(ov, attr, None) if ov is not None else None
        return value if value is not None else fallback

    return EffectiveUserPolicy(
        daily_gpu_seconds_quota=pick(
            "daily_gpu_seconds_quota", glob.student_daily_gpu_seconds_quota
        ),
        max_concurrent_jobs=pick(
            "max_concurrent_jobs", glob.student_max_concurrent_jobs
        ),
        max_time_limit_seconds=pick(
            "max_time_limit_seconds", glob.max_job_time_limit_seconds
        ),
        max_gpu_memory_mb=pick("max_gpu_memory_mb", glob.student_max_gpu_memory_mb),
        max_ram_mb=pick("max_ram_mb", glob.student_max_ram_mb),
    )


async def effective(session: AsyncSession, user_id: int) -> EffectiveUserPolicy:
    ov = await session.get(UserPolicy, user_id)
    return _merge(policy_svc.get(), ov)


async def effective_map(
    session: AsyncSession, user_ids: set[int]
) -> dict[int, EffectiveUserPolicy]:
    glob = policy_svc.get()
    if not user_ids:
        return {}
    rows = (
        await session.scalars(
            select(UserPolicy).where(UserPolicy.user_id.in_(user_ids))
        )
    ).all()
    by_id = {r.user_id: r for r in rows}
    return {uid: _merge(glob, by_id.get(uid)) for uid in user_ids}


async def get_overrides(session: AsyncSession, user_id: int) -> UserPolicy | None:
    return await session.get(UserPolicy, user_id)


async def set_overrides(
    session: AsyncSession, user_id: int, changes: dict
) -> UserPolicy:
    """Set/ubah override. Nilai None pada sebuah field = hapus override field itu."""
    ov = await session.get(UserPolicy, user_id)
    if ov is None:
        ov = UserPolicy(user_id=user_id)
        session.add(ov)
    for key, value in changes.items():
        if key in OVERRIDE_FIELDS:
            setattr(ov, key, value)
    await session.commit()
    await session.refresh(ov)
    return ov
