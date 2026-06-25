"""Scheduler in-process (asyncio) yang GPU-aware.

Alur: job `queued` -> tunggu GPU bebas -> jalankan di GPU (executor) ->
update status + runtime aktual. Tanpa Redis/Celery (cocok untuk user non-admin).

GPU-aware:
  - Hanya dispatch bila ada GPU yang bebas (tidak dipakai job platform lain &
    VRAM cukup).
  - Bila ENFORCE_GPU dan tidak ada GPU sama sekali, job tetap `queued`
    (tidak pernah jatuh ke CPU).
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.job import TERMINAL_STATUSES, Job, JobSource, JobStatus
from app.models.user import User, UserRole
from app.services import gpu as gpu_svc
from app.services import policy as policy_svc
from app.services import quota as quota_svc
from app.services import reservations
from app.services import user_policy as user_policy_svc
from app.services.executor import executor
from app.services.monitor import JobSampler

logger = get_logger(__name__)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclasses.dataclass
class _RunSpec:
    command: str
    working_dir: str
    log_path: str
    source_type: JobSource
    repo_url: str | None
    repo_ref: str | None
    time_limit_seconds: int | None
    auto_install: bool
    inline_code: str | None
    cpu_threads: int = 0
    max_ram_mb: float = 0.0
    max_vram_mb: float = 0.0


class JobScheduler:
    def __init__(self) -> None:
        self._loop_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._running: dict[int, asyncio.Task] = {}
        self._busy_gpus: set[int] = set()
        self._warned_no_gpu = False

    # ----------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self._loop_task is not None:
            return
        settings.jobs_path.mkdir(parents=True, exist_ok=True)
        await self._recover_orphans()
        self._stop.clear()
        self._loop_task = asyncio.create_task(self._run_loop(), name="job-scheduler")
        pol = policy_svc.get()
        logger.info(
            "JobScheduler jalan (interval %.0fs, max %d job paralel, enforce_gpu=%s).",
            settings.SCHEDULER_INTERVAL_SECONDS,
            pol.max_concurrent_jobs,
            pol.enforce_gpu,
        )

    async def _recover_orphans(self) -> None:
        """Tandai job `running` yatim (akibat server restart/crash) sebagai gagal.

        Saat proses uvicorn mati, subprocess job ikut hilang sehingga tidak mungkin
        dilanjutkan. Tanpa rekonsiliasi, job akan macet selamanya di status
        `running`. Di sini kita tandai gagal + beri pesan jelas agar bisa di-submit
        ulang.
        """
        now = _utcnow()
        async with AsyncSessionLocal() as session:
            orphans = (
                await session.execute(
                    select(Job).where(Job.status == JobStatus.running)
                )
            ).scalars().all()
            if not orphans:
                return
            for job in orphans:
                job.status = JobStatus.failed
                job.finished_at = now
                started = job.started_at
                if started is not None:
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=dt.timezone.utc)
                    job.actual_runtime_seconds = (now - started).total_seconds()
                if job.exit_code is None:
                    job.exit_code = -1
                job.error_message = (
                    "Terhenti karena server dimulai ulang (proses eksekusi hilang). "
                    "Silakan submit ulang."
                )
            await session.commit()
            logger.warning(
                "Recovery: %d job 'running' yatim ditandai gagal saat startup.",
                len(orphans),
            )

    async def stop(self) -> None:
        self._stop.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        # Hentikan job yang sedang berjalan (akan ditandai cancelled).
        for task in list(self._running.values()):
            task.cancel()
        if self._running:
            await asyncio.gather(*self._running.values(), return_exceptions=True)
        self._running.clear()
        self._busy_gpus.clear()

    # ----------------------------------------------------------- status
    @property
    def running_job_ids(self) -> list[int]:
        return list(self._running.keys())

    @property
    def busy_gpus(self) -> list[int]:
        return sorted(self._busy_gpus)

    # ----------------------------------------------------------- main loop
    async def _run_loop(self) -> None:
        interval = max(1.0, settings.SCHEDULER_INTERVAL_SECONDS)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scheduler tick error: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        if not settings.ENABLE_JOB_EXECUTION:
            return

        pol = policy_svc.get()
        free_slots = pol.max_concurrent_jobs - len(self._running)
        if free_slots <= 0:
            return

        # ENFORCEMENT: tanpa GPU, jangan jalankan apa pun.
        if pol.enforce_gpu and not gpu_svc.gpu_available():
            if not self._warned_no_gpu:
                logger.warning(
                    "Tidak ada GPU terlihat -> job ditahan di antrian "
                    "(CPU tidak diizinkan)."
                )
                self._warned_no_gpu = True
            return
        self._warned_no_gpu = False

        async with AsyncSessionLocal() as session:
            candidates = (
                await session.execute(
                    select(
                        Job.id,
                        Job.user_id,
                        Job.requested_gpu_memory_mb,
                        User.role,
                        User.email,
                    )
                    .select_from(Job)
                    .join(User, Job.user_id == User.id)
                    .where(Job.status == JobStatus.queued)
                    .order_by(Job.priority.desc(), Job.submitted_at.asc())
                    .limit(50)
                )
            ).all()

            # Job berjalan per user (SEMUA peran) -> kuota konkurensi.
            run_rows = (
                await session.execute(
                    select(Job.user_id, func.count())
                    .select_from(Job)
                    .where(Job.status == JobStatus.running)
                    .group_by(Job.user_id)
                )
            ).all()

            # Pemakaian GPU 24 jam per user kandidat (untuk kuota harian).
            cand_ids = {uid for (_jid, uid, _mem, _r, _s) in candidates}
            used_map = await quota_svc.gpu_seconds_used_map(session, cand_ids)
            student_ids = {
                uid
                for (_jid, uid, _mem, c_role, _s) in candidates
                if c_role == UserRole.mahasiswa
            }
            eff_map = await user_policy_svc.effective_map(session, student_ids)

        running_by_user: dict[int, int] = {uid: cnt for uid, cnt in run_rows}
        # is_superadmin = property (bukan kolom) -> hitung dari email vs FIRST_ADMIN.
        super_email = (settings.FIRST_ADMIN_EMAIL or "").strip().lower()

        for job_id, user_id, req_mem, role, email in candidates:
            if free_slots <= 0:
                break
            if job_id in self._running:
                continue

            # Kuota konkurensi + harian per peran. Super admin BEBAS.
            is_super = bool(super_email) and (email or "").strip().lower() == super_email
            if not is_super:
                if role == UserRole.mahasiswa:
                    eff = eff_map.get(user_id)
                    limit = (
                        eff.max_concurrent_jobs
                        if eff
                        else pol.student_max_concurrent_jobs
                    )
                    quota = (
                        eff.daily_gpu_seconds_quota
                        if eff
                        else pol.student_daily_gpu_seconds_quota
                    )
                else:
                    rl = policy_svc.role_limits(role)
                    limit = rl.max_concurrent_jobs
                    quota = rl.daily_gpu_seconds_quota
                if limit > 0 and running_by_user.get(user_id, 0) >= limit:
                    continue
                if quota > 0 and used_map.get(user_id, 0.0) >= quota:
                    continue

            min_free = req_mem if req_mem and req_mem > 0 else None
            gpu_index = gpu_svc.pick_free_gpu(
                min_free_mb=min_free,
                busy_indices=self._busy_gpus | reservations.reserved_indices(),
            )
            if gpu_index is None:
                # Tidak ada GPU bebas yang cukup -> tunggu tick berikutnya.
                break

            self._busy_gpus.add(gpu_index)
            self._running[job_id] = asyncio.create_task(
                self._dispatch(job_id, gpu_index), name=f"job-{job_id}"
            )
            free_slots -= 1
            running_by_user[user_id] = running_by_user.get(user_id, 0) + 1

    # ----------------------------------------------------------- dispatch
    async def _dispatch(self, job_id: int, gpu_index: int) -> None:
        sampler: JobSampler | None = None
        stopped = False
        cap_ram_mb = 0.0
        cap_vram_mb = 0.0
        log_path: str | None = None

        async def stop_sampler() -> dict:
            nonlocal stopped
            if sampler is None or stopped:
                return {}
            stopped = True
            return await sampler.stop()

        def on_start(pid: int) -> None:
            nonlocal sampler
            sampler = JobSampler(
                job_id,
                pid,
                gpu_index,
                settings.JOB_SAMPLE_INTERVAL_SECONDS,
                max_ram_mb=cap_ram_mb,
                max_vram_mb=cap_vram_mb,
                log_path=log_path,
            )
            sampler.start()

        try:
            spec = await self._mark_running(job_id, gpu_index)
            if spec is None:
                return  # job hilang / bukan queued lagi
            cap_ram_mb = spec.max_ram_mb
            cap_vram_mb = spec.max_vram_mb
            log_path = spec.log_path

            result = await executor.run_job(
                job_id=job_id,
                command=spec.command,
                working_dir=spec.working_dir,
                gpu_index=gpu_index,
                log_path=spec.log_path,
                source_type=spec.source_type,
                repo_url=spec.repo_url,
                repo_ref=spec.repo_ref,
                time_limit_seconds=spec.time_limit_seconds,
                auto_install=spec.auto_install,
                inline_code=spec.inline_code,
                cpu_threads=spec.cpu_threads,
                on_start=on_start,
            )
            aggregates = await stop_sampler()
            await self._mark_finished(job_id, result, aggregates)

        except asyncio.CancelledError:
            await stop_sampler()
            await self._mark_cancelled(job_id)
            raise
        except Exception as exc:  # noqa: BLE001
            await stop_sampler()
            logger.exception("Dispatch job #%d error", job_id)
            await self._mark_failed(job_id, f"Scheduler error: {exc!r}")
        finally:
            self._busy_gpus.discard(gpu_index)
            self._running.pop(job_id, None)

    async def _mark_running(self, job_id: int, gpu_index: int) -> _RunSpec | None:
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status != JobStatus.queued:
                return None

            job_dir = settings.jobs_path / f"job_{job_id}"
            job_dir.mkdir(parents=True, exist_ok=True)
            log_path = str(job_dir / "job.log")
            working_dir = job.working_dir or str(job_dir)
            Path(working_dir).mkdir(parents=True, exist_ok=True)

            job.status = JobStatus.running
            job.gpu_index = gpu_index
            job.started_at = _utcnow()
            job.working_dir = working_dir
            job.log_path = log_path
            spec = _RunSpec(
                command=job.command,
                working_dir=working_dir,
                log_path=log_path,
                source_type=job.source_type,
                repo_url=job.repo_url,
                repo_ref=job.repo_ref,
                time_limit_seconds=job.time_limit_seconds,
                auto_install=job.auto_install,
                inline_code=job.inline_code,
                cpu_threads=job.cpu_threads,
                max_ram_mb=job.max_ram_mb,
                max_vram_mb=job.requested_gpu_memory_mb,
            )
            await session.commit()
            logger.info("Job #%d START di GPU %d.", job_id, gpu_index)
            return spec

    async def _mark_finished(
        self, job_id: int, result, aggregates: dict | None = None
    ) -> None:
        aggregates = aggregates or {}
        kill_reason = aggregates.get("kill_reason")
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            job.status = JobStatus.failed if kill_reason else result.status
            job.exit_code = result.exit_code
            job.pid = result.pid
            job.started_at = result.started_at
            job.finished_at = result.finished_at
            job.actual_runtime_seconds = (
                result.finished_at - result.started_at
            ).total_seconds()
            job.error_message = kill_reason or result.error_message
            job.peak_ram_mb = aggregates.get("peak_ram_mb")
            job.peak_vram_mb = aggregates.get("peak_vram_mb")
            job.avg_gpu_util_percent = aggregates.get("avg_gpu_util_percent")
            await session.commit()
        logger.info(
            "Job #%d %s (exit=%s, %.1fs, peakVRAM=%s).",
            job_id,
            result.status.value,
            result.exit_code,
            (result.finished_at - result.started_at).total_seconds(),
            aggregates.get("peak_vram_mb"),
        )

    async def _mark_cancelled(self, job_id: int) -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status in TERMINAL_STATUSES:
                return
            now = _utcnow()
            job.status = JobStatus.cancelled
            job.finished_at = now
            if job.started_at is not None:
                job.actual_runtime_seconds = (now - job.started_at).total_seconds()
            job.error_message = "Job dibatalkan."
            await session.commit()
        logger.info("Job #%d cancelled.", job_id)

    async def _mark_failed(self, job_id: int, message: str) -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status in TERMINAL_STATUSES:
                return
            job.status = JobStatus.failed
            job.finished_at = _utcnow()
            job.error_message = message
            await session.commit()

    # ----------------------------------------------------------- cancel API
    async def cancel_job(self, job_id: int) -> bool:
        """Batalkan job yang sedang berjalan (task di-cancel)."""
        task = self._running.get(job_id)
        if task is None:
            return False
        task.cancel()
        return True


# Instance global.
scheduler = JobScheduler()
