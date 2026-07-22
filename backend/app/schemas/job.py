"""Schemas Job."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.job import JobDevice, JobSource, JobStatus


class JobCreate(BaseModel):
    # Nama opsional (auto dari sumber bila kosong).
    name: str | None = Field(default=None, max_length=255)

    # Sumber program (default 'paste' = tempel kode).
    source_type: JobSource = Field(default=JobSource.paste)
    code: str | None = Field(default=None, description="Kode (untuk source_type=paste)")
    repo_url: str | None = Field(default=None, description="URL repo GitHub (git)")
    repo_ref: str | None = Field(default=None, description="Branch/tag/commit (opsional)")

    # Device komputasi: 'gpu' (default) atau 'cpu' (mis. Random Forest/ML klasik).
    device: JobDevice = Field(default=JobDevice.gpu)

    # Versi Python (mode docker). None/kosong = default sistem (3.10).
    python_version: str | None = Field(default=None, max_length=16)

    # Perintah opsional. Kosong -> sistem deteksi entrypoint otomatis.
    # Untuk mahasiswa selalu otomatis (tidak bisa diisi manual).
    command: str | None = Field(default=None, description="Opsional (dosen/admin)")
    working_dir: str | None = Field(default=None)

    # ---- DIABAIKAN untuk mahasiswa (diatur otomatis / oleh admin) ----
    priority: int | None = Field(default=None, ge=0, le=100)
    requested_gpu_memory_mb: float | None = Field(default=None, ge=0)
    time_limit_seconds: int | None = Field(default=None, ge=1)
    auto_install: bool | None = Field(default=None)

    # Jadwal eksekusi (opsional, semua peran): tahan dispatch sampai waktu ini.
    scheduled_at: dt.datetime | None = Field(default=None)


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
    python_version: str | None = None

    status: JobStatus
    priority: int

    gpu_index: int | None
    requested_gpu_memory_mb: float
    device: JobDevice = JobDevice.gpu
    max_ram_mb: float = 0.0
    cpu_threads: int = 0
    time_limit_seconds: int | None
    auto_install: bool
    is_interactive: bool = False

    pid: int | None
    exit_code: int | None
    error_message: str | None

    submitted_at: dt.datetime
    scheduled_at: dt.datetime | None = None
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    deleted_at: dt.datetime | None = None

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
    owner_role: str = ""

    @field_validator("device", mode="before")
    @classmethod
    def _device_default(cls, v):  # noqa: ANN001
        """Baris lama (sebelum kolom device ada) bernilai NULL -> anggap 'gpu'."""
        return v if v is not None else JobDevice.gpu


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
    device: JobDevice = JobDevice.gpu
    waiting_reason: str | None = None  # 'gpu_full' / 'cpu_full' / None


class UsageOut(BaseModel):
    """Pemakaian GPU (rolling 24 jam) & kuota harian."""

    window_hours: int
    used_seconds: float
    quota_seconds: int  # 0 = tanpa batas
    remaining_seconds: float | None  # None bila tanpa batas
    quota_enabled: bool
