"""Router admin: pengaturan sistem global, policy per-user, & statistik pemakaian."""

from __future__ import annotations

import asyncio
import csv
import dataclasses
import datetime as dt
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.job import Job, JobStatus
from app.models.ops_event import OpsEvent
from app.models.storage_request import StorageQuotaRequest
from app.models.user import User, UserRole
from app.schemas.admin import (
    LinuxLimitsOut,
    LinuxLimitsUpdate,
    LinuxLimitsWriteOut,
    MaintenanceOut,
    MaintenanceUpdate,
    SettingsOut,
    SettingsUpdate,
    UserPolicyOut,
    UserPolicyUpdate,
    UserUsageOut,
)
from app.schemas.report import FullReport
from app.services import audit as audit_svc
from app.services import account_report as account_report_svc
from app.services import maintenance as maintenance_svc
from app.services import linux_limits as linux_limits_svc
from app.services import ops_requests as ops_requests_svc
from app.services import pdf as pdf_svc
from app.services import policy as policy_svc
from app.services import report as report_svc
from app.services import usage_history as usage_history_svc
from app.services import user_policy as user_policy_svc
from app.services import storage_request as storage_request_svc
from app.services.cleanup import cleanup_service
from app.models.audit import AuditLog

router = APIRouter()
logger = get_logger(__name__)


@router.get("/linux-accounts/limits", response_model=LinuxLimitsOut)
async def get_linux_account_limits(
    response: Response, _: User = Depends(require_admin),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return await linux_limits_svc.snapshot()


def _linux_write_gate(current_user: User) -> None:
    if not settings.LINUX_LIMITS_WRITE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pengubahan batas akun Linux dinonaktifkan (LINUX_LIMITS_WRITE_ENABLED=false).",
        )
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya administrator utama yang boleh mengubah batas akun Linux.",
        )


