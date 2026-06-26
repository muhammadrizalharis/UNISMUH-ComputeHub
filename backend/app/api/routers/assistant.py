"""Router asisten AI notebook: status + chat streaming (SSE)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_active_user
from app.models.user import User
from app.schemas.assistant import AssistantChatRequest, AssistantStatus
from app.services import assistant as assistant_svc

router = APIRouter()


@router.get("/status", response_model=AssistantStatus)
async def assistant_status(
    _user: User = Depends(get_current_active_user),
) -> AssistantStatus:
    """Apakah asisten aktif & sudah dikonfigurasi (kunci API terisi)."""
    return AssistantStatus(**assistant_svc.status())


@router.post("/chat")
async def assistant_chat(
    payload: AssistantChatRequest,
    _user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """Stream jawaban asisten sebagai Server-Sent Events.

    Format event: `data: {"delta": "..."}` per potongan, diakhiri `data: [DONE]`.
    """

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in assistant_svc.stream_chat(payload):
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
