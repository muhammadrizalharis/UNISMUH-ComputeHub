"""Keputusan akses lokal dipakai menu Pengguna dan kotak permintaan admin."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import invalidate_auth_cache
from app.models.access_request import AccessRequest
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.services import audit, provision
from app.services.interactive import kernel_manager
from app.services.devbox import devbox_manager


async def configure(
    session: AsyncSession, user: User, actor: User, *,
    approved: bool, role: UserRole | None, note: str = "",
    request: AccessRequest | None = None,
) -> None:
    if not user.is_local or user.is_superadmin or user.can_admin:
        raise ValueError("Hanya akun lokal non-admin yang dapat diatur lewat keputusan akses.")
    if role == UserRole.admin or (approved and role is None):
        raise ValueError("Pilih peran mahasiswa atau dosen untuk menyetujui akses.")
    if approved and not user.is_active:
        raise ValueError("Aktifkan kembali akun sebelum menyetujui akses fiturnya.")
    was_approved = user.access_approved
    user.access_approved = approved
    if approved and role is not None:
        user.role = role
        user.can_admin = False
    pending = list(await session.scalars(
        select(AccessRequest).where(
            AccessRequest.user_id == user.id, AccessRequest.status == "pending",
        ).with_for_update()
    ))
    if request is not None and request.status != "pending":
        raise ValueError("Permintaan ini sudah diputuskan.")
    for item in pending:
        if approved or item is request:
            item.status = "approved" if approved else "rejected"
            item.decided_at = dt.datetime.now(dt.timezone.utc)
            item.decided_by = actor.email
            item.note = note
    session.add(Notification(
        user_id=user.id, type="access_decision",
        title="Akses fitur disetujui" if approved else (
            "Akses fitur dicabut" if was_approved else "Permintaan akses ditolak"
        ),
        body=(f"Peran Anda: {user.role.value}. " if approved else "") + note,
        link="/minta-akses",
    ))
    await audit.log(
        session, actor, "local_access.approve" if approved else "local_access.reject",
        "user", user.id, f"role={user.role.value}; {note}",
    )
    await session.commit()
    invalidate_auth_cache(user.id)
    if approved:
        await provision.provision_user(user.id)
    elif was_approved:
        await kernel_manager.drop_user_sessions(user.id)
        await devbox_manager.shutdown_user(user.id, alasan="akses fitur dicabut admin")
        await provision.deprovision_user(user.id, remove_data=False)
