"""Router jobs: submit, list, detail, cancel, logs, samples."""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import os
import shutil
import time
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
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.database import get_db
from app.models.job import TERMINAL_STATUSES, Job, JobDevice, JobSource, JobStatus
from app.models.monitoring import ResourceSample
from app.models.user import User, UserRole
from app.schemas.job import JobCreate, JobOut, QueueItem, UsageOut
from app.schemas.monitoring import ResourceSampleOut
from app.services import archive as archive_svc
from app.services import cpu_pool
from app.services import gpu as gpu_svc
from app.services import policy as policy_svc
from app.services import project_files
from app.services import quota as quota_svc
from app.services import repo as repo_svc
from app.services import storage_guard
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
    remaining_quota: float | None = None,
) -> int:
    """Batas waktu per-job (detik).

    MAHASISWA: batas MENGIKUTI SISA KUOTA GPU HARIAN -> selama kuota masih ada, job
    boleh berjalan sampai selesai (TIDAK dihentikan estimasi kecil). Bila kuota
    nonaktif (0 / super admin) -> fallback ke estimasi/default + plafon policy.
    Dosen/admin: pakai nilai diminta atau estimasi, dibatasi plafon policy EFEKTIF.
    """
    pol = policy_svc.get()
    # Mahasiswa dgn kuota aktif: batas = SISA kuota harian (lantai min agar tak nol/
    # negatif). Kuota harian sendiri yang jadi batas -> tak dipotong plafon per-job.
    if role == UserRole.mahasiswa and remaining_quota is not None and remaining_quota > 0:
        return int(max(pol.min_job_time_limit_seconds, remaining_quota))
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
    is_superadmin: bool,
    requested: float | None,
    eff: user_policy_svc.EffectiveUserPolicy,
) -> float:
    """Plafon VRAM job: super admin bebas; selain itu pakai plafon efektif user
    (override per-user -> default peran; 0 = tanpa batas). Boleh minta lebih kecil."""
    req = float(requested) if requested else 0.0
    if is_superadmin:
        return req
    cap = eff.max_gpu_memory_mb
    if cap <= 0:
        return req
    return min(req, cap) if req > 0 else cap


def _resolve_ram(
    is_superadmin: bool,
    eff: user_policy_svc.EffectiveUserPolicy,
) -> float:
    """Plafon RAM job (0 = tanpa batas). Ditegakkan sampler (auto-stop)."""
    return 0.0 if is_superadmin else eff.max_ram_mb


def _resolve_cpu_threads(
    is_superadmin: bool,
    eff: user_policy_svc.EffectiveUserPolicy,
) -> int:
    """Jumlah thread komputasi job (0 = pakai default sistem)."""
    return 0 if is_superadmin else eff.max_cpu_threads


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


def _fmt_size(nbytes: float) -> str:
    """Format byte -> ukuran manusiawi (B/KB/MB/GB/TB)."""
    val = float(nbytes)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024:
            return f"{val:.0f} {unit}" if unit in ("B", "KB") else f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} TB"


def _safe_folder_paths(paths: list[str]) -> list[str] | None:
    """Ubah webkitRelativePath ('root/sub/file') -> rel-path AMAN di dalam project/
    dengan MEMBUANG 1 segmen root folder. None bila ada entri berbahaya (absolut/'..').
    """
    out: list[str] = []
    for p in paths:
        norm = (p or "").replace("\\", "/").strip().lstrip("/")
        parts = [seg for seg in norm.split("/") if seg not in ("", ".")]
        if not parts or any(seg == ".." for seg in parts):
            return None
        rel = "/".join(parts[1:]) if len(parts) > 1 else parts[0]
        if not rel:
            return None
        out.append(rel)
    return out


