"""Schemas monitoring (CPU/RAM/GPU)."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.models.monitoring import SampleScope


class GpuOut(BaseModel):
    index: int
    name: str
    uuid: str = ""
    util_percent: float = 0.0
    mem_used_mb: float = 0.0
    mem_total_mb: float = 0.0
    mem_free_mb: float = 0.0
    temperature_c: float = 0.0
    power_w: float = 0.0


class SystemSnapshot(BaseModel):
    timestamp: dt.datetime
    cpu_percent: float
    cpu_cores: int
    memory_used_mb: float
    memory_total_mb: float
    gpu_available: bool
    gpus: list[GpuOut] = []


class ResourceSampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: dt.datetime
    scope: SampleScope
    job_id: int | None
    cpu_percent: float
    memory_used_mb: float
    memory_total_mb: float
    gpu_index: int | None
    gpu_util_percent: float
    gpu_mem_used_mb: float
    gpu_mem_total_mb: float
    gpu_temperature_c: float
    gpu_power_w: float


class MonitoringOverview(BaseModel):
    system: SystemSnapshot
    jobs_queued: int
    jobs_running: int
    jobs_succeeded: int
    jobs_failed: int
    enforce_gpu: bool
    max_concurrent_jobs: int
