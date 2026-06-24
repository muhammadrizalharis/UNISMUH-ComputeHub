"""Router admin: pengaturan sistem global, policy per-user, & statistik pemakaian."""

from __future__ import annotations

import dataclasses
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.job import Job, JobStatus
from app.models.user import User
from app.schemas.admin import (
    SettingsOut,
    SettingsUpdate,
    UserPolicyOut,
    UserPolicyUpdate,
    UserUsageOut,
)
from app.schemas.report import FullReport
from app.services import policy as policy_svc
from app.services import report as report_svc
from app.services import user_policy as user_policy_svc
from app.services.cleanup import cleanup_service

router = APIRouter()


# ----------------------------------------------------------- policy global
@router.get("/settings", response_model=SettingsOut)
async def get_settings(_: User = Depends(require_admin)) -> dict:
    """Lihat policy global aktif (batas waktu, VRAM, RAM, GPU, kuota, dll)."""
    return policy_svc.get().as_dict()


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(
    payload: SettingsUpdate,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Ubah policy global (admin saja). Berlaku langsung tanpa restart."""
    changes = payload.model_dump(exclude_none=True)
    pol = await policy_svc.update(session, changes)
    return pol.as_dict()


@router.post("/maintenance/cleanup")
async def run_cleanup(_: User = Depends(require_admin)) -> dict:
    """Bersihkan artefak lama SEKARANG (folder job & PDF peringatan kedaluwarsa)."""
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
    _: User = Depends(require_admin),
) -> dict:
    """Lihat override & policy efektif satu user."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User tidak ditemukan.")
    ov = await user_policy_svc.get_overrides(session, user_id)
    eff = await user_policy_svc.effective(session, user_id)
    return _policy_payload(user_id, ov, eff)


@router.patch("/users/{user_id}/policy", response_model=UserPolicyOut)
async def set_user_policy(
    user_id: int,
    payload: UserPolicyUpdate,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Set/ubah batas KHUSUS user ini (kosongkan field = ikut global)."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User tidak ditemukan.")
    changes = payload.model_dump(exclude_unset=True)
    await user_policy_svc.set_overrides(session, user_id, changes)
    ov = await user_policy_svc.get_overrides(session, user_id)
    eff = await user_policy_svc.effective(session, user_id)
    return _policy_payload(user_id, ov, eff)


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
    """Unduh laporan detail per-user (HTML, siap cetak ke PDF)."""
    rep = await report_svc.user_report(username)
    html = report_svc.render_user_html(rep)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in username if c.isalnum() or c in "-_") or "user"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="laporan_{safe}_{stamp}.html"'
        },
    )
