"""Router system: health, info, capabilities."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import get_current_active_user
from app.core.config import settings
from app.models.user import User
from app.services import gpu as gpu_svc
from app.services import policy as policy_svc
from app.services.scheduler import scheduler

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Health check publik (untuk uptime probe)."""
    return {"status": "ok", "service": settings.PROJECT_NAME, "version": __version__}


@router.get("/info")
async def info() -> dict:
    """Info ringkas aplikasi (publik)."""
    gpus = gpu_svc.list_gpus()
    return {
        "project": settings.PROJECT_NAME,
        "version": __version__,
        "env": settings.ENV,
        "database": "sqlite" if settings.is_sqlite else "external",
        "gpu_available": len(gpus) > 0,
        "gpu_count": len(gpus),
    }


@router.get("/capabilities")
async def capabilities(_: User = Depends(get_current_active_user)) -> dict:
    """Detail kapabilitas & kebijakan GPU (perlu login)."""
    gpus = gpu_svc.list_gpus()
    pol = policy_svc.get()
    return {
        "enforce_gpu": pol.enforce_gpu,
        "allow_cpu_fallback": settings.ALLOW_CPU_FALLBACK,
        "require_cuda_preflight": settings.REQUIRE_CUDA_PREFLIGHT,
        "gpu_min_free_memory_mb": settings.GPU_MIN_FREE_MEMORY_MB,
        "max_concurrent_jobs": pol.max_concurrent_jobs,
        "scheduler_mode": settings.SCHEDULER_MODE,
        "job_execution_enabled": settings.ENABLE_JOB_EXECUTION,
        "gpu_count": len(gpus),
        "gpus": [g.as_dict() for g in gpus],
        "busy_gpus": scheduler.busy_gpus,
        "running_jobs": scheduler.running_job_ids,
        "secret_key_safe": settings.is_secret_key_safe,
        "policy": {
            "student_max_concurrent_jobs": pol.student_max_concurrent_jobs,
            "student_max_gpu_memory_mb": pol.student_max_gpu_memory_mb,
            "student_max_time_limit_seconds": pol.max_job_time_limit_seconds,
            "student_daily_gpu_seconds_quota": pol.student_daily_gpu_seconds_quota,
            "default_time_limit_seconds": pol.default_job_time_limit_seconds,
            "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB,
            "auto_pip_install": pol.auto_pip_install,
            "dosen_default_priority": settings.DOSEN_DEFAULT_PRIORITY,
            "dosen_max_priority": settings.DOSEN_MAX_PRIORITY,
            "student_priority_locked": True,
            "allowed_git_hosts": sorted(settings.allowed_git_hosts),
        },
    }
