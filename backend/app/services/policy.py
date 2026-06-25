"""Policy runtime (admin-editable) + estimasi batas waktu otomatis.

- Sumber kebenaran kuota/limit saat runtime = baris SystemSetting (id=1).
- Nilai awal diisi dari default config.py.
- Di-cache di memori; di-refresh saat startup & saat admin update.
- HANYA admin yang boleh mengubah (lihat router admin). Mahasiswa tidak.
"""

from __future__ import annotations

import dataclasses

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.setting import SystemSetting
from app.models.user import UserRole

logger = get_logger(__name__)

FIELDS = (
    "enforce_gpu",
    "max_concurrent_jobs",
    "student_max_concurrent_jobs",
    "student_daily_gpu_seconds_quota",
    "default_job_time_limit_seconds",
    "min_job_time_limit_seconds",
    "max_job_time_limit_seconds",
    "runtime_safety_factor",
    "student_max_gpu_memory_mb",
    "student_max_ram_mb",
    "student_max_cpu_threads",
    "dosen_max_concurrent_jobs",
    "dosen_daily_gpu_seconds_quota",
    "dosen_max_gpu_memory_mb",
    "dosen_max_ram_mb",
    "dosen_max_cpu_threads",
    "admin_max_concurrent_jobs",
    "admin_daily_gpu_seconds_quota",
    "admin_max_gpu_memory_mb",
    "admin_max_ram_mb",
    "admin_max_cpu_threads",
    "auto_pip_install",
)


@dataclasses.dataclass
class Policy:
    enforce_gpu: bool
    max_concurrent_jobs: int
    student_max_concurrent_jobs: int
    student_daily_gpu_seconds_quota: int
    default_job_time_limit_seconds: int
    min_job_time_limit_seconds: int
    max_job_time_limit_seconds: int
    runtime_safety_factor: float
    student_max_gpu_memory_mb: float
    student_max_ram_mb: float
    student_max_cpu_threads: int
    dosen_max_concurrent_jobs: int
    dosen_daily_gpu_seconds_quota: int
    dosen_max_gpu_memory_mb: float
    dosen_max_ram_mb: float
    dosen_max_cpu_threads: int
    admin_max_concurrent_jobs: int
    admin_daily_gpu_seconds_quota: int
    admin_max_gpu_memory_mb: float
    admin_max_ram_mb: float
    admin_max_cpu_threads: int
    auto_pip_install: bool

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class RoleLimits:
    """Plafon resource efektif untuk satu peran (0 = tanpa batas)."""

    max_concurrent_jobs: int
    daily_gpu_seconds_quota: int
    max_gpu_memory_mb: float
    max_ram_mb: float
    max_cpu_threads: int


def _defaults() -> dict:
    return {
        "enforce_gpu": settings.ENFORCE_GPU,
        "max_concurrent_jobs": settings.MAX_CONCURRENT_JOBS,
        "student_max_concurrent_jobs": settings.STUDENT_MAX_CONCURRENT_JOBS,
        "student_daily_gpu_seconds_quota": settings.STUDENT_DAILY_GPU_SECONDS_QUOTA,
        "default_job_time_limit_seconds": settings.DEFAULT_JOB_TIME_LIMIT_SECONDS,
        "min_job_time_limit_seconds": settings.MIN_JOB_TIME_LIMIT_SECONDS,
        "max_job_time_limit_seconds": settings.STUDENT_MAX_TIME_LIMIT_SECONDS,
        "runtime_safety_factor": settings.RUNTIME_SAFETY_FACTOR,
        "student_max_gpu_memory_mb": settings.STUDENT_MAX_GPU_MEMORY_MB,
        "student_max_ram_mb": settings.STUDENT_MAX_RAM_MB,
        "student_max_cpu_threads": settings.STUDENT_MAX_CPU_THREADS,
        "dosen_max_concurrent_jobs": settings.DOSEN_MAX_CONCURRENT_JOBS,
        "dosen_daily_gpu_seconds_quota": settings.DOSEN_DAILY_GPU_SECONDS_QUOTA,
        "dosen_max_gpu_memory_mb": settings.DOSEN_MAX_GPU_MEMORY_MB,
        "dosen_max_ram_mb": settings.DOSEN_MAX_RAM_MB,
        "dosen_max_cpu_threads": settings.DOSEN_MAX_CPU_THREADS,
        "admin_max_concurrent_jobs": settings.ADMIN_MAX_CONCURRENT_JOBS,
        "admin_daily_gpu_seconds_quota": settings.ADMIN_DAILY_GPU_SECONDS_QUOTA,
        "admin_max_gpu_memory_mb": settings.ADMIN_MAX_GPU_MEMORY_MB,
        "admin_max_ram_mb": settings.ADMIN_MAX_RAM_MB,
        "admin_max_cpu_threads": settings.ADMIN_MAX_CPU_THREADS,
        "auto_pip_install": settings.AUTO_PIP_INSTALL,
    }


