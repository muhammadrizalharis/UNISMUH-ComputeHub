"""Skema laporan penggunaan resource (admin)."""

from __future__ import annotations

from app.schemas.monitoring import GpuOut
from pydantic import BaseModel


class SystemReport(BaseModel):
    hostname: str
    os: str
    cpu_cores: int
    cpu_physical_cores: int
    cpu_percent: float
    load_avg: list[float]
    memory_total_mb: float
    memory_used_mb: float
    memory_available_mb: float
    swap_total_mb: float
    swap_used_mb: float
    disk_total_gb: float
    disk_used_gb: float
    disk_percent: float
    gpus: list[GpuOut]
    driver_version: str
    cuda_version: str
    uptime_seconds: float
    boot_time: str
    platform_users: int
    now: str


class GpuProcess(BaseModel):
    gpu_index: int
    pid: int
    username: str
    name: str
    command: str
    vram_mb: float
    workload: str = ""
    is_platform_job: bool = False
    job_id: int | None = None


class SystemProcess(BaseModel):
    pid: int
    username: str
    name: str
    cpu_percent: float
    cpu_cores_eq: float
    memory_mb: float
    command: str = ""
    workload: str = ""


class OsUserUsage(BaseModel):
    username: str
    cpu_percent: float
    cpu_cores_eq: float
    memory_mb: float
    vram_mb: float
    gpu_indices: list[int]
    processes: int
    activity: str


class RunningJob(BaseModel):
    id: int
    name: str
    owner_name: str
    owner_email: str
    role: str
    gpu_index: int | None
    pid: int | None
    source_type: str
    runtime_seconds: float | None
    peak_ram_mb: float | None
    peak_vram_mb: float | None
    avg_gpu_util_percent: float | None
    started_at: str | None


class PlatformUserUsage(BaseModel):
    user_id: int
    name: str
    email: str
    role: str
    jobs_total: int
    jobs_succeeded: int
    jobs_failed: int
    jobs_cancelled: int
    jobs_running: int
    jobs_queued: int
    gpu_seconds_24h: float
    gpu_seconds_total: float
    peak_ram_mb: float | None
    peak_vram_mb: float | None
    peak_cpu_percent: float | None
    last_activity: str | None


class FullReport(BaseModel):
    system: SystemReport
    gpu_processes: list[GpuProcess]
    top_processes: list[SystemProcess]
    os_users: list[OsUserUsage]
    running_jobs: list[RunningJob]
    users: list[PlatformUserUsage]
