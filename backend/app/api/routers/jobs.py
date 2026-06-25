"""Router jobs: submit, list, detail, cancel, logs, samples."""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import os
import shutil
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.database import get_db
from app.models.job import TERMINAL_STATUSES, Job, JobSource, JobStatus
from app.models.monitoring import ResourceSample
from app.models.user import User, UserRole
from app.schemas.job import JobCreate, JobOut, QueueItem, UsageOut
from app.schemas.monitoring import ResourceSampleOut
from app.services import archive as archive_svc
from app.services import policy as policy_svc
from app.services import quota as quota_svc
from app.services import repo as repo_svc
from app.services import user_policy as user_policy_svc
from app.services.predictor import predict_runtime
from app.services.queue import compute_queue_eta
from app.services.interactive import kernel_manager
from app.services.scheduler import scheduler

router = APIRouter()


def _resolve_priority(role: UserRole, requested: int | None) -> int:
    """Tentukan prioritas sesuai kebijakan peran.

    - mahasiswa: SELALU 0 -> urutan eksekusi mengikuti waktu submit (FIFO).
    - dosen: boleh atur (default DOSEN_DEFAULT_PRIORITY), minimal 1 -> selalu
      di atas mahasiswa.
    - admin: bebas (minimal 1).
    """
    if role == UserRole.mahasiswa:
        return 0
    if role == UserRole.dosen:
        value = requested if requested is not None else settings.DOSEN_DEFAULT_PRIORITY
        return max(1, min(value, settings.DOSEN_MAX_PRIORITY))
    # admin
    value = requested if requested is not None else settings.DOSEN_DEFAULT_PRIORITY
    return max(1, min(value, settings.ADMIN_MAX_PRIORITY))


def _resolve_time_limit(
    role: UserRole,
    requested: int | None,
    predicted: float | None,
    eff: user_policy_svc.EffectiveUserPolicy,
) -> int:
    """Batas waktu OTOMATIS (estimasi) untuk mahasiswa; dosen/admin boleh override.

    Plafon maksimum mengikuti policy EFEKTIF (per-user override -> global).
    """
    pol = policy_svc.get()
    if role == UserRole.mahasiswa or not requested or requested <= 0:
        base = (
            predicted * pol.runtime_safety_factor
            if predicted and predicted > 0
            else float(pol.default_job_time_limit_seconds)
        )
    else:
        base = float(requested)
    return int(
        max(pol.min_job_time_limit_seconds, min(base, eff.max_time_limit_seconds))
    )


def _resolve_vram(
    role: UserRole,
    requested: float | None,
    eff: user_policy_svc.EffectiveUserPolicy,
) -> float:
    """VRAM: mahasiswa pakai plafon efektif; dosen dibatasi plafon dosen; admin bebas."""
    if role == UserRole.mahasiswa:
        return eff.max_gpu_memory_mb
    if role == UserRole.dosen:
        cap = policy_svc.get().dosen_max_gpu_memory_mb
        req = float(requested) if requested else 0.0
        if cap <= 0:
            return req
        return min(req, cap) if req > 0 else cap
    return float(requested) if requested else 0.0


def _resolve_auto_install(role: UserRole, requested: bool | None) -> bool:
    if role == UserRole.mahasiswa or requested is None:
        return policy_svc.get().auto_pip_install
    return bool(requested)


def _auto_name(payload: JobCreate) -> str:
    if payload.name and payload.name.strip():
        return payload.name.strip()[:255]
    if payload.source_type == JobSource.git and payload.repo_url:
        tail = payload.repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        return (tail or "job-git")[:255]
    return f"job-{payload.source_type.value}"


def _fmt_duration(seconds: float) -> str:
    """Format durasi menjadi teks ramah (detik/menit/jam)."""
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{seconds:.0f} detik"
    if seconds < 3600:
        return f"{seconds / 60:.0f} menit"
    return f"{seconds / 3600:.1f} jam"


