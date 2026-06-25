"""Model Job (antrian & eksekusi di GPU)."""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class JobStatus(str, enum.Enum):
    queued = "queued"        # menunggu GPU bebas
    running = "running"      # sedang jalan di GPU
    succeeded = "succeeded"  # selesai exit code 0
    failed = "failed"        # gagal / preflight GPU gagal
    cancelled = "cancelled"  # dibatalkan user


class JobSource(str, enum.Enum):
    command = "command"    # jalankan perintah langsung (lanjutan/admin)
    git = "git"            # clone repo GitHub lalu jalankan
    upload = "upload"      # upload folder (ZIP) lalu jalankan di dalamnya
    notebook = "notebook"  # upload .ipynb -> dikonversi ke skrip lalu dijalankan
    paste = "paste"        # tempel kode 1 file langsung


# Status final (tidak berubah lagi).
TERMINAL_STATUSES = {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    # Perintah eksekusi. Boleh kosong -> sistem deteksi entrypoint otomatis.
    command: Mapped[str] = mapped_column(Text, default="")
    working_dir: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Kode yang ditempel (source_type=paste).
    inline_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Sumber program: perintah langsung atau repo Git (GitHub).
    source_type: Mapped[JobSource] = mapped_column(
        SAEnum(JobSource, native_enum=False, length=20),
        default=JobSource.command,
        nullable=False,
    )
    repo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    repo_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    upload_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Auto-install requirements.txt (untuk git/upload) sebelum eksekusi.
    auto_install: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # True bila job ini mewakili SESI INTERAKTIF (notebook hidup), bukan job batch.
    is_interactive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, native_enum=False, length=20),
        default=JobStatus.queued,
        index=True,
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # GPU
    gpu_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_gpu_memory_mb: Mapped[float] = mapped_column(Float, default=0.0)

    # Plafon resource per job (0 = tanpa batas). Ditegakkan sampler (auto-stop).
    max_ram_mb: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_threads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Batas waktu eksekusi (timeout, detik). None = tanpa batas.
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Proses
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Waktu
    submitted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True, nullable=False
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Prediksi vs aktual runtime (detik)
    estimated_runtime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_runtime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Metrik resource yang DIUKUR sistem saat job berjalan.
    peak_ram_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_vram_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_gpu_util_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Pemilik
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner: Mapped["User"] = relationship(  # noqa: F821
        back_populates="jobs", lazy="joined"
    )

    @property
    def owner_name(self) -> str:
        """Nama pemilik job (untuk laporan admin). Aman: tak memicu lazy-load."""
        owner = self.__dict__.get("owner")
        return owner.name if owner is not None else ""

    @property
    def owner_email(self) -> str:
        owner = self.__dict__.get("owner")
        return owner.email if owner is not None else ""

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Job id={self.id} name={self.name!r} status={self.status.value}>"
