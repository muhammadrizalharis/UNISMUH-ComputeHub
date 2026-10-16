"""Permintaan akses Google lokal dan keputusan admin, dengan notifikasi atomik."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_session_user, require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.access_request import AccessRequest
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.services import local_access

router = APIRouter()


class CreateRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class Decision(BaseModel):
    approved: bool
    role: UserRole | None = None
    note: str = Field(default="", max_length=2000)


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    created_at: dt.datetime
    reason: str
    status: str
    decided_at: dt.datetime | None
    decided_by: str
    note: str
    user_name: str = ""
    user_email: str = ""


@router.get("", response_model=list[RequestOut])
async def list_requests(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_session_user),
) -> list[RequestOut]:
    if user.role != UserRole.admin and not user.is_local:
        raise HTTPException(403, "Menu ini hanya untuk akun lokal dan admin.")
    query = select(AccessRequest, User).join(User, User.id == AccessRequest.user_id)
    if user.role != UserRole.admin:
        query = query.where(AccessRequest.user_id == user.id)
    rows = (await session.execute(query.order_by(AccessRequest.id.desc()).limit(100))).all()
    results = []
    for item, owner in rows:
        out = RequestOut.model_validate(item)
        out.user_name, out.user_email = owner.name, owner.email
        results.append(out)
    return results


@router.post("", response_model=RequestOut, status_code=201)
async def create_request(
    payload: CreateRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_session_user),
) -> AccessRequest:
    reason = payload.reason.strip()
    if len(reason) < 5:
        raise HTTPException(400, "Jelaskan alasan permintaan akses minimal 5 karakter.")
    await session.scalar(select(User).where(User.id == user.id).with_for_update())
    await session.refresh(user)
    if not user.is_local or user.role == UserRole.admin or not user.features_locked:
        raise HTTPException(403, "Permintaan akses hanya untuk akun lokal yang fiturnya terkunci.")
    pending = await session.scalar(select(AccessRequest.id).where(
        AccessRequest.user_id == user.id, AccessRequest.status == "pending",
    ))
    if pending is not None:
        raise HTTPException(409, "Permintaan sebelumnya masih menunggu keputusan admin.")
    item = AccessRequest(user_id=user.id, reason=reason)
    session.add(item)
    admins = list(await session.scalars(select(User.id).where(
        User.is_active.is_(True),
        or_(User.can_admin.is_(True), User.role == UserRole.admin,
            func.lower(User.email) == (settings.FIRST_ADMIN_EMAIL or "").strip().lower()),
    )))
    if not admins:
        raise HTTPException(503, "Belum ada admin aktif untuk menerima permintaan. Hubungi pengelola.")
    for admin_id in admins:
        session.add(Notification(
            user_id=admin_id, type="access_request", title="Permintaan akses akun lokal",
            body=f"{user.name} ({user.email}): {reason}", link="/permintaan-akses",
        ))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Permintaan sebelumnya masih menunggu keputusan admin.") from exc
    await session.refresh(item)
    return item


@router.put("/users/{user_id}")
async def configure_user(
    user_id: int, payload: Decision,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
) -> dict:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(404, "Akun tidak ditemukan.")
    try:
        await local_access.configure(
            session, user, actor, approved=payload.approved, role=payload.role, note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"access_approved": user.access_approved}


@router.post("/{request_id}/decision")
async def decide_request(
    request_id: int, payload: Decision,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
) -> dict:
    item = await session.get(AccessRequest, request_id)
    if item is None:
        raise HTTPException(404, "Permintaan tidak ditemukan.")
    # Urutan lock sama seperti pembuatan/konfigurasi manual: user lalu permintaan.
    user = await session.scalar(select(User).where(User.id == item.user_id).with_for_update())
    await session.refresh(item)
    if item.status != "pending":
        raise HTTPException(409, "Permintaan ini sudah diputuskan.")
    try:
        await local_access.configure(
            session, user, actor, approved=payload.approved, role=payload.role,
            note=payload.note, request=item,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": item.status}
