"""Router monitoring: snapshot CPU/RAM/GPU, overview, time-series."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_admin, require_authenticated
from app.core.config import settings
from app.core.database import get_db
from app.models.job import Job, JobStatus
from app.models.monitoring import ResourceSample, SampleScope
from app.models.user import User, UserRole
from app.schemas.monitoring import (
    GpuOut,
    MonitoringOverview,
    ResourceSampleOut,
    SystemSnapshot,
)
from app.services import gpu as gpu_svc
from app.services import policy as policy_svc
from app.services.interactive import kernel_manager
from app.services.monitor import system_snapshot
from app.services.queue import compute_queue_eta
from app.services.scheduler import scheduler

router = APIRouter()


@router.get("/system", response_model=SystemSnapshot)
async def get_system(
    _: int = Depends(require_authenticated),
) -> SystemSnapshot:
    return system_snapshot()


@router.get("/system/stream")
async def stream_system(
    _: int = Depends(require_authenticated),
) -> StreamingResponse:
    """Stream snapshot CPU/RAM/GPU sebagai SSE (real-time, push tiap N ms).

    Jauh lebih real-time daripada polling: 1 koneksi, server mendorong data terus.
    Hanya snapshot sistem (tanpa query DB) -> ringan & cepat (NVML).
    """
    interval = max(0.1, settings.MONITOR_STREAM_INTERVAL_MS / 1000.0)

    async def event_stream() -> AsyncIterator[str]:
        while True:
            snap = system_snapshot().model_dump(mode="json")
            yield f"data: {json.dumps(snap)}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # cegah buffering proxy (cloudflared)
        },
    )


@router.get("/gpus", response_model=list[GpuOut])
async def get_gpus(
    _: User = Depends(get_current_active_user),
) -> list[GpuOut]:
    return [GpuOut(**g.as_dict()) for g in gpu_svc.list_gpus()]


def _job_count(status: JobStatus, user_id: int | None):
    """Ekspresi SUM(CASE ...) untuk menghitung job berstatus tertentu dalam 1 query.

    Bila `user_id` diberikan -> hanya job milik user itu; bila None -> keseluruhan.
    Dipakai agar overview cukup SATU round-trip ke DB (endpoint sering di-poll).
    """
    cond = Job.status == status
    if user_id is not None:
        cond = and_(cond, Job.user_id == user_id)
    return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)


@router.get("/overview", response_model=MonitoringOverview)
async def get_overview(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> MonitoringOverview:
    # Mahasiswa & dosen: kartu "Berjalan" tetap menampilkan beban server
    # keseluruhan, sedangkan "Antri/Sukses/Gagal" hanya menghitung job miliknya.
    # Admin tetap melihat angka keseluruhan platform.
    is_admin = current_user.role == UserRole.admin
    own_id = None if is_admin else current_user.id

    # SATU query agregasi (hemat round-trip ke DB remote): "running" selalu
    # keseluruhan; "queued/succeeded/failed" per-user untuk non-admin.
    running, queued, succeeded, failed = (
        await session.execute(
            select(
                _job_count(JobStatus.running, None),
                _job_count(JobStatus.queued, own_id),
                _job_count(JobStatus.succeeded, own_id),
                _job_count(JobStatus.failed, own_id),
            )
        )
    ).one()

    queue_position: int | None = None
    queue_total: int | None = None
    if not is_admin and queued > 0:
        # Posisi job user dalam antrian global (konsisten dengan halaman Jobs).
        queue = await compute_queue_eta(session)
        queue_total = len(queue)
        mine = [q["position"] for q in queue if q["user_id"] == current_user.id]
        queue_position = min(mine) if mine else None

    pol = policy_svc.get()
    return MonitoringOverview(
        system=system_snapshot(),
        jobs_queued=int(queued),
        jobs_running=int(running),
        jobs_succeeded=int(succeeded),
        jobs_failed=int(failed),
        enforce_gpu=pol.enforce_gpu,
        max_concurrent_jobs=pol.max_concurrent_jobs,
        interactive_sessions=kernel_manager.active_count,
        queue_position=queue_position,
        queue_total=queue_total,
    )


@router.get("/interactive-sessions")
async def list_interactive_sessions(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    """Daftar sesi interaktif (kernel hidup) yang sedang aktif — admin saja."""
    sessions = kernel_manager.list_all()
    if not sessions:
        return []
    uids = {s["user_id"] for s in sessions}
    rows = (await session.scalars(select(User).where(User.id.in_(uids)))).all()
    umap = {u.id: u for u in rows}
    out: list[dict] = []
    for s in sessions:
        u = umap.get(s["user_id"])
        out.append({
            **s,
            "owner_name": (u.name if u else None),
            "owner_email": (u.email if u else None),
        })
    return out


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
