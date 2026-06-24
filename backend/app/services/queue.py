"""Estimasi antrian: posisi & perkiraan waktu mulai (ETA) tiap job queued.

Simulasi penjadwalan slot GPU:
  - Setiap GPU slot punya "waktu bebas" = sisa estimasi job yang sedang jalan.
  - Job queued (urut prioritas lalu waktu submit) ditempatkan ke slot yang
    paling cepat bebas; ETA = waktu tunggu sampai slot itu bebas.

Estimasi durasi tiap job memakai (berurutan): riwayat (estimated_runtime_seconds)
-> batas waktu (time_limit_seconds) -> default global.
"""

from __future__ import annotations

import datetime as dt
import heapq

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.job import Job, JobStatus
from app.models.user import User


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _estimate(job: Job) -> float:
    return float(
        job.estimated_runtime_seconds
        or job.time_limit_seconds
        or settings.DEFAULT_JOB_TIME_LIMIT_SECONDS
    )


async def compute_queue_eta(session: AsyncSession) -> list[dict]:
    slots = max(1, settings.MAX_CONCURRENT_JOBS)
    now = _utcnow()

    # Sisa waktu tiap job yang sedang berjalan.
    running = (
        await session.scalars(select(Job).where(Job.status == JobStatus.running))
    ).all()
    remaining: list[float] = []
    for job in running:
        elapsed = (now - job.started_at).total_seconds() if job.started_at else 0.0
        remaining.append(max(0.0, _estimate(job) - elapsed))
    while len(remaining) < slots:
        remaining.append(0.0)  # slot kosong = bebas sekarang
    heapq.heapify(remaining)

    rows = (
        await session.execute(
            select(Job, User.name)
            .join(User, Job.user_id == User.id)
            .where(Job.status == JobStatus.queued)
            .order_by(Job.priority.desc(), Job.submitted_at.asc())
        )
    ).all()

    out: list[dict] = []
    for position, (job, owner_name) in enumerate(rows, start=1):
        start_in = heapq.heappop(remaining)
        est = _estimate(job)
        out.append(
            {
                "job_id": job.id,
                "name": job.name,
                "user_id": job.user_id,
                "owner_name": owner_name,
                "position": position,
                "priority": job.priority,
                "estimated_runtime_seconds": est,
                "eta_seconds": start_in,
            }
        )
        heapq.heappush(remaining, start_in + est)
    return out
