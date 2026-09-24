"""Schemas monitoring (CPU/RAM/GPU)."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, model_validator

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
    cpu_percent: float | None
    memory_used_mb: float | None
    memory_total_mb: float | None
    gpu_index: int | None
    gpu_util_percent: float | None
    gpu_mem_used_mb: float | None
    gpu_mem_total_mb: float | None
    gpu_temperature_c: float | None
    gpu_power_w: float | None
    unavailable_metrics: list[str] | None = None

    @model_validator(mode="after")
    def mask_unavailable(self) -> ResourceSampleOut:
        measured = {
            "cpu_percent", "memory_used_mb", "memory_total_mb", "gpu_util_percent",
            "gpu_mem_used_mb", "gpu_mem_total_mb", "gpu_temperature_c", "gpu_power_w",
        }
        for field_name in measured.intersection(self.unavailable_metrics or []):
            setattr(self, field_name, None)
        return self


class MonitoringOverview(BaseModel):
    system: SystemSnapshot
    jobs_queued: int
    jobs_running: int
    jobs_succeeded: int
    jobs_failed: int
    enforce_gpu: bool
    max_concurrent_jobs: int
    interactive_sessions: int = 0
    # Untuk mahasiswa/dosen: posisi job miliknya yang terdepan di antrian global
    # (1 = paling depan) dan total job di antrian. None untuk admin / tanpa antrian.
    queue_position: int | None = None
    queue_total: int | None = None
