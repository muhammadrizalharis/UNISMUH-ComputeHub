"""Router asisten AI notebook: status + chat streaming (SSE)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_active_user, require_admin
from app.models.user import User
from app.schemas.assistant import AssistantChatRequest, AssistantStatus
from app.services import assistant as assistant_svc

router = APIRouter()


@router.get("/status", response_model=AssistantStatus)
async def assistant_status(
    user: User = Depends(get_current_active_user),
) -> AssistantStatus:
    """Status asisten + model yang dipakai untuk peran user ini."""
    return AssistantStatus(**assistant_svc.status(role=user.role))


@router.get("/models")
async def assistant_models(_admin: User = Depends(require_admin)) -> list[dict]:
    """Daftar model provider lokal (Ollama) + ukuran (GB) untuk pemilih model admin."""
    return await assistant_svc.list_models()


@router.post("/chat")
async def assistant_chat(
    payload: AssistantChatRequest,
    user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """Stream jawaban asisten sebagai Server-Sent Events.

    Format event: `data: {"delta": "..."}` per potongan, diakhiri `data: [DONE]`.
    """

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in assistant_svc.stream_chat(payload, role=user.role):
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