async def _ensure_gpu_quota(
    session: AsyncSession, user: User, eff: user_policy_svc.EffectiveUserPolicy
) -> None:
    """Tolak submit bila kuota GPU harian sudah habis (mahasiswa & dosen)."""
    if user.role == UserRole.mahasiswa:
        quota = eff.daily_gpu_seconds_quota
    elif user.role == UserRole.dosen:
        quota = policy_svc.get().dosen_daily_gpu_seconds_quota
    else:
        return
    if quota <= 0:
        return
    used = await quota_svc.gpu_seconds_used(session, user.id)
    if used >= quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Kuota GPU harian habis (terpakai {_fmt_duration(used)} dari "
                f"{_fmt_duration(quota)} per 24 jam). Coba lagi nanti."
            ),
        )


async def _get_owned_job(job_id: int, session: AsyncSession, user: User) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job tidak ditemukan.")
    if user.role != UserRole.admin and job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bukan job Anda.")
    return job


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def submit_job(
    payload: JobCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Job:
    """Submit job (tempel kode / GitHub / perintah). Upload ZIP/notebook -> /jobs/upload."""
    role = current_user.role
    src = payload.source_type

    if src in (JobSource.upload, JobSource.notebook):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Untuk upload ZIP/notebook gunakan POST /jobs/upload.",
        )
    if src == JobSource.command and role == UserRole.mahasiswa:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Mahasiswa tidak boleh perintah manual. Pakai tempel kode / upload / GitHub.",
        )
    if src == JobSource.paste and not (payload.code and payload.code.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Kode kosong."
        )
    if src == JobSource.command and not (payload.command and payload.command.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Perintah kosong."
        )
    if src == JobSource.git:
        if not payload.repo_url:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="repo_url wajib untuk source_type=git.",
            )
        err = repo_svc.validate_repo_url(payload.repo_url) or repo_svc.validate_ref(
            payload.repo_ref
        )
        if err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err
            )

    eff = await user_policy_svc.effective(session, current_user.id)
    await _ensure_gpu_quota(session, current_user, eff)

    # Mahasiswa: perintah SELALU otomatis. Dosen/admin: boleh isi.
    command = "" if role == UserRole.mahasiswa else (payload.command or "").strip()

    name = _auto_name(payload)
    estimate = await predict_runtime(session, name)

    job = Job(
        name=name,
        command=command,
        source_type=src,
        repo_url=payload.repo_url if src == JobSource.git else None,
        repo_ref=payload.repo_ref if src == JobSource.git else None,
        inline_code=payload.code if src == JobSource.paste else None,
        working_dir=payload.working_dir if role != UserRole.mahasiswa else None,
        priority=_resolve_priority(role, payload.priority),
        requested_gpu_memory_mb=_resolve_vram(role, payload.requested_gpu_memory_mb, eff),
        time_limit_seconds=_resolve_time_limit(
            role, payload.time_limit_seconds, estimate, eff
        ),
        auto_install=_resolve_auto_install(role, payload.auto_install),
        status=JobStatus.queued,
        estimated_runtime_seconds=estimate,
        user_id=current_user.id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/upload", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def submit_upload_job(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    command: str | None = Form(default=None),
    time_limit_seconds: int | None = Form(default=None),
    requested_gpu_memory_mb: float | None = Form(default=None),
    auto_install: bool | None = Form(default=None),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Job:
    """Upload project (.zip) ATAU notebook (.ipynb) lalu dijalankan otomatis."""
    role = current_user.role
    fname = file.filename or "project.zip"
    low = fname.lower()
    if low.endswith(".ipynb"):
        kind = "notebook"
    elif low.endswith(".zip"):
        kind = "zip"
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File harus .zip (folder project) atau .ipynb (notebook).",
        )

    eff = await user_policy_svc.effective(session, current_user.id)
    await _ensure_gpu_quota(session, current_user, eff)

    # --- Simpan ke temp dengan batas ukuran (streaming) ---
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    tmp_dir = settings.jobs_path / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid4().hex}{'.ipynb' if kind == 'notebook' else '.zip'}"
    size = 0
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File melebihi batas {settings.MAX_UPLOAD_SIZE_MB} MB.",
                    )
                out.write(chunk)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    # --- Validasi isi ---
    if kind == "zip":
        err = archive_svc.validate_zip(tmp_path)
        if err:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err
            )
    else:
        try:
            data = json.loads(tmp_path.read_text(encoding="utf-8", errors="replace"))
            if "cells" not in data:
                raise ValueError("bukan notebook")
        except Exception as exc:  # noqa: BLE001
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Notebook .ipynb tidak valid.",
            ) from exc

    name_final = (
        name.strip() if name and name.strip() else fname.rsplit(".", 1)[0]
    )[:255]
    command_final = "" if role == UserRole.mahasiswa else (command or "").strip()
    estimate = await predict_runtime(session, name_final)

    job = Job(
        name=name_final,
        command=command_final,
        source_type=JobSource.notebook if kind == "notebook" else JobSource.upload,
        upload_name=fname,
        priority=_resolve_priority(role, None),
        requested_gpu_memory_mb=_resolve_vram(role, requested_gpu_memory_mb, eff),
        time_limit_seconds=_resolve_time_limit(role, time_limit_seconds, estimate, eff),
        auto_install=_resolve_auto_install(role, auto_install),
        status=JobStatus.queued,
        estimated_runtime_seconds=estimate,
        user_id=current_user.id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    # --- Pindahkan berkas ke folder job ---
    job_dir = settings.jobs_path / f"job_{job.id}"
    dest = job_dir / ("notebook.ipynb" if kind == "notebook" else "_upload.zip")
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_path), str(dest))
    except Exception as exc:  # noqa: BLE001
        # Gagal simpan berkas -> bersihkan temp + buang job tanpa-berkas (jangan
        # tinggalkan job 'queued' yang pasti gagal karena berkasnya tak ada).
        tmp_path.unlink(missing_ok=True)
        await session.delete(job)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal menyimpan berkas unggahan.",
        ) from exc
    job.working_dir = str(job_dir)
    await session.commit()
    await session.refresh(job)
    return job


