"""Asisten AI notebook: proxy streaming ke provider OpenAI-compatible.

Tidak mengikat ke satu vendor — base URL + kunci + model dibaca dari konfigurasi
(.env). Default menunjuk GitHub Models sehingga begitu user mengisi GitHub token
(scope models:read) asisten langsung aktif. Bisa diarahkan ke OpenAI/OpenRouter/
Groq atau server vLLM/Ollama lokal tanpa mengubah kode.

Bila kunci belum diisi, service tetap menstream pesan fallback yang jelas agar UI
dapat diuji penuh tanpa kredensial.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.assistant import AssistantChatRequest

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "Kamu adalah asisten coding di dalam UNISMUH ComputeHub, sebuah notebook "
    "interaktif ala Google Colab yang berjalan di GPU server kampus (PyTorch + CUDA "
    "tersedia, library data science umum sudah terpasang). Bantu pengguna menulis, "
    "menjelaskan, dan memperbaiki kode Python untuk sel notebook. Jawab ringkas dan "
    "to the point dalam Bahasa Indonesia (kecuali pengguna memakai bahasa lain). "
    "Saat memberi kode, gunakan blok kode berpagar ```python agar mudah disisipkan "
    "ke sel. Jangan mengarang API yang tidak ada."
)

# Batas konteks agar payload tetap wajar.
_MAX_CONTEXT_CHARS = 12_000
_MAX_CELL_CHARS = 8_000


def status() -> dict:
    return {
        "enabled": settings.ASSISTANT_ENABLED,
        "configured": settings.assistant_configured,
        "model": settings.ASSISTANT_MODEL,
        "provider": settings.ASSISTANT_PROVIDER_LABEL,
    }


def _build_messages(req: AssistantChatRequest) -> list[dict[str, str]]:
    """Susun daftar pesan OpenAI: system + konteks notebook + riwayat percakapan."""
    msgs: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    context_parts: list[str] = []
    if req.notebook_context and req.notebook_context.strip():
        ctx = req.notebook_context.strip()[-_MAX_CONTEXT_CHARS:]
        context_parts.append(
            "Isi notebook pengguna saat ini (semua sel kode):\n```python\n" + ctx + "\n```"
        )
    if req.cell_code and req.cell_code.strip():
        cell = req.cell_code.strip()[:_MAX_CELL_CHARS]
        context_parts.append(
            "Sel yang sedang difokuskan pengguna:\n```python\n" + cell + "\n```"
        )
    if context_parts:
        msgs.append({"role": "system", "content": "\n\n".join(context_parts)})

    for m in req.messages:
        if m.role in ("user", "assistant") and m.content.strip():
            msgs.append({"role": m.role, "content": m.content})
    return msgs


async def _stream_fallback(req: AssistantChatRequest) -> AsyncIterator[str]:
    """Tanpa kredensial: jelaskan cara mengaktifkan, plus echo ringkas."""
    last = next(
        (m.content for m in reversed(req.messages) if m.role == "user"), ""
    ).strip()
    text = (
        "Asisten AI belum dikonfigurasi.\n\n"
        "Untuk mengaktifkannya, isi `ASSISTANT_API_KEY` di `backend/.env` "
        "(mis. GitHub token dengan scope `models:read`), lalu restart layanan. "
        "Model & provider bisa diatur lewat `ASSISTANT_MODEL` dan `ASSISTANT_API_BASE`.\n\n"
    )
    if last:
        text += f"Pesanmu tadi: _{last[:300]}_"
    # Stream per-kata supaya UI terasa hidup.
    for i, word in enumerate(text.split(" ")):
        yield (word if i == 0 else " " + word)


async def _stream_provider(req: AssistantChatRequest) -> AsyncIterator[str]:
    """Stream dari provider OpenAI-compatible (SSE chat completions)."""
    payload = {
        "model": settings.ASSISTANT_MODEL,
        "messages": _build_messages(req),
        "stream": True,
        "temperature": settings.ASSISTANT_TEMPERATURE,
        "max_tokens": settings.ASSISTANT_MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {settings.ASSISTANT_API_KEY.strip()}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    url = settings.assistant_chat_url
    timeout = httpx.Timeout(settings.ASSISTANT_TIMEOUT_SECONDS, connect=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")[:500]
                    logger.warning(
                        "Asisten provider balas %s: %s", resp.status_code, body
                    )
                    yield (
                        f"⚠️ Provider AI menolak permintaan (HTTP {resp.status_code}). "
                        "Periksa ASSISTANT_API_KEY / ASSISTANT_MODEL / ASSISTANT_API_BASE."
                    )
                    return
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0]["delta"].get("content")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta
    except httpx.TimeoutException:
        yield "⚠️ Permintaan ke provider AI melebihi batas waktu. Coba lagi."
    except httpx.HTTPError as exc:  # noqa: BLE001
        logger.warning("Asisten gagal menghubungi provider: %s", exc)
        yield "⚠️ Gagal menghubungi provider AI. Periksa koneksi/konfigurasi."


async def stream_chat(req: AssistantChatRequest) -> AsyncIterator[str]:
    """Hasilkan potongan teks jawaban (delta) untuk di-stream ke klien."""
    if settings.assistant_configured:
        async for chunk in _stream_provider(req):
            yield chunk
    else:
        async for chunk in _stream_fallback(req):
            yield chunk
