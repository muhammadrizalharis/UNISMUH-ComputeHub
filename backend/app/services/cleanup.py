"""Pembersihan otomatis: hapus folder job lama & PDF peringatan lama.

Tujuan: menjaga disk server (bersama) tidak penuh. Hanya menyentuh artefak milik
platform sendiri (folder `_jobs/job_*` dan berkas di `_alerts/`), tidak pernah
menyentuh berkas user lain di server.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import shutil
import time

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.job import TERMINAL_STATUSES, Job
from app.models.monitoring import ResourceSample

logger = get_logger(__name__)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class CleanupService:
    """Tugas latar berkala untuk membersihkan artefak lama (retensi)."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return (
            settings.JOB_RETENTION_DAYS > 0
            or settings.ALERT_RETENTION_DAYS > 0
            or settings.MONITOR_RETENTION_DAYS > 0
        )

    async def start(self) -> None:
        if self._task is not None:
            return
        if not self.enabled:
            logger.info("CleanupService nonaktif (retensi 0).")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="cleanup-service")
        logger.info(
            "CleanupService jalan (job %d hari, alert %d hari, sampel %d hari, interval %.1f jam).",
            settings.JOB_RETENTION_DAYS,
            settings.ALERT_RETENTION_DAYS,
            settings.MONITOR_RETENTION_DAYS,
            settings.CLEANUP_INTERVAL_HOURS,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        interval = max(0.1, settings.CLEANUP_INTERVAL_HOURS) * 3600.0
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Cleanup error: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def run_once(self) -> dict:
        """Jalankan satu siklus pembersihan; kembalikan ringkasan jumlah."""
        jobs_removed = await self._cleanup_jobs()
        alerts_removed = self._cleanup_alerts()
        samples_removed = await self._cleanup_samples()
        if jobs_removed or alerts_removed or samples_removed:
            logger.info(
                "Cleanup: %d folder job, %d berkas peringatan & %d sampel monitoring dihapus.",
                jobs_removed,
                alerts_removed,
                samples_removed,
            )
        return {
            "jobs_removed": jobs_removed,
            "alerts_removed": alerts_removed,
            "samples_removed": samples_removed,
        }

    # ------------------------------------------------------------------ jobs
    async def _cleanup_jobs(self) -> int:
        days = settings.JOB_RETENTION_DAYS
        if days <= 0:
            return 0
        cutoff = _utcnow() - dt.timedelta(days=days)
        removed = 0
        known_ids: set[int] = set()
        async with AsyncSessionLocal() as session:
            all_ids = (await session.execute(select(Job.id))).scalars().all()
            known_ids = set(all_ids)

            stale = (
                await session.execute(
                    select(Job).where(
                        Job.status.in_(TERMINAL_STATUSES),
                        Job.finished_at.is_not(None),
                        Job.finished_at < cutoff,
                    )
                )
            ).scalars().all()
            for job in stale:
                job_dir = settings.jobs_path / f"job_{job.id}"
                if job_dir.exists():
                    shutil.rmtree(job_dir, ignore_errors=True)
                    removed += 1
                # Lepaskan referensi berkas yang sudah dihapus.
                job.log_path = None
                job.working_dir = None
            if stale:
                await session.commit()

        removed += self._cleanup_orphan_dirs(cutoff, known_ids)
        return removed

    def _cleanup_orphan_dirs(self, cutoff: dt.datetime, known_ids: set[int]) -> int:
        """Hapus folder `job_*` yatim (tak ada baris DB) yang sudah lewat retensi."""
        base = settings.jobs_path
        if not base.exists():
            return 0
        cutoff_ts = cutoff.timestamp()
        removed = 0
        for entry in base.iterdir():
            if not entry.is_dir() or not entry.name.startswith("job_"):
                continue
            suffix = entry.name[4:]
            if suffix.isdigit() and int(suffix) in known_ids:
                continue  # masih ada di DB -> jangan disentuh
            try:
                if entry.stat().st_mtime < cutoff_ts:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        return removed

    # ---------------------------------------------------------------- alerts
    def _cleanup_alerts(self) -> int:
        days = settings.ALERT_RETENTION_DAYS
        if days <= 0:
            return 0
        base = settings.alerts_path
        if not base.exists():
            return 0
        cutoff_ts = time.time() - days * 86400.0
        removed = 0
        for entry in base.iterdir():
            if not entry.is_file():
                continue
            try:
                if entry.stat().st_mtime < cutoff_ts:
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    # --------------------------------------------------------------- samples
    async def _cleanup_samples(self) -> int:
        """Hapus baris resource_samples lebih lama dari MONITOR_RETENTION_DAYS.

        Tabel ini diisi sampler tiap MONITOR_SAMPLE_INTERVAL_SECONDS sehingga
        tumbuh tanpa batas bila tak dipangkas (sampel scope `system` tak ikut
        terhapus via cascade job). Hanya menyentuh tabel milik platform.
        """
        days = settings.MONITOR_RETENTION_DAYS
        if days <= 0:
            return 0
        cutoff = _utcnow() - dt.timedelta(days=days)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(ResourceSample).where(ResourceSample.ts < cutoff)
            )
            await session.commit()
            return int(result.rowcount or 0)


# Instance global.
cleanup_service = CleanupService()