async def _ensure_gpu_quota(
    session: AsyncSession, user: User, eff: user_policy_svc.EffectiveUserPolicy
) -> float | None:
    """Tolak submit bila kuota GPU harian sudah habis; kembalikan SISA kuota (detik).

    Super admin bebas. Selain itu pakai kuota efektif user (override per-user ->
    default peran). Return None = TANPA batas kuota (super admin / kuota 0) -> batas
    waktu job memakai estimasi/default seperti biasa.
    """
    if user.is_superadmin:
        return None
    quota = eff.daily_gpu_seconds_quota
    if quota <= 0:
        return None
    used = await quota_svc.gpu_seconds_used(session, user.id)
    if used >= quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Kuota GPU harian habis (terpakai {_fmt_duration(used)} dari "
                f"{_fmt_duration(quota)} per 24 jam). Coba lagi nanti."
            ),
        )
    return max(0.0, quota - used)


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
    # Job CPU tak memakai GPU -> tak kena kuota GPU harian.
    device = payload.device if settings.ALLOW_CPU_JOBS else JobDevice.gpu
    remaining_quota: float | None = None
    if device is JobDevice.gpu:
        remaining_quota = await _ensure_gpu_quota(session, current_user, eff)

    # Mahasiswa: perintah SELALU otomatis. Dosen/admin: boleh isi.
    command = "" if role == UserRole.mahasiswa else (payload.command or "").strip()

    name = _auto_name(payload)
    estimate = await predict_runtime(session, name)

    job = Job(
        name=name,
        command=command,
        source_type=src,
        device=device,
        repo_url=payload.repo_url if src == JobSource.git else None,
        repo_ref=payload.repo_ref if src == JobSource.git else None,
        inline_code=payload.code if src == JobSource.paste else None,
        working_dir=payload.working_dir if role != UserRole.mahasiswa else None,
        priority=_resolve_priority(role, payload.priority),
        requested_gpu_memory_mb=(
            0.0 if device is JobDevice.cpu
            else _resolve_vram(
                current_user.is_superadmin, payload.requested_gpu_memory_mb, eff
            )
        ),
        max_ram_mb=_resolve_ram(current_user.is_superadmin, eff),
        cpu_threads=_resolve_cpu_threads(current_user.is_superadmin, eff),
        time_limit_seconds=_resolve_time_limit(
            role, payload.time_limit_seconds, estimate, eff, remaining_quota
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
    device: JobDevice = Form(default=JobDevice.gpu),
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
    dev = device if settings.ALLOW_CPU_JOBS else JobDevice.gpu
    remaining_quota: float | None = None
    if dev is JobDevice.gpu:
        remaining_quota = await _ensure_gpu_quota(session, current_user, eff)

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
        device=dev,
        upload_name=fname,
        priority=_resolve_priority(role, None),
        requested_gpu_memory_mb=(
            0.0 if dev is JobDevice.cpu
            else _resolve_vram(
                current_user.is_superadmin, requested_gpu_memory_mb, eff
            )
        ),
        max_ram_mb=_resolve_ram(current_user.is_superadmin, eff),
        cpu_threads=_resolve_cpu_threads(current_user.is_superadmin, eff),
        time_limit_seconds=_resolve_time_limit(role, time_limit_seconds, estimate, eff, remaining_quota),
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


# --- Upload FOLDER chunked (tahan batas ukuran body proxy nginx di depan) ---------
# nginx pembatas membatasi ukuran 1 request -> tiap file dipecah jadi chunk kecil &
# dikirim berurutan. Sesi unggah disimpan sementara (memori + folder temp); Job baru
# dibuat saat FINALIZE. File disimpan APA ADANYA -> pemakaian disk = ukuran NYATA,
# batas = SISA KUOTA DISK user (transparan, tak ada kesalahpahaman zip-vs-nyata).
_folder_sessions: dict[str, dict] = {}
_FOLDER_TTL = 3600.0  # sesi unggah menganggur dibuang setelah 1 jam


def _cleanup_folder_sessions() -> None:
    now = time.time()
    for tok in list(_folder_sessions):
        s = _folder_sessions.get(tok)
        if s and now - s["ts"] > _FOLDER_TTL:
            shutil.rmtree(s["dir"], ignore_errors=True)
            _folder_sessions.pop(tok, None)


def _folder_session(token: str, user: User) -> dict:
    s = _folder_sessions.get(token)
    if s is None or s["user_id"] != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sesi unggah tidak ditemukan."
        )
    return s


class FolderInit(BaseModel):
    name: str | None = None
    command: str | None = None
    time_limit_seconds: int | None = None
    requested_gpu_memory_mb: float | None = None
    auto_install: bool | None = None
    device: JobDevice = JobDevice.gpu


@router.post("/folder/init")
async def folder_upload_init(
    body: FolderInit,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Mulai sesi unggah FOLDER (chunked). Kembalikan token + sisa kuota disk (byte)."""
    _cleanup_folder_sessions()
    eff = await user_policy_svc.effective(session, current_user.id)
    dev = body.device if settings.ALLOW_CPU_JOBS else JobDevice.gpu
    remaining_quota: float | None = None
    if dev is JobDevice.gpu:
        remaining_quota = await _ensure_gpu_quota(session, current_user, eff)
    max_bytes = await storage_guard.upload_limit_bytes(current_user.id, eff.max_storage_mb)
    if max_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Kuota penyimpanan Anda penuh. Hapus file di menu Penyimpanan dulu.",
        )
    token = uuid4().hex
    sess_dir = settings.jobs_path / "_folder" / token
    (sess_dir / "project").mkdir(parents=True, exist_ok=True)
    _folder_sessions[token] = {
        "user_id": current_user.id,
        "dir": sess_dir,
        "received": 0,
        "max_bytes": max_bytes,
        "remaining_quota": remaining_quota,
        "device": dev,
        "meta": body.model_dump(),
        "ts": time.time(),
    }
    return {"token": token, "max_bytes": max_bytes}


@router.post("/folder/{token}/chunk")
async def folder_upload_chunk(
    token: str,
    request: Request,
    path: str = Query(...),
    first: bool = Query(default=False),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Terima SATU potongan (raw bytes) untuk file `path`. first=1 -> mulai file baru."""
    s = _folder_session(token, current_user)
    rels = _safe_folder_paths([path])
    if not rels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Path tidak aman."
        )
    project_dir = (s["dir"] / "project").resolve()
    target = (project_dir / rels[0]).resolve()
    if target != project_dir and not str(target).startswith(str(project_dir) + os.sep):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Path tidak aman."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = s["max_bytes"]
    try:
        with open(target, "wb" if first else "ab") as out:
            async for chunk in request.stream():
                if not chunk:
                    continue
                s["received"] += len(chunk)
                if s["received"] > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            f"Folder melebihi sisa kuota penyimpanan Anda "
                            f"(~{_fmt_size(max_bytes)} tersisa)."
                        ),
                    )
                out.write(chunk)
    except HTTPException:
        shutil.rmtree(s["dir"], ignore_errors=True)
        _folder_sessions.pop(token, None)
        raise
    s["ts"] = time.time()
    return {"received": s["received"]}


