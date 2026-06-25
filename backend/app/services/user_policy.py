"""Resolusi policy efektif per-user (override per-user + fallback default peran)."""

from __future__ import annotations

import dataclasses

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.models.user_policy import UserPolicy
from app.services import policy as policy_svc

OVERRIDE_FIELDS = (
    "daily_gpu_seconds_quota",
    "max_concurrent_jobs",
    "max_time_limit_seconds",
    "max_gpu_memory_mb",
    "max_ram_mb",
    "max_cpu_threads",
)


@dataclasses.dataclass
class EffectiveUserPolicy:
    daily_gpu_seconds_quota: int
    max_concurrent_jobs: int
    max_time_limit_seconds: int
    max_gpu_memory_mb: float
    max_ram_mb: float
    max_cpu_threads: int


def _merge(
    glob: policy_svc.Policy,
    ov: UserPolicy | None,
    role: UserRole,
) -> EffectiveUserPolicy:
    # Basis default = batas peran user (mahasiswa/dosen/admin). Override per-user
    # menimpa per-field. Batas waktu tetap dari policy global (bukan per-peran).
    rl = policy_svc.role_limits(role)

    def pick(attr: str, fallback):
        value = getattr(ov, attr, None) if ov is not None else None
        return value if value is not None else fallback

    return EffectiveUserPolicy(
        daily_gpu_seconds_quota=pick(
            "daily_gpu_seconds_quota", rl.daily_gpu_seconds_quota
        ),
        max_concurrent_jobs=pick("max_concurrent_jobs", rl.max_concurrent_jobs),
        max_time_limit_seconds=pick(
            "max_time_limit_seconds", glob.max_job_time_limit_seconds
        ),
        max_gpu_memory_mb=pick("max_gpu_memory_mb", rl.max_gpu_memory_mb),
        max_ram_mb=pick("max_ram_mb", rl.max_ram_mb),
        max_cpu_threads=pick("max_cpu_threads", rl.max_cpu_threads),
    )


async def effective(session: AsyncSession, user_id: int) -> EffectiveUserPolicy:
    user = await session.get(User, user_id)
    ov = await session.get(UserPolicy, user_id)
    role = user.role if user is not None else UserRole.mahasiswa
    return _merge(policy_svc.get(), ov, role)


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
    users = (
        await session.scalars(select(User).where(User.id.in_(user_ids)))
    ).all()
    role_by_id = {u.id: u.role for u in users}
    return {
        uid: _merge(glob, by_id.get(uid), role_by_id.get(uid, UserRole.mahasiswa))
        for uid in user_ids
    }


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
