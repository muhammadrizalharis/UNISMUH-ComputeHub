"""Pencatatan & rekap pemakaian Asisten AI per AKUN ComputeHub.

Melengkapi `llm_attrib` yang hanya bisa menjawab sisi USER LINUX (pemilik socket).
Permintaan dari web ComputeHub selalu tampak berasal dari proses backend, jadi
tanpa catatan ini beban asisten tidak bisa dipertanggungjawabkan ke siapa pun.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.assistant_usage import AssistantUsage
from app.models.user import User

logger = get_logger(__name__)


async def catat(
    user_id: int,
    model: str,
    *,
    is_vision: bool = False,
    sumber: str = "chat",
    prompt_chars: int = 0,
    reply_chars: int = 0,
    durasi_detik: float = 0.0,
) -> None:
    """Simpan satu permintaan asisten. Best-effort: gagal mencatat != gagal layanan."""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                AssistantUsage(
                    user_id=user_id,
                    model=(model or "")[:128],
                    is_vision=bool(is_vision),
                    sumber=(sumber or "chat")[:16],
                    prompt_chars=max(0, int(prompt_chars)),
                    reply_chars=max(0, int(reply_chars)),
                    durasi_detik=max(0.0, float(durasi_detik)),
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal mencatat pemakaian asisten user %s: %s", user_id, exc)


async def ringkasan(
    session: AsyncSession, *, days: int = 30, limit: int = 50
) -> list[dict]:
    """Rekap pemakaian asisten per akun ComputeHub (paling sering dulu).

    `days <= 0` = sejak awal (arsip permanen).
    """
    q = (
        select(
            User.id,
            func.max(User.name).label("nama"),
            func.max(User.email).label("email"),
            func.count().label("permintaan"),
            func.sum(func.cast(AssistantUsage.is_vision, Integer)).label("vision"),
            func.sum(AssistantUsage.prompt_chars).label("prompt_chars"),
            func.sum(AssistantUsage.reply_chars).label("reply_chars"),
            func.sum(AssistantUsage.durasi_detik).label("detik"),
            func.max(AssistantUsage.ts).label("terakhir"),
        )
        .select_from(AssistantUsage)
        .join(User, AssistantUsage.user_id == User.id)
        .group_by(User.id)
        .order_by(func.count().desc())
        .limit(max(1, limit))
    )
    if days > 0:
        sejak = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        q = q.where(AssistantUsage.ts >= sejak)

    hasil: list[dict] = []
    for r in (await session.execute(q)).all():
        hasil.append(
            {
                "user_id": r.id,
                "nama": r.nama or "",
                "email": r.email or "",
                "permintaan": int(r.permintaan or 0),
                "vision": int(r.vision or 0),
                "prompt_chars": int(r.prompt_chars or 0),
                "reply_chars": int(r.reply_chars or 0),
                "detik": round(float(r.detik or 0.0), 1),
                "terakhir": r.terakhir.isoformat() if r.terakhir else "",
            }
        )
    return hasil