@router.post(
    "/folder/{token}/finalize",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
)
async def folder_upload_finalize(
    token: str,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Job:
    """Selesaikan sesi unggah FOLDER -> buat Job (source upload) & masukkan antrian."""
    s = _folder_session(token, current_user)
    project_dir = s["dir"] / "project"
    if not any(project_dir.rglob("*")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder kosong.")

    role = current_user.role
    eff = await user_policy_svc.effective(session, current_user.id)
    meta = s["meta"]
    dev = s["device"]
    command_final = "" if role == UserRole.mahasiswa else (meta.get("command") or "").strip()
    name_final = ((meta.get("name") or "").strip() or "job-folder")[:255]
    estimate = await predict_runtime(session, name_final)

    job = Job(
        name=name_final,
        command=command_final,
        source_type=JobSource.upload,
        device=dev,
        upload_name=name_final,
        priority=_resolve_priority(role, None),
        requested_gpu_memory_mb=(
            0.0 if dev is JobDevice.cpu
            else _resolve_vram(
                current_user.is_superadmin, meta.get("requested_gpu_memory_mb"), eff
            )
        ),
        max_ram_mb=_resolve_ram(current_user.is_superadmin, eff),
        cpu_threads=_resolve_cpu_threads(current_user.is_superadmin, eff),
        time_limit_seconds=_resolve_time_limit(
            role, meta.get("time_limit_seconds"), estimate, eff, s["remaining_quota"]
        ),
        auto_install=_resolve_auto_install(role, meta.get("auto_install")),
        status=JobStatus.queued,
        estimated_runtime_seconds=estimate,
        user_id=current_user.id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    job_dir = settings.jobs_path / f"job_{job.id}"
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(project_dir), str(job_dir / "project"))
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(job_dir, ignore_errors=True)
        await session.delete(job)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal menyimpan folder unggahan.",
        ) from exc
    finally:
        shutil.rmtree(s["dir"], ignore_errors=True)
        _folder_sessions.pop(token, None)

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


@router.get("/pools")
async def get_pools(
    _: User = Depends(get_current_active_user),
) -> dict:
    """Status kapasitas kolam GPU & CPU (untuk indikator 'penuh'/'tersedia')."""
    cpu = cpu_pool.summary()
    gpu = gpu_svc.pool_summary()
    return {
        "cpu": cpu,
        "gpu": gpu,
        "allow_cpu_jobs": settings.ALLOW_CPU_JOBS,
    }


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
    deleted: bool = Query(default=False, description="True -> tampilkan isi 'Sampah'."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[Job]:
    # 'Sampah' diurut waktu-hapus terbaru; daftar aktif diurut waktu-submit terbaru.
    stmt = select(Job).order_by(
        Job.deleted_at.desc() if deleted else Job.submitted_at.desc()
    )
    # Pisahkan job aktif vs yang di 'Sampah' (soft-delete).
    stmt = stmt.where(Job.deleted_at.is_not(None) if deleted else Job.deleted_at.is_(None))

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


def _can_soft_delete(user: User, job: Job) -> bool:
    """Boleh HAPUS (soft-delete) job ini?

    - Super admin     : SEMUA job.
    - Owner NON-admin : job MILIKNYA (mahasiswa/dosen).
    - Admin biasa     : TIDAK boleh sama sekali (kebijakan kampus).
    """
    if user.is_superadmin:
        return True
    return user.role != UserRole.admin and job.user_id == user.id


def _can_restore(user: User, job: Job) -> bool:
    """Boleh KEMBALIKAN job dari 'Sampah'?

    - Super admin     : SEMUA job.
    - Owner NON-admin : job MILIKNYA.
    - Admin biasa     : job milik MAHASISWA/DOSEN (bukan admin lain) — ia boleh MENOLONG
      mengembalikan pekerjaan user yang terhapus, tapi TETAP tak boleh menghapusnya.
    """
    if user.is_superadmin:
        return True
    if user.role != UserRole.admin and job.user_id == user.id:
        return True
    if user.role == UserRole.admin:
        owner = job.__dict__.get("owner")
        return owner is not None and owner.role in (UserRole.mahasiswa, UserRole.dosen)
    return False


async def _stop_job_execution(job: Job, session: AsyncSession) -> None:
    """Hentikan job yang MASIH AKTIF (interaktif / queued / running): tandai cancelled,
    hitung runtime, hentikan kernel/proses & bebaskan GPU. No-op bila sudah terminal."""
    if job.status in TERMINAL_STATUSES:
        return
    if job.is_interactive:
        # commit dulu agar penutupan kernel tak menimpa status jadi succeeded.
        now = dt.datetime.now(dt.timezone.utc)
        job.status = JobStatus.cancelled
        job.finished_at = now
        if job.started_at is not None:
            started = job.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=dt.timezone.utc)
            job.actual_runtime_seconds = max(0.0, (now - started).total_seconds())
        await session.commit()
        await kernel_manager.shutdown_by_job_id(job.id)
        await session.refresh(job)
        return
    if job.status == JobStatus.running:
        await scheduler.cancel_job(job.id)  # scheduler menandai cancelled
    else:
        job.status = JobStatus.cancelled  # masih queued -> cukup tandai
        await session.commit()
    await session.refresh(job)


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
    await _stop_job_execution(job, session)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Soft-delete: pindahkan job ke 'Sampah' (bisa dikembalikan). Job yang masih
    aktif dibatalkan otomatis dulu (bebaskan GPU). File TETAP disimpan."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job tidak ditemukan.")
    if not _can_soft_delete(current_user, job):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak berhak menghapus job ini.",
        )
    if job.deleted_at is not None:
        return  # sudah di Sampah -> idempoten
    await _stop_job_execution(job, session)
    job.deleted_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()


