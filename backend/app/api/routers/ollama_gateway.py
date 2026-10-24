"""Endpoint PUBLIK gerbang Ollama (di root domain, bukan /api/v1).

Dipakai klien eksternal lewat domain khusus (mis. ollama.calyzr-ai.my.id) dengan
`Authorization: Bearer <kunci>`. Kompatibel OpenAI (/v1/*) dan Ollama native (/api/*).
Endpoint mutasi model (pull/push/delete/create/copy) diblokir.
"""

from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.ollama_key import OllamaApiKey
from app.services import ollama_gateway as gw

logger = get_logger(__name__)

router = APIRouter(tags=["ollama-gateway"])


async def _auth(session: AsyncSession, authorization: str | None) -> OllamaApiKey:
    if not settings.OLLAMA_GATEWAY_ENABLED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Gerbang Ollama dinonaktifkan")
    raw = ""
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    key = await gw.find_valid_key(session, raw)
    if key is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Kunci API tidak valid / nonaktif / kedaluwarsa",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return key


def _enforce_model(key: OllamaApiKey, model: str | None) -> None:
    allowed = key.models_list()
    if not model:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Field 'model' wajib diisi")
    if model not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Model '{model}' tidak diizinkan untuk kunci ini. Diizinkan: {', '.join(allowed) or '(tidak ada)'}",
        )


def _cap_tokens(key: OllamaApiKey, body: dict, openai_style: bool) -> None:
    if key.max_tokens <= 0:
        return
    if openai_style:
        cur = body.get("max_tokens")
        if cur is None or int(cur) > key.max_tokens:
            body["max_tokens"] = key.max_tokens
    else:
        opts = body.get("options")
        if not isinstance(opts, dict):
            opts = {}
        body["options"] = opts
        cur = opts.get("num_predict")
        if cur is None or int(cur) > key.max_tokens:
            opts["num_predict"] = key.max_tokens


async def _record_use(session: AsyncSession, key: OllamaApiKey) -> None:
    try:
        key.last_used_at = gw._utcnow()
        key.request_count = (key.request_count or 0) + 1
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gagal update pemakaian kunci: %s", exc)


async def _proxy(path: str, body: dict, stream: bool):
    """Teruskan ke Ollama lokal; kembalikan respons (stream atau JSON)."""
    url = settings.OLLAMA_BASE_URL.rstrip("/") + path
    timeout = httpx.Timeout(settings.OLLAMA_GATEWAY_TIMEOUT_SECONDS, connect=15.0)
    client = httpx.AsyncClient(timeout=timeout)
    req = client.build_request("POST", url, json=body)
    resp = await client.send(req, stream=True)
    media = resp.headers.get("content-type", "application/json")

    async def _gen():
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(_gen(), status_code=resp.status_code, media_type=media)


async def _handle_generate(
    path: str, openai_style: bool, request: Request, session: AsyncSession, key: OllamaApiKey
):
    try:
        body = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body JSON tidak valid")
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body JSON harus objek")
    _enforce_model(key, body.get("model"))
    _cap_tokens(key, body, openai_style)
    stream = bool(body.get("stream", False))

    reason = await gw.limiter.acquire(key.id, key.rate_per_min, key.max_concurrent)
    if reason:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, reason)
    try:
        await _record_use(session, key)
        resp = await _proxy(path, body, stream)
    except HTTPException:
        await gw.limiter.release(key.id)
        raise
    except httpx.HTTPError as exc:
        await gw.limiter.release(key.id)
        logger.warning("Gerbang gagal menghubungi Ollama: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gagal menghubungi Ollama server")

    # Lepas slot konkurensi saat stream selesai.
    orig = resp.body_iterator

    async def _wrapped():
        try:
            async for chunk in orig:
                yield chunk
        finally:
            await gw.limiter.release(key.id)

    resp.body_iterator = _wrapped()
    return resp


def _filter_models(data: dict, key: OllamaApiKey) -> dict:
    allowed = set(key.models_list())
    if isinstance(data.get("data"), list):  # OpenAI /v1/models
        data["data"] = [m for m in data["data"] if m.get("id") in allowed]
    if isinstance(data.get("models"), list):  # Ollama /api/tags
        data["models"] = [m for m in data["models"] if m.get("name") in allowed or m.get("model") in allowed]
    return data


async def _list_models(path: str, key: OllamaApiKey):
    url = settings.OLLAMA_BASE_URL.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            r = await client.get(url)
        data = r.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.warning("Gerbang gagal daftar model: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gagal menghubungi Ollama server")
    return JSONResponse(_filter_models(data, key))


# ---- OpenAI-compatible ----
@router.post("/v1/chat/completions")
async def v1_chat(request: Request, authorization: str | None = Header(None),
                  session: AsyncSession = Depends(get_db)):
    key = await _auth(session, authorization)
    return await _handle_generate("/v1/chat/completions", True, request, session, key)


@router.post("/v1/completions")
async def v1_completions(request: Request, authorization: str | None = Header(None),
                         session: AsyncSession = Depends(get_db)):
    key = await _auth(session, authorization)
    return await _handle_generate("/v1/completions", True, request, session, key)


@router.post("/v1/embeddings")
async def v1_embeddings(request: Request, authorization: str | None = Header(None),
                        session: AsyncSession = Depends(get_db)):
    key = await _auth(session, authorization)
    return await _handle_generate("/v1/embeddings", True, request, session, key)


@router.get("/v1/models")
async def v1_models(authorization: str | None = Header(None), session: AsyncSession = Depends(get_db)):
    key = await _auth(session, authorization)
    return await _list_models("/v1/models", key)


# ---- Ollama native ----
@router.post("/api/chat")
async def api_chat(request: Request, authorization: str | None = Header(None),
                   session: AsyncSession = Depends(get_db)):
    key = await _auth(session, authorization)
    return await _handle_generate("/api/chat", False, request, session, key)


@router.post("/api/generate")
async def api_generate(request: Request, authorization: str | None = Header(None),
                       session: AsyncSession = Depends(get_db)):
    key = await _auth(session, authorization)
    return await _handle_generate("/api/generate", False, request, session, key)


@router.post("/api/embed")
async def api_embed(request: Request, authorization: str | None = Header(None),
                    session: AsyncSession = Depends(get_db)):
    key = await _auth(session, authorization)
    return await _handle_generate("/api/embed", False, request, session, key)


@router.post("/api/embeddings")
async def api_embeddings(request: Request, authorization: str | None = Header(None),
                         session: AsyncSession = Depends(get_db)):
    key = await _auth(session, authorization)
    return await _handle_generate("/api/embeddings", False, request, session, key)


@router.get("/api/tags")
async def api_tags(authorization: str | None = Header(None), session: AsyncSession = Depends(get_db)):
    key = await _auth(session, authorization)
    return await _list_models("/api/tags", key)


@router.get("/api/version")
async def api_version(authorization: str | None = Header(None), session: AsyncSession = Depends(get_db)):
    await _auth(session, authorization)
    url = settings.OLLAMA_BASE_URL.rstrip("/") + "/api/version"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            r = await client.get(url)
        return JSONResponse(r.json())
    except (httpx.HTTPError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gagal menghubungi Ollama server")


# ---- Blokir eksplisit endpoint mutasi/manajemen ----
@router.api_route("/api/pull", methods=["POST"])
@router.api_route("/api/push", methods=["POST"])
@router.api_route("/api/delete", methods=["DELETE", "POST"])
@router.api_route("/api/create", methods=["POST"])
@router.api_route("/api/copy", methods=["POST"])
async def _blocked():
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Operasi ini tidak diizinkan lewat gerbang")
