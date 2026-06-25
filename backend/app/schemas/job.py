"""Schemas Job."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobSource, JobStatus


class JobCreate(BaseModel):
    # Nama opsional (auto dari sumber bila kosong).
    name: str | None = Field(default=None, max_length=255)

    # Sumber program (default 'paste' = tempel kode).
    source_type: JobSource = Field(default=JobSource.paste)
    code: str | None = Field(default=None, description="Kode (untuk source_type=paste)")
    repo_url: str | None = Field(default=None, description="URL repo GitHub (git)")
    repo_ref: str | None = Field(default=None, description="Branch/tag/commit (opsional)")

    # Perintah opsional. Kosong -> sistem deteksi entrypoint otomatis.
    # Untuk mahasiswa selalu otomatis (tidak bisa diisi manual).
    command: str | None = Field(default=None, description="Opsional (dosen/admin)")
    working_dir: str | None = Field(default=None)

    # ---- DIABAIKAN untuk mahasiswa (diatur otomatis / oleh admin) ----
    priority: int | None = Field(default=None, ge=0, le=100)
    requested_gpu_memory_mb: float | None = Field(default=None, ge=0)
    time_limit_seconds: int | None = Field(default=None, ge=1)
    auto_install: bool | None = Field(default=None)


class JobUpdate(BaseModel):
    priority: int | None = Field(default=None, ge=0, le=100)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    command: str
    working_dir: str | None

    source_type: JobSource
    repo_url: str | None
    repo_ref: str | None
    upload_name: str | None
    inline_code: str | None

    status: JobStatus
    priority: int

    gpu_index: int | None
    requested_gpu_memory_mb: float
    max_ram_mb: float = 0.0
    cpu_threads: int = 0
    time_limit_seconds: int | None
    auto_install: bool
    is_interactive: bool = False

    pid: int | None
    exit_code: int | None
    error_message: str | None

    submitted_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None

    estimated_runtime_seconds: float | None
    actual_runtime_seconds: float | None

    # Diukur oleh sistem saat berjalan
    peak_ram_mb: float | None
    peak_vram_mb: float | None
    avg_gpu_util_percent: float | None
    peak_cpu_percent: float | None = None

    user_id: int
    # Pemilik (untuk laporan/riwayat admin)
    owner_name: str = ""
    owner_email: str = ""


class QueueItem(BaseModel):
    """Posisi & perkiraan waktu mulai sebuah job di antrian."""

    job_id: int
    name: str
    user_id: int
    owner_name: str
    position: int
    priority: int
    estimated_runtime_seconds: float
    eta_seconds: float  # perkiraan detik sampai job mulai jalan


class UsageOut(BaseModel):
    """Pemakaian GPU (rolling 24 jam) & kuota harian."""

    window_hours: int
    used_seconds: float
    quota_seconds: int  # 0 = tanpa batas
    remaining_seconds: float | None  # None bila tanpa batas
    quota_enabled: bool
