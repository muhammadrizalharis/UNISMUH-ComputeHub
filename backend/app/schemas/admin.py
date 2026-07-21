"""Schemas pengaturan sistem (policy) untuk admin."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
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
    assistant_model_student: str
    assistant_model_dosen: str
    assistant_model_admin: str
    assistant_model_vision: str
    announcement_text: str
    announcement_level: str


class SettingsUpdate(BaseModel):
    enforce_gpu: bool | None = None
    max_concurrent_jobs: int | None = Field(default=None, ge=1, le=64)
    student_max_concurrent_jobs: int | None = Field(default=None, ge=1, le=32)
    student_daily_gpu_seconds_quota: int | None = Field(default=None, ge=0)
    default_job_time_limit_seconds: int | None = Field(default=None, ge=10)
    min_job_time_limit_seconds: int | None = Field(default=None, ge=10)
    max_job_time_limit_seconds: int | None = Field(default=None, ge=10)
    runtime_safety_factor: float | None = Field(default=None, ge=1.0, le=10.0)
    student_max_gpu_memory_mb: float | None = Field(default=None, ge=0)
    student_max_ram_mb: float | None = Field(default=None, ge=0)
    student_max_cpu_threads: int | None = Field(default=None, ge=0, le=256)
    dosen_max_concurrent_jobs: int | None = Field(default=None, ge=0, le=32)
    dosen_daily_gpu_seconds_quota: int | None = Field(default=None, ge=0)
    dosen_max_gpu_memory_mb: float | None = Field(default=None, ge=0)
    dosen_max_ram_mb: float | None = Field(default=None, ge=0)
    dosen_max_cpu_threads: int | None = Field(default=None, ge=0, le=256)
    admin_max_concurrent_jobs: int | None = Field(default=None, ge=0, le=64)
    admin_daily_gpu_seconds_quota: int | None = Field(default=None, ge=0)
    admin_max_gpu_memory_mb: float | None = Field(default=None, ge=0)
    admin_max_ram_mb: float | None = Field(default=None, ge=0)
    admin_max_cpu_threads: int | None = Field(default=None, ge=0, le=256)
    auto_pip_install: bool | None = None
    assistant_model_student: str | None = Field(default=None, max_length=128)
    assistant_model_dosen: str | None = Field(default=None, max_length=128)
    assistant_model_admin: str | None = Field(default=None, max_length=128)
    assistant_model_vision: str | None = Field(default=None, max_length=128)
    announcement_text: str | None = Field(default=None, max_length=2000)
    announcement_level: str | None = Field(default=None, pattern="^(info|warning|danger)$")


class EffectivePolicyOut(BaseModel):
    daily_gpu_seconds_quota: int
    max_concurrent_jobs: int
    max_time_limit_seconds: int
    max_gpu_memory_mb: float
    max_ram_mb: float
    max_cpu_threads: int
    max_storage_mb: float
    assistant_model: str


class UserPolicyOverrides(BaseModel):
    daily_gpu_seconds_quota: int | None = None
    max_concurrent_jobs: int | None = None
    max_time_limit_seconds: int | None = None
    max_gpu_memory_mb: float | None = None
    max_ram_mb: float | None = None
    max_cpu_threads: int | None = None
    max_storage_mb: float | None = None
    assistant_model: str | None = None


class UserPolicyOut(BaseModel):
    user_id: int
    overrides: UserPolicyOverrides
    effective: EffectivePolicyOut


class UserPolicyUpdate(BaseModel):
    daily_gpu_seconds_quota: int | None = Field(default=None, ge=0)
    max_concurrent_jobs: int | None = Field(default=None, ge=0)
    max_time_limit_seconds: int | None = Field(default=None, ge=0)
    max_gpu_memory_mb: float | None = Field(default=None, ge=0)
    max_ram_mb: float | None = Field(default=None, ge=0)
    max_cpu_threads: int | None = Field(default=None, ge=0, le=256)
    max_storage_mb: float | None = Field(default=None, ge=0)
    assistant_model: str | None = Field(default=None, max_length=128)


class UserUsageOut(BaseModel):
    user_id: int
    name: str
    email: str
    role: str
    jobs_total: int
    jobs_succeeded: int
    jobs_failed: int
    gpu_seconds_24h: float
    gpu_seconds_total: float