@router.get("/queue", response_model=list[QueueItem])
async def get_queue(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[dict]:
    """Antrian job queued dengan posisi & perkiraan waktu mulai (ETA)."""
    return await compute_queue_eta(session)


@router.get("/usage", response_model=UsageOut)
async def get_usage(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Pemakaian GPU (24 jam terakhir) & sisa kuota harian user saat ini."""
    used = await quota_svc.gpu_seconds_used(session, current_user.id)
    eff = await user_policy_svc.effective(session, current_user.id)
    quota = eff.daily_gpu_seconds_quota
    enabled = quota > 0
    return {
        "window_hours": 24,
        "used_seconds": used,
        "quota_seconds": quota,
        "remaining_seconds": max(0.0, quota - used) if enabled else None,
        "quota_enabled": enabled,
    }


@router.get("", response_model=list[JobOut])
async def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    mine_only: bool = Query(default=True),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[Job]:
    stmt = select(Job).order_by(Job.submitted_at.desc())

    # Non-admin selalu dibatasi ke job miliknya.
    if current_user.role != UserRole.admin or mine_only:
        stmt = stmt.where(Job.user_id == current_user.id)
    if status_filter is not None:
        stmt = stmt.where(Job.status == status_filter)

    result = await session.scalars(stmt.offset(skip).limit(limit))
    return list(result.all())


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Job:
    return await _get_owned_job(job_id, session, current_user)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Job:
    job = await _get_owned_job(job_id, session, current_user)
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job sudah berstatus '{job.status.value}'.",
        )

    if job.is_interactive:
        # Job ini mewakili sesi interaktif: tandai cancelled + hitung runtime,
        # lalu hentikan kernel & lepas GPU-nya. (commit dulu agar _close tak
        # menimpa status menjadi succeeded.)
        now = dt.datetime.now(dt.timezone.utc)
        job.status = JobStatus.cancelled
        job.finished_at = now
        if job.started_at is not None:
            started = job.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=dt.timezone.utc)
            job.actual_runtime_seconds = max(0.0, (now - started).total_seconds())
        await session.commit()
        await kernel_manager.shutdown_by_job_id(job_id)
        await session.refresh(job)
        return job

    if job.status == JobStatus.running:
        # Hentikan proses yang berjalan (scheduler menandai cancelled).
        await scheduler.cancel_job(job_id)
    else:
        # Masih queued -> cukup tandai cancelled.
        job.status = JobStatus.cancelled
        await session.commit()

    await session.refresh(job)
    return job


@router.get("/{job_id}/logs")
async def get_job_logs(
    job_id: int,
    tail: int = Query(default=200, ge=1, le=10000, description="Jumlah baris terakhir"),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    job = await _get_owned_job(job_id, session, current_user)
    if not job.log_path or not Path(job.log_path).exists():
        return {"job_id": job_id, "lines": [], "message": "Log belum tersedia."}

    try:
        with open(job.log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal membaca log: {exc}",
        ) from exc

    return {
        "job_id": job_id,
        "total_lines": len(lines),
        "lines": [ln.rstrip("\n") for ln in lines[-tail:]],
    }


@router.get("/{job_id}/samples", response_model=list[ResourceSampleOut])
async def get_job_samples(
    job_id: int,
    limit: int = Query(500, ge=1, le=5000),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[ResourceSample]:
    await _get_owned_job(job_id, session, current_user)
    result = await session.scalars(
        select(ResourceSample)
        .where(ResourceSample.job_id == job_id)
        .order_by(ResourceSample.ts.desc())
        .limit(limit)
    )
    return list(result.all())


@router.get("/{job_id}/notebook")
async def download_notebook(
    job_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> FileResponse:
    """Unduh notebook HASIL eksekusi (dengan output sel)."""
    job = await _get_owned_job(job_id, session, current_user)
    if job.source_type != JobSource.notebook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bukan job notebook.")
    if not job.working_dir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hasil belum ada.")
    path = Path(job.working_dir) / "notebook_executed.ipynb"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook hasil belum tersedia (job belum selesai).",
        )
    return FileResponse(
        str(path),
        filename=f"{job.name}_executed.ipynb",
        media_type="application/x-ipynb+json",
    )


# Folder/berkas internal yang TIDAK perlu ikut diunduh sebagai "output".
_OUTPUT_EXCLUDE_DIRS = {
    "_pydeps",
    ".git",
    "__pycache__",
    ".ipynb_checkpoints",
    "node_modules",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
}
_OUTPUT_EXCLUDE_FILES = {"_upload.zip"}
_OUTPUT_MAX_BYTES = 512 * 1024 * 1024  # batas aman 512 MB


def _zip_job_output(base: Path, files: list[Path], job_id: int) -> io.BytesIO:
    """Bangun ZIP (sinkron/blocking) dari daftar berkas -> dijalankan via to_thread."""
    buf = io.BytesIO()
    prefix = f"job_{job_id}"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = f"{prefix}/{path.relative_to(base).as_posix()}"
            try:
                zf.write(path, arcname)
            except OSError:
                continue
    buf.seek(0)
    return buf


@router.get("/{job_id}/output")
async def download_output(
    job_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """Unduh SEMUA hasil/output job sebagai ZIP (log + berkas yang dihasilkan program).

    Berlaku untuk semua jenis job (tempel kode / notebook / upload / GitHub) dan
    semua peran (mahasiswa/dosen/admin) selama job miliknya. Folder internal
    (mis. _pydeps, .git) dikecualikan agar ringkas.
    """
    job = await _get_owned_job(job_id, session, current_user)
    if not job.working_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Output belum tersedia (job belum dijalankan).",
        )
    base = Path(job.working_dir)
    if not base.exists() or not base.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Folder output tidak ditemukan (mungkin sudah dibersihkan otomatis).",
        )

    # Kumpulkan berkas (pangkas folder internal; lewati symlink demi keamanan).
    files: list[Path] = []
    total = 0
    for root, dirs, filenames in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _OUTPUT_EXCLUDE_DIRS]
        for fn in filenames:
            if fn in _OUTPUT_EXCLUDE_FILES:
                continue
            p = Path(root) / fn
            if p.is_symlink() or not p.is_file():
                continue
            try:
                total += p.stat().st_size
            except OSError:
                continue
            if total > _OUTPUT_MAX_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Output terlalu besar untuk diunduh sekaligus (>512 MB).",
                )
            files.append(p)

    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tidak ada berkas output untuk diunduh.",
        )

    buf = await asyncio.to_thread(_zip_job_output, base, files, job_id)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in (job.name or f"job_{job_id}"))[:80]
    headers = {"Content-Disposition": f'attachment; filename="{safe or f"job_{job_id}"}_output.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)
