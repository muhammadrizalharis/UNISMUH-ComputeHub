"""Prediksi runtime job.

Strategi: rata-rata `actual_runtime_seconds` dari job SUKSES dengan nama
(signature) SAMA. Bila belum ada riwayat nama itu -> kembalikan None
(durasi belum diketahui). TIDAK memakai rata-rata global, karena memakai
durasi job lain yang tak berkaitan untuk menetapkan timeout itu berbahaya
(job baru yang berat bisa dihentikan terlalu cepat). Untuk job tanpa riwayat,
batas waktu memakai DEFAULT dari policy admin.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus

# Berapa banyak job terakhir yang dipakai untuk rata-rata.
_WINDOW = 10


async def predict_runtime(session: AsyncSession, name: str) -> float | None:
    """Perkiraan durasi (detik) berdasarkan riwayat NAMA yang sama; None bila belum ada."""
    subq = (
        select(Job.actual_runtime_seconds)
        .where(
            Job.name == name,
            Job.status == JobStatus.succeeded,
            Job.actual_runtime_seconds.is_not(None),
        )
        .order_by(Job.finished_at.desc())
        .limit(_WINDOW)
        .subquery()
    )
    avg_named = await session.scalar(select(func.avg(subq.c.actual_runtime_seconds)))
    return float(avg_named) if avg_named is not None else None