@router.post("/{job_id}/restore", response_model=JobOut)
async def restore_job(
    job_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Job:
    """Kembalikan job dari 'Sampah' (soft-delete) ke daftar aktif."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job tidak ditemukan.")
    if not _can_restore(current_user, job):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak berhak mengembalikan job ini.",
        )
    job.deleted_at = None
    await session.commit()
    await session.refresh(job)
    return job


@router.delete("/{job_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_job(
    job_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Hapus PERMANEN (file + data) — hanya super admin. Tidak bisa dikembalikan."""
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya super admin yang bisa menghapus permanen.",
        )
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job tidak ditemukan.")
    # Hentikan bila masih aktif (bebaskan GPU) lalu buang folder kerja + log dari disk.
    await _stop_job_execution(job, session)
    job_dir = settings.jobs_path / f"job_{job_id}"
    shutil.rmtree(job_dir, ignore_errors=True)
    # Sampel monitoring ikut terhapus otomatis (FK ondelete=CASCADE).
    await session.delete(job)
    await session.commit()


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
    "_jkernel",
}
_OUTPUT_EXCLUDE_FILES = {"_upload.zip", "_run_notebook.py"}
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


# ------------------------------------------- edit project job (explorer JobDetail)
class JobFileBody(BaseModel):
    path: str
    content: str = ""


class JobPathBody(BaseModel):
    path: str


class JobRenameBody(BaseModel):
    path: str
    new_path: str


