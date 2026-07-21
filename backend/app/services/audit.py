"""Servis AUDIT LOG — catat aksi penting admin (best-effort, tak pernah melempar).

Pakai: `await audit.log(session, actor, "user.delete", "user", uid, "hapus akun X")`.
Gagal mencatat TIDAK boleh menggagalkan aksi utamanya (hanya warning di log).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.audit import AuditLog
from app.models.user import User

logger = get_logger(__name__)


async def log(
    session: AsyncSession,
    actor: User | None,
    action: str,
    target_type: str = "",
    target_id: int | str = "",
    detail: str = "",
) -> None:
    """Tambahkan baris audit ke SESSION yang sama (ikut commit aksi utama)."""
    try:
        session.add(
            AuditLog(
                actor_id=getattr(actor, "id", None),
                actor_email=getattr(actor, "email", "") or "",
                action=action[:64],
                target_type=target_type[:32],
                target_id=str(target_id)[:64],
                detail=(detail or "")[:2000],
            )
        )
    except Exception as exc:  # noqa: BLE001 — audit tak boleh mematahkan aksi utama
        logger.warning("Gagal mencatat audit %s: %s", action, exc)
