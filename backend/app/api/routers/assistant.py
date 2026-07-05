"""Router asisten AI notebook: status + chat streaming (SSE)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import SlidingWindowRateLimiter
from app.models.user import User
from app.schemas.assistant import AssistantChatRequest, AssistantStatus
from app.services import assistant as assistant_svc

router = APIRouter()

# Rate-limit chat asisten PER-USER: tiap permintaan dihitung; lewat batas -> 429
# (cegah spam & lindungi Ollama bersama saat banyak user aktif).
_chat_limiter = SlidingWindowRateLimiter(
    max_attempts=settings.ASSISTANT_RATE_LIMIT_MAX,
    window_seconds=settings.ASSISTANT_RATE_LIMIT_WINDOW_SECONDS,
    block_seconds=settings.ASSISTANT_RATE_LIMIT_BLOCK_SECONDS,
)


@router.get("/status", response_model=AssistantStatus)
async def assistant_status(
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> AssistantStatus:
    """Status asisten + model efektif utk user ini (override per-user -> default peran)."""
    model = await assistant_svc.resolve_model(session, user)
    return AssistantStatus(**assistant_svc.status(model))


@router.get("/models")
async def assistant_models(_admin: User = Depends(require_admin)) -> list[dict]:
    """Daftar model provider lokal (Ollama) + ukuran (GB) untuk pemilih model admin."""
    return await assistant_svc.list_models()


@router.post("/chat")
async def assistant_chat(
    payload: AssistantChatRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream jawaban asisten sebagai Server-Sent Events.

    Format event: `data: {"delta": "..."}` per potongan, diakhiri `data: [DONE]`.
    """
    # Rate-limit per-user: cegah spam & jaga beban Ollama bersama.
    key = f"assistant:{user.id}"
    limited = _chat_limiter.check(key)
    if not limited.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Terlalu banyak permintaan ke Asisten AI. Coba lagi dalam ~{limited.retry_after} detik.",
            headers={"Retry-After": str(limited.retry_after)},
        )
    _chat_limiter.record_failure(key)

    # Bila pesan menyertakan gambar -> pakai model VISION (multimodal); selain itu
    # model teks per-user/peran seperti biasa.
    if assistant_svc.request_has_images(payload):
        model = assistant_svc.vision_model() or await assistant_svc.resolve_model(session, user)
    else:
        model = await assistant_svc.resolve_model(session, user)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in assistant_svc.stream_chat(payload, model):
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # cegah buffering proxy (nginx/cloudflared)
        },
    )