_cache: Policy | None = None


def _from_row(row: SystemSetting) -> Policy:
    return Policy(**{f: getattr(row, f) for f in FIELDS})


async def ensure_loaded(session: AsyncSession) -> Policy:
    """Buat baris bila belum ada, lalu isi cache. Dipanggil saat startup."""
    global _cache
    row = await session.get(SystemSetting, 1)
    if row is None:
        row = SystemSetting(id=1, **_defaults())
        session.add(row)
        await session.commit()
        logger.info("SystemSetting awal dibuat dari default config.")
    _cache = _from_row(row)
    return _cache


def get() -> Policy:
    """Snapshot policy saat ini (fallback ke default config bila belum loaded)."""
    return _cache if _cache is not None else Policy(**_defaults())


def role_limits(role: UserRole, is_superadmin: bool = False) -> RoleLimits:
    """Plafon resource GLOBAL untuk satu peran (0 = tanpa batas).

    Super admin = bebas (semua 0). Mahasiswa memakai plafon global student_*
    (override per-user diterapkan terpisah lewat user_policy). Dosen & admin
    biasa memakai plafon global masing-masing.
    """
    if is_superadmin:
        return RoleLimits(0, 0, 0.0, 0.0, 0)
    p = get()
    if role == UserRole.mahasiswa:
        return RoleLimits(
            p.student_max_concurrent_jobs,
            p.student_daily_gpu_seconds_quota,
            p.student_max_gpu_memory_mb,
            p.student_max_ram_mb,
            p.student_max_cpu_threads,
        )
    if role == UserRole.dosen:
        return RoleLimits(
            p.dosen_max_concurrent_jobs,
            p.dosen_daily_gpu_seconds_quota,
            p.dosen_max_gpu_memory_mb,
            p.dosen_max_ram_mb,
            p.dosen_max_cpu_threads,
        )
    if role == UserRole.admin:
        return RoleLimits(
            p.admin_max_concurrent_jobs,
            p.admin_daily_gpu_seconds_quota,
            p.admin_max_gpu_memory_mb,
            p.admin_max_ram_mb,
            p.admin_max_cpu_threads,
        )
    return RoleLimits(0, 0, 0.0, 0.0, 0)


async def update(session: AsyncSession, changes: dict) -> Policy:
    """Update sebagian field policy (admin). Mengembalikan policy terbaru."""
    global _cache
    row = await session.get(SystemSetting, 1)
    if row is None:
        row = SystemSetting(id=1, **_defaults())
        session.add(row)
    for key, value in changes.items():
        if key in FIELDS and value is not None:
            setattr(row, key, value)
    await session.commit()
    _cache = _from_row(row)
    logger.info("Policy diperbarui admin: %s", list(changes.keys()))
    return _cache


def compute_time_limit(predicted_runtime: float | None) -> int:
    """Hitung batas waktu OTOMATIS dari estimasi durasi.

    - Ada riwayat -> estimasi * safety_factor.
    - Belum ada riwayat -> default policy.
    Selalu dibatasi [min, max] policy (admin yang menentukan plafon).
    """
    p = get()
    if predicted_runtime and predicted_runtime > 0:
        value = int(round(predicted_runtime * p.runtime_safety_factor))
    else:
        value = p.default_job_time_limit_seconds
    return max(p.min_job_time_limit_seconds, min(value, p.max_job_time_limit_seconds))
