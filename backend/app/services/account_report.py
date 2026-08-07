"""Laporan DETAIL per AKUN ComputeHub (padanan `report.user_report` untuk akun OS).

`user_report` menjawab "apa yang dilakukan akun Linux di server". Modul ini menjawab
pertanyaan yang berbeda: "apa yang dilakukan sebuah AKUN PLATFORM" -- job yang
dijalankan, kuota yang berlaku, sesi interaktif, dan pemakaian Asisten AI. Keduanya
tidak bisa saling menggantikan karena satu orang bisa punya akun di kedua sisi.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.job import Job, JobDevice, JobStatus
from app.models.user import User
from app.services import assistant_usage as assistant_usage_svc
from app.services import storage_guard
from app.services import usage_history as usage_history_svc
from app.services import user_policy as user_policy_svc

logger = get_logger(__name__)


def _iso(v) -> str:
    return v.isoformat() if v else ""


async def account_report(
    session: AsyncSession, user_id: int, *, days: int = 30
) -> dict | None:
    """Laporan lengkap satu akun ComputeHub. None bila akun tak ada."""
    user = await session.get(User, user_id)
    if user is None:
        return None

    eff = await user_policy_svc.effective(session, user_id)

    # --- Ringkasan job sepanjang masa ---
    agg = (
        await session.execute(
            select(
                func.count().label("total"),
                func.sum(func.cast(Job.status == JobStatus.succeeded, Integer)).label("sukses"),
                func.sum(func.cast(Job.status == JobStatus.failed, Integer)).label("gagal"),
                func.sum(func.cast(Job.status == JobStatus.cancelled, Integer)).label("batal"),
                func.sum(func.cast(Job.status == JobStatus.running, Integer)).label("jalan"),
                func.sum(func.cast(Job.status == JobStatus.queued, Integer)).label("antre"),
                func.sum(
                    func.cast(Job.device == JobDevice.gpu, Integer)
                    * func.coalesce(Job.actual_runtime_seconds, 0.0)
                ).label("gpu_detik"),
                func.sum(func.coalesce(Job.actual_runtime_seconds, 0.0)).label("total_detik"),
                func.max(Job.peak_vram_mb).label("vram_max"),
                func.max(Job.peak_ram_mb).label("ram_max"),
                func.max(Job.peak_cpu_percent).label("cpu_max"),
                func.min(Job.submitted_at).label("pertama"),
                func.max(Job.submitted_at).label("terakhir"),
            ).where(Job.user_id == user_id)
        )
    ).one()

    # --- Job terakhir (bukti konkret, bukan sekadar angka) ---
    rows = (
        await session.execute(
            select(Job)
            .where(Job.user_id == user_id)
            .order_by(Job.id.desc())
            .limit(15)
        )
    ).scalars().all()
    job_terakhir = [
        {
            "id": j.id,
            "nama": j.name or f"Job #{j.id}",
            "status": j.status.value if hasattr(j.status, "value") else str(j.status),
            "device": j.device.value if hasattr(j.device, "value") else str(j.device),
            "gpu_index": j.gpu_index,
            "interaktif": bool(j.is_interactive),
            "detik": float(j.actual_runtime_seconds or 0.0),
            "vram_mb": float(j.peak_vram_mb or 0.0),
            "ram_mb": float(j.peak_ram_mb or 0.0),
            "selesai": _iso(j.finished_at),
        }
        for j in rows
    ]

    harian = await usage_history_svc.daily_summary_computehub(
        session, days=days, user_id=user_id
    )
    asisten = [
        a
        for a in await assistant_usage_svc.ringkasan(session, days=days, limit=200)
        if a["user_id"] == user_id
    ]

    # Pemakaian penyimpanan pribadi (/persist) -- best-effort.
    dipakai_mb = 0.0
    try:
        dipakai_mb = float(await storage_guard.user_disk_used_bytes(user_id)) / 1024 / 1024
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pemakaian disk akun %s tak terbaca: %s", user_id, exc)

    return {
        "generated_at": dt.datetime.now().astimezone().strftime("%d %b %Y %H:%M:%S %Z"),
        "days": days,
        "akun": {
            "id": user.id,
            "nama": user.name,
            "email": user.email,
            "username_os": user.username or "",
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "aktif": bool(user.is_active),
            "pintu_admin": bool(user.can_admin),
            "sso": bool(user.sso_sub),
            "dibuat": _iso(user.created_at),
        },
        "kuota": {
            "gpu_detik_harian": eff.daily_gpu_seconds_quota,
            "job_serempak": eff.max_concurrent_jobs,
            "batas_waktu_detik": eff.max_time_limit_seconds,
            "vram_mb": eff.max_gpu_memory_mb,
            "ram_mb": eff.max_ram_mb,
            "cpu_threads": eff.max_cpu_threads,
            "storage_mb": eff.max_storage_mb,
            "model_asisten": eff.assistant_model,
            "boleh_multi_gpu": eff.allow_multi_gpu,
        },
        "job": {
            "total": int(agg.total or 0),
            "sukses": int(agg.sukses or 0),
            "gagal": int(agg.gagal or 0),
            "batal": int(agg.batal or 0),
            "jalan": int(agg.jalan or 0),
            "antre": int(agg.antre or 0),
            "gpu_detik": round(float(agg.gpu_detik or 0.0), 1),
            "total_detik": round(float(agg.total_detik or 0.0), 1),
            "vram_max_mb": round(float(agg.vram_max or 0.0), 1),
            "ram_max_mb": round(float(agg.ram_max or 0.0), 1),
            "cpu_max_percent": round(float(agg.cpu_max or 0.0), 1),
            "pertama": _iso(agg.pertama),
            "terakhir": _iso(agg.terakhir),
        },
        "penyimpanan": {
            "dipakai_mb": round(dipakai_mb, 1),
            "kuota_mb": float(eff.max_storage_mb or 0.0),
        },
        "harian": harian,
        "asisten": asisten[0] if asisten else {},
        "job_terakhir": job_terakhir,
    }
