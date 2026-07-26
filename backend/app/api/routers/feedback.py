"""Router SARAN/MASUKAN (menu Saran).

Semua peran boleh mengirim & melihat kiriman miliknya sendiri. Admin & super
admin melihat semua, mengubah status tindak lanjut, dan menghapus spam.
Saran baru -> pemberitahuan Telegram + email semua admin (fire-and-forget).
"""

from __future__ import annotations

import asyncio
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_admin
from app.models.feedback import Feedback
from app.models.user import User
from app.schemas.feedback import FeedbackCreate, FeedbackOut, FeedbackStatusUpdate
from app.services import feedback_notify

router = APIRouter()

# Anti-spam: maksimal kiriman per user per 24 jam (dihitung dari baris yang
# masih ada — saran yang dihapus admin tidak ikut terhitung).
MAX_PER_DAY = 10


@router.post("", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    payload: FeedbackCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Feedback:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    sent_today = await session.scalar(
        select(func.count())
        .select_from(Feedback)
        .where(Feedback.user_id == current_user.id, Feedback.created_at >= since)
    )
    if (sent_today or 0) >= MAX_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=f"Batas {MAX_PER_DAY} saran per 24 jam tercapai. Coba lagi besok.",
        )

    fb = Feedback(
        user_id=current_user.id,
        user_name=(current_user.name or current_user.username or "").strip(),
        user_role=current_user.role.value,
        category=payload.category,
        message=payload.message.strip(),
    )
    session.add(fb)
    await session.commit()
    await session.refresh(fb)

    # Kabari pengelola tanpa menahan respons (best-effort).
    asyncio.create_task(feedback_notify.notify_new_feedback(fb.id))
    return fb


@router.get("/mine", response_model=list[FeedbackOut])
async def list_my_feedback(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[Feedback]:
    rows = await session.execute(
        select(Feedback)
        .where(Feedback.user_id == current_user.id)
        .order_by(Feedback.created_at.desc())
        .limit(50)
    )
    return list(rows.scalars())


@router.get("", response_model=list[FeedbackOut])
async def list_all_feedback(
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[Feedback]:
    rows = await session.execute(
        select(Feedback).order_by(Feedback.created_at.desc()).limit(200)
    )
    return list(rows.scalars())


@router.patch("/{feedback_id}", response_model=FeedbackOut)
async def update_feedback_status(
    feedback_id: int,
    payload: FeedbackStatusUpdate,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> Feedback:
    fb = await session.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="Saran tidak ditemukan.")
    fb.status = payload.status
    await session.commit()
    await session.refresh(fb)
    return fb


@router.delete("/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback(
    feedback_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    fb = await session.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="Saran tidak ditemukan.")
    await session.delete(fb)
    await session.commit()