def _job_project_root(job: Job) -> Path:
    """Folder project job (upload -> project/, github -> repo/). Error bila tak ada."""
    if not job.working_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project belum tersedia."
        )
    base = Path(job.working_dir)
    for sub in ("project", "repo"):
        d = base / sub
        if d.is_dir():
            return d
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Job ini tidak punya folder project untuk diedit.",
    )


def _require_editable(job: Job) -> None:
    if job.status not in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job masih berjalan/antre — tunggu selesai untuk mengedit.",
        )


def _pf_tree(fn) -> dict:
    try:
        return {"tree": fn()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{job_id}/files")
async def job_list_files(
    job_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Pohon file project job (untuk explorer di detail job)."""
    job = await _get_owned_job(job_id, session, current_user)
    return {"tree": project_files.build_tree(_job_project_root(job))}


@router.get("/{job_id}/file")
async def job_read_file(
    job_id: int,
    path: str = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    job = await _get_owned_job(job_id, session, current_user)
    root = _job_project_root(job)
    try:
        return project_files.read_text(root, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.put("/{job_id}/file")
async def job_write_file(
    job_id: int,
    body: JobFileBody,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    job = await _get_owned_job(job_id, session, current_user)
    _require_editable(job)
    root = _job_project_root(job)
    return _pf_tree(lambda: project_files.write_text(root, body.path, body.content))


@router.post("/{job_id}/mkdir")
async def job_mkdir(
    job_id: int,
    body: JobPathBody,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    job = await _get_owned_job(job_id, session, current_user)
    _require_editable(job)
    root = _job_project_root(job)
    return _pf_tree(lambda: project_files.make_dir(root, body.path))


@router.post("/{job_id}/rename")
async def job_rename(
    job_id: int,
    body: JobRenameBody,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    job = await _get_owned_job(job_id, session, current_user)
    _require_editable(job)
    root = _job_project_root(job)
    return _pf_tree(lambda: project_files.rename(root, body.path, body.new_path))


@router.delete("/{job_id}/item")
async def job_delete_item(
    job_id: int,
    path: str = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    job = await _get_owned_job(job_id, session, current_user)
    _require_editable(job)
    root = _job_project_root(job)
    return _pf_tree(lambda: project_files.delete(root, path))


@router.post("/{job_id}/rerun", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def rerun_job(
    job_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Job:
    """Jalankan ULANG project job (yang mungkin sudah diedit) sebagai job batch BARU."""
    job = await _get_owned_job(job_id, session, current_user)
    src = _job_project_root(job)
    role = current_user.role
    eff = await user_policy_svc.effective(session, current_user.id)
    dev = job.device
    remaining_quota: float | None = None
    if dev is JobDevice.gpu:
        remaining_quota = await _ensure_gpu_quota(session, current_user, eff)
    name_final = (job.name or "job-folder")[:255]
    estimate = await predict_runtime(session, name_final)
    new = Job(
        name=name_final,
        command="" if role == UserRole.mahasiswa else (job.command or ""),
        source_type=JobSource.upload,
        device=dev,
        upload_name=job.upload_name or name_final,
        priority=_resolve_priority(role, None),
        requested_gpu_memory_mb=(
            0.0 if dev is JobDevice.cpu
            else _resolve_vram(current_user.is_superadmin, job.requested_gpu_memory_mb, eff)
        ),
        max_ram_mb=_resolve_ram(current_user.is_superadmin, eff),
        cpu_threads=_resolve_cpu_threads(current_user.is_superadmin, eff),
        time_limit_seconds=_resolve_time_limit(role, None, estimate, eff, remaining_quota),
        auto_install=job.auto_install,
        status=JobStatus.queued,
        estimated_runtime_seconds=estimate,
        user_id=current_user.id,
    )
    session.add(new)
    await session.commit()
    await session.refresh(new)
    new_dir = settings.jobs_path / f"job_{new.id}"
    try:
        new_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            src,
            new_dir / "project",
            # Jangan bawa artefak sistem/dependensi agar job baru bersih & entrypoint
            # notebook terdeteksi benar (bukan skrip/kernel basi dari run sebelumnya).
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", ".ipynb_checkpoints",
                "_pydeps", "_jkernel", "_run_notebook.py", "notebook_executed.ipynb",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(new_dir, ignore_errors=True)
        await session.delete(new)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal menyalin project untuk dijalankan ulang.",
        ) from exc
    new.working_dir = str(new_dir)
    await session.commit()
    await session.refresh(new)
    return new