def _linux_account(uid: int) -> str:
    import pwd

    from app.services.report import is_human_user

    try:
        entry = pwd.getpwuid(uid)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Akun Linux tidak ditemukan.")
    if uid < 1000 or not is_human_user(entry.pw_name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hanya akun login manusia yang boleh diatur.")
    return entry.pw_name


@router.put("/linux-accounts/{uid}/limits", response_model=LinuxLimitsWriteOut)
async def set_linux_account_limits(
    uid: int,
    payload: LinuxLimitsUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Pasang batas CPU/RAM RUNTIME pada satu akun Linux (hilang saat reboot).

    Hanya administrator utama; wajib mengetik ulang username sebagai konfirmasi;
    ditolak bila akun sudah punya aturan systemd dari luar ComputeHub (aturan IT).
    """
    _linux_write_gate(current_user)
    username = _linux_account(uid)
    if payload.confirm_username != username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Konfirmasi username tidak cocok.")
    changes = payload.model_dump(exclude_unset=True, exclude={"confirm_username"})
    try:
        result = await linux_limits_svc.apply_runtime_limits(uid, username, changes)
    except linux_limits_svc.LinuxLimitError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    await audit_svc.log(
        session, current_user, "linux_limits.set", "linux_user", username,
        f"uid={uid} runtime " + ", ".join(f"{k}={v or 'max'}" for k, v in result["properties"].items()),
    )
    await session.commit()
    logger.info("Batas Linux %s (uid %s) diubah oleh %s: %s", username, uid, current_user.email, result["properties"])
    return result


@router.delete("/linux-accounts/{uid}/limits", response_model=LinuxLimitsWriteOut)
async def revert_linux_account_limits(
    uid: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Lepas batas runtime buatan ComputeHub -> akun kembali ke aturan sistem/IT."""
    _linux_write_gate(current_user)
    username = _linux_account(uid)
    try:
        result = await linux_limits_svc.revert_runtime_limits(uid)
    except linux_limits_svc.LinuxLimitError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if result["removed"]:
        await audit_svc.log(
            session, current_user, "linux_limits.revert", "linux_user", username,
            f"uid={uid} dilepas: {', '.join(result['removed'])}",
        )
        await session.commit()
        logger.info("Batas Linux %s (uid %s) dilepas oleh %s.", username, uid, current_user.email)
    return result


async def _assert_can_manage(
    session: AsyncSession, current_user: User, user_id: int
) -> User:
    """Hierarki: admin biasa hanya boleh mengelola dosen & mahasiswa; tak boleh
    menyentuh kebijakan akun admin lain atau administrator utama."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User tidak ditemukan.")
    if current_user.id != user_id:
        if user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tidak boleh mengubah kebijakan administrator utama.",
            )
        if user.role == UserRole.admin and not current_user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin biasa tidak boleh mengelola kebijakan admin lain.",
            )
    return user


# ----------------------------------------------------------- policy global
@router.get("/settings", response_model=SettingsOut)
async def get_settings(_: User = Depends(require_admin)) -> dict:
    """Lihat policy global aktif (batas waktu, VRAM, RAM, GPU, kuota, dll)."""
    return policy_svc.get().as_dict()


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(
    payload: SettingsUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Ubah policy global. HANYA administrator utama (berlaku langsung)."""
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya administrator utama yang boleh mengubah pengaturan global.",
        )
    changes = payload.model_dump(exclude_none=True)
    pol = await policy_svc.update(session, changes)
    await audit_svc.log(
        session, current_user, "settings.update", "settings", "global",
        "ubah: " + ", ".join(f"{k}={v}" for k, v in sorted(changes.items())),
    )
    await session.commit()
    logger.info(
        "Policy global diubah oleh %s: %s", current_user.email, sorted(changes.keys())
    )
    return pol.as_dict()


def _maintenance_payload() -> dict:
    st = maintenance_svc.state()
    return {
        "active": st.active,
        "message": st.message,
        "since": (
            dt.datetime.fromtimestamp(st.since, dt.timezone.utc).isoformat()
            if st.since else None
        ),
    }


@router.get("/maintenance-mode", response_model=MaintenanceOut)
async def get_maintenance_mode(_: User = Depends(require_admin)) -> dict:
    """Lihat kondisi mode pemeliharaan (pekerjaan BARU ditahan)."""
    return _maintenance_payload()


@router.put("/maintenance-mode", response_model=MaintenanceOut)
async def set_maintenance_mode(
    payload: MaintenanceUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Nyalakan/matikan mode pemeliharaan. HANYA administrator utama.

    Saat aktif: submit job & sesi interaktif BARU ditolak 503 untuk non-admin,
    sedangkan job/kernel yang sedang berjalan dibiarkan selesai.
    """
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya administrator utama yang boleh mengubah mode pemeliharaan.",
        )
    maintenance_svc.set_active(payload.active, payload.message or "")
    await audit_svc.log(
        session, current_user, "maintenance.set", "settings", "maintenance",
        "aktif" if payload.active else "nonaktif",
    )
    await session.commit()
    logger.info(
        "Mode pemeliharaan %s oleh %s.",
        "DINYALAKAN" if payload.active else "DIMATIKAN", current_user.email,
    )
    return _maintenance_payload()


@router.post("/maintenance/cleanup")
async def run_cleanup(current_user: User = Depends(require_admin)) -> dict:
    """Bersihkan artefak lama SEKARANG. HANYA administrator utama."""
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya administrator utama yang boleh menjalankan pembersihan manual.",
        )
    logger.info("Pembersihan manual dijalankan oleh %s.", current_user.email)
    return await cleanup_service.run_once()


# ----------------------------------------------------------- policy per-user
def _policy_payload(user_id: int, ov, eff) -> dict:
    return {
        "user_id": user_id,
        "overrides": {
            f: getattr(ov, f, None) if ov is not None else None
            for f in user_policy_svc.OVERRIDE_FIELDS
        },
        "effective": dataclasses.asdict(eff),
    }


@router.get("/users/{user_id}/policy", response_model=UserPolicyOut)
async def get_user_policy(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Lihat override & policy efektif satu user."""
    await _assert_can_manage(session, current_user, user_id)
    ov = await user_policy_svc.get_overrides(session, user_id)
    eff = await user_policy_svc.effective(session, user_id)
    return _policy_payload(user_id, ov, eff)


@router.patch("/users/{user_id}/policy", response_model=UserPolicyOut)
async def set_user_policy(
    user_id: int,
    payload: UserPolicyUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Set/ubah batas KHUSUS user ini (kosongkan field = ikut global)."""
    await _assert_can_manage(session, current_user, user_id)
    changes = payload.model_dump(exclude_unset=True)
    # Izin 2 GPU = keputusan strategis (1 job memborong seluruh server) —
    # HANYA administrator utama; admin biasa ditolak walau boleh atur field lain.
    if "allow_multi_gpu" in changes and not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya administrator utama yang boleh mengatur izin 2 GPU.",
        )
    await user_policy_svc.set_overrides(session, user_id, changes)
    await audit_svc.log(
        session, current_user, "policy.update", "user", user_id,
        "override: " + ", ".join(f"{k}={v}" for k, v in sorted(changes.items())),
    )
    await session.commit()
    logger.info(
        "Kebijakan user #%s diubah oleh %s: %s",
        user_id, current_user.email, sorted(changes.keys()),
    )
    ov = await user_policy_svc.get_overrides(session, user_id)
    eff = await user_policy_svc.effective(session, user_id)
    return _policy_payload(user_id, ov, eff)


# ----------------------------------------------------------- audit log
@router.get("/audit")
async def list_audit(
    skip: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    """Riwayat aksi penting admin (terbaru dulu) — akuntabilitas multi-admin."""
    limit = max(1, min(int(limit), 200))
    rows = (
        await session.scalars(
            select(AuditLog).order_by(AuditLog.created_at.desc()).offset(max(0, skip)).limit(limit)
        )
    ).all()
    return [
        {
            "id": a.id,
            "created_at": a.created_at,
            "actor_id": a.actor_id,
            "actor_email": a.actor_email,
            "action": a.action,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "detail": a.detail,
        }
        for a in rows
    ]


# ----------------------------------------------------------- statistik
@router.get("/usage", response_model=list[UserUsageOut])
async def usage(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    """Statistik pemakaian per user (jumlah job, sukses/gagal, GPU-detik)."""
    day_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)

    rows = (
        await session.execute(
            select(
                User.id,
                User.name,
                User.email,
                User.role,
                func.count(Job.id),
                func.coalesce(
                    func.sum(case((Job.status == JobStatus.succeeded, 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Job.status == JobStatus.failed, 1), else_=0)),
                    0,
                ),
                func.coalesce(func.sum(Job.actual_runtime_seconds), 0.0),
            )
            .select_from(User)
            .join(Job, Job.user_id == User.id, isouter=True)
            .group_by(User.id)
            .order_by(User.id)
        )
    ).all()

    used24 = dict(
        (
            await session.execute(
                select(
                    Job.user_id,
                    func.coalesce(func.sum(Job.actual_runtime_seconds), 0.0),
                )
                .where(
                    Job.finished_at >= day_ago,
                    Job.actual_runtime_seconds.is_not(None),
                )
                .group_by(Job.user_id)
            )
        ).all()
    )

    out: list[dict] = []
    for uid, name, email, role, total, succ, failed, secs_total in rows:
        out.append(
            {
                "user_id": uid,
                "name": name,
                "email": email,
                "role": role.value if hasattr(role, "value") else str(role),
                "jobs_total": int(total),
                "jobs_succeeded": int(succ),
                "jobs_failed": int(failed),
                "gpu_seconds_24h": float(used24.get(uid, 0.0)),
                "gpu_seconds_total": float(secs_total),
            }
        )
    return out


# ----------------------------------------------------------- laporan lengkap
@router.get("/report", response_model=FullReport)
async def report(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Laporan penggunaan resource lengkap (OS-level + platform ComputeHub)."""
    return await report_svc.build_report(session)


@router.get("/report/disk")
async def report_disk(
    _: User = Depends(require_admin),
) -> dict:
    """Pemakaian disk: total (df /) + per-user home (du). Di-cache + dihitung di latar."""
    return await report_svc.disk_usage()


@router.get("/report/history")
async def report_history(
    days: int = 30,
    username: str | None = None,
    user_id: int | None = None,
    llm_nama: str | None = None,
    include_system: bool = True,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Riwayat pemakaian HARIAN: per user OS (server) + per user ComputeHub (job).

    Bila `username` / `user_id` diisi, rincian PER JAM user itu ikut dikirim.
    `days=0` berarti "hari ini" (sejak tengah malam waktu server).
    """
    days = max(0, min(int(days), 730))
    return {
        "days": days,
        "os_users": await usage_history_svc.daily_summary(
            session, days=days, username=username, include_system=include_system
        ),
        "computehub_users": await usage_history_svc.daily_summary_computehub(
            session, days=days, user_id=user_id
        ),
        "llm_harian": await usage_history_svc.daily_summary_llm(
            session, days=days, nama=llm_nama
        ),
        "daftar_user": await usage_history_svc.daftar_user(
            session, days=days, include_system=include_system
        ),
        "daftar_llm": await usage_history_svc.daftar_pihak_llm(session, days=days),
        "os_jam": (
            await usage_history_svc.hourly_detail(
                session, username=username, days=days
            )
            if username
            else []
        ),
        "computehub_jam": (
            await usage_history_svc.hourly_detail_computehub(
                session, user_id=user_id, days=days
            )
            if user_id
            else []
        ),
    }


@router.get("/report/history.csv")
async def report_history_csv(
    days: int = 30,
    username: str | None = None,
    include_system: bool = True,
    per_jam: bool = False,
    sumber: str = "os",
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Response:
    """Riwayat per user OS sebagai CSV (lampiran laporan/skripsi).

    `per_jam=1` + `username` -> rincian jam-per-jam user tersebut.
    `sumber=llm` -> riwayat harian koneksi ke layanan LLM.
    """
    days = max(0, min(int(days), 730))
    if sumber == "llm":
        rows = await usage_history_svc.daily_summary_llm(
            session, days=days, nama=username
        )
        kolom = [
            "tanggal", "nama", "sumber", "uid", "koneksi_avg", "koneksi_max",
            "detik_aktif", "pangsa_avg", "layanan_vram_max_mb",
            "layanan_cpu_avg_percent", "layanan_ram_max_mb", "est_vram_max_mb",
            "est_cpu_avg_percent", "est_ram_max_mb", "menit_aktif", "cuplikan",
        ]
        nama = f"riwayat-llm-{dt.date.today():%Y%m%d}.csv"
    elif per_jam and username:
        rows = await usage_history_svc.hourly_detail(
            session, username=username, days=days
        )
        kolom = [
            "tanggal", "jam", "rentang", "cpu_avg_percent", "cpu_max_percent",
            "cpu_cores_avg", "ram_max_mb", "ram_model_max_mb", "vram_max_mb",
            "proses_max", "menit_aktif", "aktivitas", "cuplikan",
        ]
        nama = f"riwayat-jam-{username}-{dt.date.today():%Y%m%d}.csv"
    else:
        rows = await usage_history_svc.daily_summary(
            session, days=days, username=username, include_system=include_system
        )
        kolom = [
            "tanggal", "username", "is_system", "cpu_avg_percent", "cpu_max_percent",
            "cpu_cores_avg", "ram_avg_mb", "ram_max_mb", "ram_model_max_mb",
            "vram_max_mb", "proses_max", "menit_aktif", "aktivitas", "cuplikan",
        ]
        nama = f"riwayat-pemakaian-{dt.date.today():%Y%m%d}.csv"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=kolom, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )


@router.get("/report/download")
async def report_download(
    days: int = 7,
    username: str | None = None,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Response:
    """Unduh laporan server LENGKAP sebagai PDF.

    Selain potret keadaan saat ini, ikut disertakan riwayat harian (server & LLM)
    dan pemakaian disk. `username` menambahkan rincian per jam user tersebut.
    Bawaan 7 hari agar berkas tetap wajar; naikkan `days` bila perlu lebih panjang.
    """
    days = max(0, min(int(days), 365))
    rep = await report_svc.build_report(session)
    riwayat = {
        "days": days,
        "username": username or "",
        "os_users": await usage_history_svc.daily_summary(
            session, days=days, include_system=False
        ),
        "llm_harian": await usage_history_svc.daily_summary_llm(session, days=days),
        "os_jam": (
            await usage_history_svc.hourly_detail(session, username=username, days=days)
            if username
            else []
        ),
        "disk": await report_svc.disk_usage(),
    }
    isi = await asyncio.to_thread(pdf_svc.build_full_pdf, rep, riwayat)
    return Response(
        content=isi,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf_svc.full_pdf_filename()}"'
        },
    )


@router.get("/report/account/{user_id}")
async def report_account(
    user_id: int,
    days: int = 30,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Laporan DETAIL satu akun ComputeHub (job, kuota, asisten, penyimpanan)."""
    rep = await account_report_svc.account_report(
        session, user_id, days=max(1, min(int(days), 730))
    )
    if rep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Akun tidak ditemukan."
        )
    return rep


@router.get("/report/account/{user_id}/download")
async def report_account_download(
    user_id: int,
    days: int = 30,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Response:
    """Unduh laporan detail akun ComputeHub sebagai PDF."""
    rep = await account_report_svc.account_report(
        session, user_id, days=max(1, min(int(days), 730))
    )
    if rep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Akun tidak ditemukan."
        )
    isi = await asyncio.to_thread(pdf_svc.build_account_pdf, rep)
    nama = pdf_svc.account_pdf_filename(rep["akun"]["nama"] or rep["akun"]["email"])
    return Response(
        content=isi,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )


@router.get("/report/user/{username}")
async def report_user(
    username: str,
    days: int = 30,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Laporan DETAIL per-user OS (analisis workload + riwayat + temuan)."""
    return await report_svc.user_report(
        username, session, days=max(1, min(int(days), 730))
    )


@router.get("/report/user/{username}/download")
async def report_user_download(
    username: str,
    days: int = 30,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Response:
    """Unduh laporan detail per-user sebagai PDF (siap dilampirkan/dicetak)."""
    rep = await report_svc.user_report(
        username, session, days=max(1, min(int(days), 730))
    )
    # Render PDF memblokir CPU -> ke thread agar event loop tetap responsif.
    isi = await asyncio.to_thread(pdf_svc.build_user_pdf, rep, None)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in username if c.isalnum() or c in "-_") or "user"
    return Response(
        content=isi,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="laporan_{safe}_{stamp}.pdf"'
        },
    )


# --------------------------------------------------------------------------- #
#  Bukti cadangan & pemulihan (ops_events) — tersimpan di DB, bukan hanya email  #
# --------------------------------------------------------------------------- #
_OPS_KINDS = ("backup", "restore", "restore_drill", "offsite", "watchdog")


def _ops_row(e: OpsEvent) -> dict:
    return {
        "id": e.id,
        "created_at": e.created_at,
        "kind": e.kind,
        "status": e.status,
        "title": e.title,
        "detail": e.detail,
        "data": e.data or {},
        "duration_seconds": e.duration_seconds,
        "source": e.source,
    }


# --------------------------------------------------------------------------- #
#  Permintaan tambahan kuota penyimpanan (dari pengguna, diputuskan admin)       #
# --------------------------------------------------------------------------- #
class StorageDecision(BaseModel):
    granted_mb: float | None = Field(default=None, gt=0)
    note: str = Field(default="", max_length=1000)


@router.get("/storage-requests")
async def list_storage_requests(
    status_filter: str = "pending",
    limit: int = 100,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    """Permintaan tambahan kuota; status_filter = pending | approved | rejected | all."""
    q = select(StorageQuotaRequest).order_by(StorageQuotaRequest.created_at.desc())
    if status_filter in ("pending", "approved", "rejected"):
        q = q.where(StorageQuotaRequest.status == status_filter)
    rows = (await session.scalars(q.limit(max(1, min(int(limit), 500))))).all()
    return [storage_request_svc.to_dict(r) for r in rows]


async def _putuskan(session: AsyncSession, current_user: User, request_id: int, approve: bool, body: StorageDecision) -> dict:
    req = await session.get(StorageQuotaRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permintaan tidak ditemukan.")
    await _assert_can_manage(session, current_user, req.user_id)
    try:
        req = await storage_request_svc.decide(
            session, req, current_user, approve, granted_mb=body.granted_mb, note=body.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await audit_svc.log(
        session, current_user,
        "storage_quota.approve" if approve else "storage_quota.reject",
        "user", req.user_id,
        (f"permintaan #{req.id}: {req.requested_mb:.0f} MB -> diberikan {req.granted_mb:.0f} MB" if approve
         else f"permintaan #{req.id} ({req.requested_mb:.0f} MB) ditolak: {body.note[:200]}"),
    )
    await session.commit()
    return storage_request_svc.to_dict(req)


@router.post("/storage-requests/{request_id}/approve")
async def approve_storage_request(
    request_id: int,
    body: StorageDecision,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Setujui: kuota user di-set ke granted_mb (default = jumlah yang diminta)."""
    return await _putuskan(session, current_user, request_id, True, body)


@router.post("/storage-requests/{request_id}/reject")
async def reject_storage_request(
    request_id: int,
    body: StorageDecision,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Tolak dengan catatan (dikirim ke pemohon)."""
    return await _putuskan(session, current_user, request_id, False, body)


@router.get("/ops/events")
async def list_ops_events(
    kind: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    """Riwayat bukti operasional (backup, restore drill, offsite), terbaru dulu."""
    q = select(OpsEvent).order_by(OpsEvent.created_at.desc())
    if kind in _OPS_KINDS:
        q = q.where(OpsEvent.kind == kind)
    rows = (await session.scalars(q.limit(max(1, min(int(limit), 500))))).all()
    return [_ops_row(e) for e in rows]


@router.delete("/ops/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ops_event(
    event_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Response:
    """Hapus satu catatan riwayat (administrator utama). Penghapusannya sendiri tercatat
    di audit agar jejak bukti tetap bisa ditelusuri; berkas arsip TIDAK ikut dihapus."""
    _require_superadmin(current_user)
    e = await session.get(OpsEvent, event_id)
    if e is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catatan tidak ditemukan.")
    waktu = e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "?"
    await audit_svc.log(
        session, current_user, "ops.event.delete", "ops_event", e.id,
        f"{e.kind}/{e.status} {waktu} — {e.title[:140]}",
    )
    await session.delete(e)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class OpsArchiveDeleteIn(BaseModel):
    archive: str = Field(min_length=8, max_length=128)
    confirm: str = Field(default="", max_length=16)


@router.post("/ops/archives/delete", status_code=status.HTTP_202_ACCEPTED)
async def ops_delete_archive(
    body: OpsArchiveDeleteIn,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    """Hapus berkas arsip terenkripsi di server lewat agen host (beserta .sha256 & manifest).
    Salinan Drive dan snapshot restic tidak disentuh; dipindah ke folder versi oleh sinkronisasi berikutnya."""
    _require_superadmin(current_user)
    try:
        params = ops_requests_svc.validate_delete_params(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await _tolak_bila_sibuk()
    agent = await asyncio.to_thread(ops_requests_svc.agent_status)
    if not agent["alive"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agen host tidak aktif; penghapusan arsip tidak bisa dijalankan sekarang.",
        )
    req = await asyncio.to_thread(
        ops_requests_svc.submit, "delete_archive", params, current_user.id, current_user.username or "", current_user.email,
    )
    await audit_svc.log(session, current_user, "ops.archive.delete", "ops_request", req["id"], f"hapus arsip {params['archive']} dari server")
    await session.commit()
    return req


@router.get("/ops/events.csv")
async def export_ops_events(
    kind: str | None = None,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Response:
    """Ekspor seluruh riwayat bukti sebagai CSV (untuk lampiran audit)."""
    q = select(OpsEvent).order_by(OpsEvent.created_at.asc())
    if kind in _OPS_KINDS:
        q = q.where(OpsEvent.kind == kind)
    rows = (await session.scalars(q)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["waktu", "jenis", "status", "judul", "durasi_detik", "sumber", "data", "detail"])
    for e in rows:
        w.writerow([
            e.created_at.isoformat() if e.created_at else "",
            e.kind, e.status, e.title,
            "" if e.duration_seconds is None else e.duration_seconds,
            e.source,
            json.dumps(e.data or {}, ensure_ascii=False),
            e.detail,
        ])
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bukti_cadangan_{stamp}.csv"'},
    )


def _list_local_archives() -> dict:
    """Arsip .gpg yang masih ada di server (metadata saja; /home di-mount read-only)."""
    base = settings.docker_user_data_root.parent / "backups_enc"
    utama: list[dict] = []
    tier = {"weekly": 0, "monthly": 0}
    try:
        for p in sorted(base.glob("computehub-*.tar.gz.gpg")):
            st = p.stat()
            utama.append({
                "name": p.name,
                "bytes": st.st_size,
                "mtime": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc),
            })
        for nama in tier:
            tier[nama] = len(list((base / nama).glob("computehub-*.tar.gz.gpg")))
    except OSError:
        pass
    utama.sort(key=lambda a: a["mtime"], reverse=True)
    return {"archives": utama, "weekly": tier["weekly"], "monthly": tier["monthly"]}


@router.get("/ops/backup-status")
async def backup_status(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Ringkasan untuk kartu 'Cadangan & Pemulihan': backup/drill terakhir, arsip lokal,
    jumlah snapshot restic yang tercatat, dan kebijakan retensi yang berlaku."""

    async def terakhir(kind: str, **where) -> dict | None:
        q = select(OpsEvent).where(OpsEvent.kind == kind)
        for col, val in where.items():
            q = q.where(getattr(OpsEvent, col) == val)
        e = await session.scalar(q.order_by(OpsEvent.created_at.desc()).limit(1))
        return _ops_row(e) if e else None

    backup_run = await terakhir("backup", source="backup.sh")
    backup_ok = await terakhir("backup", source="backup.sh", status="ok")
    drill = await terakhir("restore_drill")
    drill_ok = await terakhir("restore_drill", status="ok")
    restic_total = await session.scalar(
        select(func.count()).select_from(OpsEvent).where(OpsEvent.dedup_key.like("restic:%"))
    )
    restic_terbaru = await session.scalar(
        select(func.max(OpsEvent.created_at)).where(OpsEvent.dedup_key.like("restic:%"))
    )
    total = await session.scalar(select(func.count()).select_from(OpsEvent))
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc),
        "last_backup": backup_run,
        "last_backup_ok": backup_ok,
        "last_restore_drill": drill,
        "last_restore_drill_ok": drill_ok,
        "restic_snapshots_recorded": int(restic_total or 0),
        "restic_latest_at": restic_terbaru,
        "events_total": int(total or 0),
        "local": await asyncio.to_thread(_list_local_archives),
        "policy": {
            "backup_schedule": "Harian 02:30 WITA: arsip inti (DB + konfigurasi, tanpa workspace) + snapshot restic langsung ke Drive; arsip penuh tiap Minggu; kapan saja lewat tombol Backup sekarang",
            "tar_keep": "Server hanya menyimpan arsip inti 30 hari (kecil); arsip penuh hanya di Google Drive (8 terbaru), salinan server dihapus setelah terverifikasi",
            "restic_keep": "Repo restic di Google Drive: 7 harian, 4 mingguan, 3 bulanan; integritas 5% data diperiksa tiap Minggu",
            "offsite": "Google Drive (rclone copy --immutable + verifikasi md5; arsip inti 90 hari)",
            "restore_drill": "Tanggal 2 tiap bulan 03:30 WITA ke Postgres sementara (arsip inti terbaru); bisa dijalankan kapan saja dari web, termasuk arsip di Drive",
        },
    }


# --------------------------------------------------------------------------- #
#  Backup & restore dari web — antrean permintaan ke agen host (ops_agent.py)     #
# --------------------------------------------------------------------------- #
class OpsRestoreIn(BaseModel):
    source_type: str = Field(pattern="^(archive|snapshot|pre_restore|offsite)$")
    source: str = Field(min_length=8, max_length=128)
    scope: list[str] = Field(default_factory=lambda: ["db", "users"])
    stop_sessions: bool = False
    confirm: str = Field(default="", max_length=32)
    acknowledge_sessions: bool = False


class OpsDrillIn(BaseModel):
    archive: str | None = Field(default=None, max_length=128)


def _require_superadmin(current_user: User) -> None:
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya administrator utama yang boleh menjalankan backup/restore.",
        )


async def _ops_precheck(session: AsyncSession) -> dict:
    """Kondisi yang menentukan aman-tidaknya restore: sesi berjalan, pemeliharaan, agen, antrean."""
    from app.services.devbox import DEVBOX_JOB_NAME, devbox_manager  # lazy: hindari siklus impor
    from app.services.interactive import kernel_manager

    jobs_running = await session.scalar(
        select(func.count()).select_from(Job).where(Job.status == JobStatus.running, Job.name != DEVBOX_JOB_NAME)
    )
    kernels = int(kernel_manager.active_count)
    devboxes = int(devbox_manager.running_count())
    maint = maintenance_svc.state()
    agent = await asyncio.to_thread(ops_requests_svc.agent_status)
    active = await asyncio.to_thread(ops_requests_svc.has_active_request)
    return {
        "jobs_running": int(jobs_running or 0),
        "kernels_active": kernels,
        "devboxes_running": devboxes,
        "sessions_total": int(jobs_running or 0) + kernels + devboxes,
        "maintenance_active": maint.active,
        "agent": agent,
        "active_request": ops_requests_svc.public_view(active) if active else None,
    }


@router.get("/ops/agent")
async def ops_agent(_: User = Depends(require_admin)) -> dict:
    """Detak jantung agen host yang mengeksekusi backup/restore."""
    return await asyncio.to_thread(ops_requests_svc.agent_status)


@router.get("/ops/sources")
async def ops_sources(_: User = Depends(require_admin)) -> dict:
    """Sumber pemulihan: arsip di server (+manifest), snapshot restic, salinan Drive, titik rollback."""
    return await asyncio.to_thread(ops_requests_svc.sources)


@router.get("/ops/precheck")
async def ops_precheck(
    session: AsyncSession = Depends(get_db), _: User = Depends(require_admin),
) -> dict:
    return await _ops_precheck(session)


@router.get("/ops/requests")
async def ops_requests(limit: int = 30, _: User = Depends(require_admin)) -> list[dict]:
    return await asyncio.to_thread(ops_requests_svc.list_requests, limit)


@router.get("/ops/requests/{request_id}")
async def ops_request_detail(request_id: str, _: User = Depends(require_admin)) -> dict:
    req = await asyncio.to_thread(ops_requests_svc.get_request, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permintaan tidak ditemukan.")
    return req


async def _tolak_bila_sibuk() -> None:
    active = await asyncio.to_thread(ops_requests_svc.has_active_request)
    if active and active.get("action") in ("backup", "restore", "drill"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Masih ada permintaan {active.get('action')} yang {active.get('status')} ({active.get('id')}). Tunggu selesai.",
        )


@router.post("/ops/sources/refresh", status_code=status.HTTP_202_ACCEPTED)
async def ops_refresh_sources(current_user: User = Depends(require_admin)) -> dict:
    return await asyncio.to_thread(
        ops_requests_svc.submit, "refresh_sources", {}, current_user.id, current_user.username or "", current_user.email,
    )


@router.post("/ops/backup", status_code=status.HTTP_202_ACCEPTED)
async def ops_backup(
    session: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin),
) -> dict:
    """Backup penuh SEKARANG (arsip tar terenkripsi + restic + offsite) lewat agen host."""
    _require_superadmin(current_user)
    await _tolak_bila_sibuk()
    req = await asyncio.to_thread(
        ops_requests_svc.submit, "backup", {}, current_user.id, current_user.username or "", current_user.email,
    )
    await audit_svc.log(session, current_user, "ops.backup", "ops_request", req["id"], "backup manual dari web")
    await session.commit()
    return req


@router.post("/ops/drill", status_code=status.HTTP_202_ACCEPTED)
async def ops_drill(
    body: OpsDrillIn,
    session: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin),
) -> dict:
    """Uji pulih (restore drill) ke Postgres sementara — produksi tidak disentuh."""
    _require_superadmin(current_user)
    await _tolak_bila_sibuk()
    try:
        req = await asyncio.to_thread(
            ops_requests_svc.submit, "drill", {"archive": body.archive}, current_user.id, current_user.username or "", current_user.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await audit_svc.log(session, current_user, "ops.drill", "ops_request", req["id"], f"uji pulih arsip {body.archive or 'terbaru'}")
    await session.commit()
    return req


@router.post("/ops/restore", status_code=status.HTTP_202_ACCEPTED)
async def ops_restore(
    body: OpsRestoreIn,
    session: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin),
) -> dict:
    """RESTORE PRODUKSI dari web. Destruktif: menimpa DB/workspace sesuai cakupan, aplikasi
    dimatikan sementara oleh agen host. Snapshot kondisi sekarang diambil dulu (titik rollback)."""
    _require_superadmin(current_user)
    try:
        params = ops_requests_svc.validate_restore_params(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await _tolak_bila_sibuk()
    pre = await _ops_precheck(session)
    if not pre["agent"]["alive"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agen host (computehub-ops-agent) tidak aktif — restore tidak bisa dijalankan dari web.",
        )
    if pre["sessions_total"] > 0 and not body.acknowledge_sessions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Masih ada pekerjaan berjalan. Nyalakan mode pemeliharaan dan tunggu sepi, atau centang persetujuan bahwa sesi berjalan akan dihentikan.",
                "precheck": {k: v for k, v in pre.items() if k not in ("agent", "active_request")},
            },
        )
    req = await asyncio.to_thread(
        ops_requests_svc.submit, "restore", params, current_user.id, current_user.username or "", current_user.email,
    )
    await audit_svc.log(
        session, current_user, "ops.restore", "ops_request", req["id"],
        f"restore dari {params['source_type']}:{params['source']} cakupan {','.join(params['scope'])}"
        + (" (sesi berjalan dihentikan)" if params["stop_sessions"] else ""),
    )
    await session.commit()
    return req
