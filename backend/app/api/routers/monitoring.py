"""Router monitoring: snapshot CPU/RAM/GPU, overview, time-series."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.database import get_db
from app.models.job import Job, JobStatus
from app.models.monitoring import ResourceSample, SampleScope
from app.models.user import User
from app.schemas.monitoring import (
    GpuOut,
    MonitoringOverview,
    ResourceSampleOut,
    SystemSnapshot,
)
from app.services import gpu as gpu_svc
from app.services import policy as policy_svc
from app.services.monitor import system_snapshot
from app.services.scheduler import scheduler

router = APIRouter()


@router.get("/system", response_model=SystemSnapshot)
async def get_system(
    _: User = Depends(get_current_active_user),
) -> SystemSnapshot:
    return system_snapshot()


@router.get("/gpus", response_model=list[GpuOut])
async def get_gpus(
    _: User = Depends(get_current_active_user),
) -> list[GpuOut]:
    return [GpuOut(**g.as_dict()) for g in gpu_svc.list_gpus()]


async def _count(session: AsyncSession, status: JobStatus) -> int:
    return await session.scalar(
        select(func.count()).select_from(Job).where(Job.status == status)
    ) or 0


@router.get("/overview", response_model=MonitoringOverview)
async def get_overview(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> MonitoringOverview:
    return MonitoringOverview(
        system=system_snapshot(),
        jobs_queued=await _count(session, JobStatus.queued),
        jobs_running=await _count(session, JobStatus.running),
        jobs_succeeded=await _count(session, JobStatus.succeeded),
        jobs_failed=await _count(session, JobStatus.failed),
        enforce_gpu=policy_svc.get().enforce_gpu,
        max_concurrent_jobs=policy_svc.get().max_concurrent_jobs,
    )


@router.get("/samples", response_model=list[ResourceSampleOut])
async def get_samples(
    gpu_index: int | None = Query(default=None),
    limit: int = Query(500, ge=1, le=5000),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[ResourceSample]:
    stmt = (
        select(ResourceSample)
        .where(ResourceSample.scope == SampleScope.system)
        .order_by(ResourceSample.ts.desc())
    )
    if gpu_index is not None:
        stmt = stmt.where(ResourceSample.gpu_index == gpu_index)
    result = await session.scalars(stmt.limit(limit))
    return list(result.all())
