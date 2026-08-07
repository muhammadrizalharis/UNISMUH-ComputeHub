"""Router admin: pengaturan sistem global, policy per-user, & statistik pemakaian."""

from __future__ import annotations

import asyncio
import csv
import dataclasses
import datetime as dt
import io

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.schemas.admin import (
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
from app.services import maintenance as maintenance_svc
from app.services import pdf as pdf_svc
from app.services import policy as policy_svc
from app.services import report as report_svc
from app.services import usage_history as usage_history_svc
from app.services import user_policy as user_policy_svc
from app.services.cleanup import cleanup_service
from app.models.audit import AuditLog

router = APIRouter()
logger = get_logger(__name__)


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
        "daftar_user": await usage_history_svc.daftar_user(
            session, days=days, include_system=include_system
        ),
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
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Response:
    """Riwayat per user OS sebagai CSV (lampiran laporan/skripsi).

    `per_jam=1` + `username` -> rincian jam-per-jam user tersebut.
    """
    days = max(0, min(int(days), 730))
    if per_jam and username:
        rows = await usage_history_svc.hourly_detail(
            session, username=username, days=days
        )
        kolom = [
            "tanggal", "jam", "rentang", "cpu_avg_percent", "cpu_max_percent",
            "cpu_cores_avg", "ram_max_mb", "vram_max_mb", "proses_max",
            "menit_aktif", "aktivitas", "cuplikan",
        ]
        nama = f"riwayat-jam-{username}-{dt.date.today():%Y%m%d}.csv"
    else:
        rows = await usage_history_svc.daily_summary(
            session, days=days, username=username, include_system=include_system
        )
        kolom = [
            "tanggal", "username", "is_system", "cpu_avg_percent", "cpu_max_percent",
            "cpu_cores_avg", "ram_avg_mb", "ram_max_mb", "vram_max_mb",
            "proses_max", "menit_aktif", "aktivitas", "cuplikan",
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
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Response:
    """Unduh laporan server (HTML, siap cetak ke PDF)."""
    rep = await report_svc.build_report(session)
    html = report_svc.render_full_html(rep)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="laporan_server_{stamp}.html"'
        },
    )


@router.get("/report/user/{username}")
async def report_user(
    username: str,
    _: User = Depends(require_admin),
) -> dict:
    """Laporan DETAIL per-user OS (analisis workload + temuan + rekomendasi)."""
    return await report_svc.user_report(username)


@router.get("/report/user/{username}/download")
async def report_user_download(
    username: str,
    _: User = Depends(require_admin),
) -> Response:
    """Unduh laporan detail per-user sebagai PDF (siap dilampirkan/dicetak)."""
    rep = await report_svc.user_report(username)
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
