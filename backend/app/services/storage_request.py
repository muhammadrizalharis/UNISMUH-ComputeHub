"""Permintaan tambahan kuota penyimpanan: pembuatan, pemberitahuan, keputusan.

Pemberitahuan ke admin mengikuti pola feedback_notify (lonceng + Telegram + email
semua admin aktif) dan ke pemohon lewat lonceng. Semua pemberitahuan best-effort.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.notification import Notification
from app.models.storage_request import StorageQuotaRequest
from app.models.user import User, UserRole
from app.services import email as email_svc
from app.services import storage_guard
from app.services import user_policy as user_policy_svc

logger = get_logger(__name__)

_NOTIFY_TELEGRAM = Path(__file__).resolve().parents[3] / "scripts" / "notify_telegram.py"


def _gb(mb: float) -> str:
    return f"{mb / 1024:.1f} GB"


def to_dict(r: StorageQuotaRequest) -> dict:
    return {
        "id": r.id,
        "created_at": r.created_at,
        "user_id": r.user_id,
        "user_name": r.user_name,
        "user_email": r.user_email,
        "user_role": r.user_role,
        "current_quota_mb": r.current_quota_mb,
        "used_mb": r.used_mb,
        "requested_mb": r.requested_mb,
        "reason": r.reason,
        "status": r.status,
        "decided_at": r.decided_at,
        "decided_by_email": r.decided_by_email,
        "granted_mb": r.granted_mb,
        "decision_note": r.decision_note,
    }


async def pending_for(session: AsyncSession, user_id: int) -> StorageQuotaRequest | None:
    return await session.scalar(
        select(StorageQuotaRequest)
        .where(StorageQuotaRequest.user_id == user_id, StorageQuotaRequest.status == "pending")
        .order_by(StorageQuotaRequest.created_at.desc())
        .limit(1)
    )


async def latest_for(session: AsyncSession, user_id: int) -> StorageQuotaRequest | None:
    return await session.scalar(
        select(StorageQuotaRequest)
        .where(StorageQuotaRequest.user_id == user_id)
        .order_by(StorageQuotaRequest.created_at.desc())
        .limit(1)
    )


async def create(
    session: AsyncSession, user: User, requested_mb: float, reason: str
) -> StorageQuotaRequest:
    """Buat permintaan baru. ValueError bila tidak sah / sudah ada yang pending."""
    if await pending_for(session, user.id) is not None:
        raise ValueError("Masih ada permintaan yang menunggu keputusan admin.")
    eff = await user_policy_svc.effective(session, user.id)
    current = float(getattr(eff, "max_storage_mb", 0.0) or 0.0)
    if current <= 0:
        raise ValueError("Akun Anda tidak dibatasi kuota penyimpanan.")
    if requested_mb <= current:
        raise ValueError(f"Jumlah yang diminta harus lebih besar dari kuota sekarang ({_gb(current)}).")
    if requested_mb > float(settings.STORAGE_REQUEST_MAX_MB):
        raise ValueError(f"Maksimal yang bisa diajukan {_gb(float(settings.STORAGE_REQUEST_MAX_MB))}.")
    snap = storage_guard.user_status(user.id)
    used_mb = float(snap["used_mb"]) if snap else float(await storage_guard.user_disk_used_bytes(user.id)) / 1024 / 1024
    req = StorageQuotaRequest(
        user_id=user.id,
        user_name=user.name or "",
        user_email=user.email or "",
        user_role=user.role.value if hasattr(user.role, "value") else str(user.role),
        current_quota_mb=current,
        used_mb=round(used_mb, 1),
        requested_mb=float(requested_mb),
        reason=reason.strip(),
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    asyncio.create_task(notify_admins(req.id))
    return req


async def decide(
    session: AsyncSession,
    req: StorageQuotaRequest,
    actor: User,
    approve: bool,
    granted_mb: float | None = None,
    note: str = "",
) -> StorageQuotaRequest:
    """Setujui (set override max_storage_mb) atau tolak. Pemohon diberi tahu lewat lonceng."""
    if req.status != "pending":
        raise ValueError("Permintaan ini sudah diputuskan.")
    req.decided_at = dt.datetime.now(dt.timezone.utc)
    req.decided_by_id = actor.id
    req.decided_by_email = actor.email or ""
    req.decision_note = (note or "").strip()
    if approve:
        granted = float(granted_mb if granted_mb is not None else req.requested_mb)
        if granted <= 0:
            raise ValueError("Kuota baru harus lebih dari 0 MB.")
        await user_policy_svc.set_overrides(session, req.user_id, {"max_storage_mb": granted})
        req.status = "approved"
        req.granted_mb = granted
        storage_guard.clear_over(req.user_id, granted)
        judul = f"Permintaan kuota disetujui: {_gb(granted)}"
        isi = f"Kuota penyimpanan Anda kini {_gb(granted)}." + (f" Catatan admin: {req.decision_note}" if req.decision_note else "")
        tipe = "storage_request_approved"
    else:
        req.status = "rejected"
        judul = "Permintaan tambahan kuota ditolak"
        isi = (req.decision_note or "Silakan rapikan berkas yang tidak terpakai di menu Penyimpanan.")
        tipe = "storage_request_rejected"
    session.add(Notification(user_id=req.user_id, type=tipe, title=judul, body=isi, link="/storage"))
    await session.commit()
    await session.refresh(req)
    return req


def _kirim_telegram(judul: str, isi: str) -> None:
    if not _NOTIFY_TELEGRAM.exists():
        return
    subprocess.run([sys.executable, str(_NOTIFY_TELEGRAM), judul, isi], capture_output=True, timeout=30, check=False)


async def notify_admins(request_id: int) -> None:
    """Lonceng ke semua admin aktif + Telegram + email. Best-effort (tak melempar)."""
    try:
        async with AsyncSessionLocal() as session:
            req = await session.get(StorageQuotaRequest, request_id)
            if req is None:
                return
            admins = (
                await session.execute(
                    select(User.id, User.email).where(User.role == UserRole.admin, User.is_active.is_(True))
                )
            ).all()
            ringkas = (
                f"{req.user_name or req.user_email} ({req.user_role}) meminta {_gb(req.requested_mb)} "
                f"(sekarang {_gb(req.current_quota_mb)}, terpakai {_gb(req.used_mb)})."
            )
            if req.reason.strip().startswith("[UJI QA]"):
                return
            for admin_id, _ in admins:
                session.add(Notification(
                    user_id=admin_id, type="storage_request",
                    title="Permintaan tambahan kuota penyimpanan", body=ringkas, link="/admin#kuota",
                ))
            await session.commit()
            recipients = sorted({e.strip() for (_, e) in admins if e and e.strip()})
        base = settings.public_base_url
        link = f"{base}/admin#kuota" if base else ""
        alasan = req.reason.strip()[:800]
        try:
            isi = f"{ringkas}\n\nAlasan: {alasan}" + (f"\n\nTinjau: {link}" if link else "")
            await asyncio.to_thread(_kirim_telegram, f"\U0001f4be Permintaan kuota #{req.id} \u2014 {settings.PROJECT_NAME}", isi)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Telegram permintaan kuota #%d gagal: %r", request_id, exc)
        if not recipients or not settings.smtp_configured:
            return
        try:
            await asyncio.to_thread(
                email_svc.send_email,
                recipients,
                f"Permintaan tambahan kuota penyimpanan dari {req.user_name or req.user_email} \u2014 {settings.PROJECT_NAME}",
                "\n".join([ringkas, "", f"Alasan: {alasan}", "", f"Tinjau & putuskan: {link}" if link else ""]),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Email permintaan kuota #%d gagal: %r", request_id, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify_admins kuota #%d gagal total: %r", request_id, exc)
