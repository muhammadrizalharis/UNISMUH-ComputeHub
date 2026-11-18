"""Router Tanya Dokumen: koleksi dokumen pribadi + chat berbasis isi dokumen."""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.api.routers.assistant import _chat_limiter, _sse
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import SlidingWindowRateLimiter
from app.models.user import User
from app.models.user_document import UserDocument
from app.schemas.assistant import AssistantChatRequest, LibraryChatRequest
from app.services import assistant as assistant_svc
from app.services import assistant_usage as assistant_usage_svc
from app.services import doc_extract, doc_library, storage_guard
from app.services import user_policy as user_policy_svc

router = APIRouter()

_upload_limiter = SlidingWindowRateLimiter(max_attempts=40, window_seconds=60, block_seconds=60)
_UPLOAD_ID = re.compile(r"^[a-f0-9]{32}$")
_MAX_CHUNK = 16 * 1024 * 1024
# upload_id -> {"user": id, "limit": byte, "written": byte, "name": str, "t": waktu}
_uploads: dict[str, dict] = {}
_UPLOAD_TTL = 6 * 3600

DOC_QA_PROMPT = """Kamu adalah asisten "Tanya Dokumen" ComputeHub UNISMUH.
Tugasmu menjawab pertanyaan pengguna BERDASARKAN KUTIPAN DOKUMEN MILIKNYA yang
disertakan (ditandai [D1], [D2], ...).

Aturan:
- Jawab dalam Bahasa Indonesia yang jelas, kecuali pengguna memakai bahasa lain.
- Gunakan hanya informasi dari kutipan. Cantumkan nomor kutipan, mis. [D1], pada
  setiap informasi yang diambil darinya.
- Bila kutipan tidak memuat jawabannya, katakan terus terang bahwa jawabannya tidak
  ditemukan di dokumen. Boleh menambahkan pengetahuan umum hanya bila diberi label
  jelas "(di luar dokumen)".
- Jangan mengarang kutipan, nomor halaman, penulis, atau angka yang tidak ada.
- Untuk permintaan ringkasan, rangkum poin penting dari kutipan yang tersedia dan
  ingatkan bahwa ringkasan hanya mencakup bagian yang relevan dengan pertanyaan.
"""


def _require_enabled() -> None:
    if not settings.docs_library_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Fitur Tanya Dokumen belum diaktifkan."
        )


def _doc_out(d: UserDocument) -> dict:
    return {
        "id": d.id,
        "name": d.filename,
        "size_bytes": d.size_bytes,
        "status": d.status,
        "error": d.error,
        "engine": d.engine,
        "chars": d.chars,
        "chunks": d.chunks,
        "truncated": d.truncated,
        "created_at": d.created_at,
        "indexed_at": d.indexed_at,
    }


@router.get("")
async def list_documents(user: User = Depends(get_current_active_user)) -> dict:
    if not settings.docs_library_enabled:
        return {"enabled": False, "folder": settings.DOCS_LIBRARY_FOLDER, "docs": []}
    docs = await doc_library.sync_folder(user.id)
    return {
        "enabled": True,
        "folder": settings.DOCS_LIBRARY_FOLDER,
        "docs": [_doc_out(d) for d in docs],
    }


def _open_nofollow(path: Path, flags: int):
    """Buka untuk tulis tanpa mengikuti symlink (berkas sementara ada di /persist pengguna)."""
    fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | flags, 0o644)
    return os.fdopen(fd, "wb")


def _expire_uploads() -> None:
    now = time.time()
    for uid, info in list(_uploads.items()):
        if now - info["t"] > _UPLOAD_TTL:
            _uploads.pop(uid, None)
            tmp = doc_library.folder(info["user"]) / f".{uid}.unggah"
            tmp.unlink(missing_ok=True)


@router.post("/upload")
async def upload_chunk(
    request: Request,
    upload_id: str = Query(...),
    name: str = Query(..., max_length=300),
    first: bool = Query(default=False),
    last: bool = Query(default=False),
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Unggah bertahap (raw bytes per potongan) agar tahan batas ukuran body proxy.

    first=1 pada potongan pertama, last=1 pada potongan terakhir. Batasnya hanya sisa
    kuota disk pengguna (sama dengan unggahan lain di ComputeHub).
    """
    _require_enabled()
    if not _UPLOAD_ID.match(upload_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "upload_id tidak valid.")
    if not doc_extract.is_allowed(name):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Jenis berkas belum didukung. Gunakan PDF, Word, PowerPoint, Excel, "
            "OpenDocument, atau teks (txt/md/csv/json/html).",
        )
    _expire_uploads()
    tmp = doc_library.folder(user.id) / f".{upload_id}.unggah"
    if first:
        key = f"doc-upload:{user.id}"
        limited = _upload_limiter.check(key)
        if not limited.allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Terlalu banyak unggahan. Coba lagi dalam ~{limited.retry_after} detik.",
                headers={"Retry-After": str(limited.retry_after)},
            )
        _upload_limiter.record_failure(key)
        eff = await user_policy_svc.effective(session, user.id)
        limit = await storage_guard.upload_limit_bytes(user.id, eff.max_storage_mb)
        await asyncio.to_thread(tmp.parent.mkdir, parents=True, exist_ok=True)
        if not doc_library.folder_ok(user.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Folder /persist/{settings.DOCS_LIBRARY_FOLDER} berupa tautan (symlink). "
                "Ganti dengan folder biasa lalu coba lagi.",
            )
        await asyncio.to_thread(_open_nofollow(tmp, os.O_CREAT | os.O_TRUNC).close)
        _uploads[upload_id] = {
            "user": user.id, "limit": limit, "written": 0, "name": name, "t": time.time(),
        }
    info = _uploads.get(upload_id)
    if info is None or info["user"] != user.id or info["name"] != name:
        raise HTTPException(status.HTTP_409_CONFLICT, "Sesi unggah tidak ditemukan. Ulangi unggah.")

    if not doc_library.folder_ok(user.id):
        _uploads.pop(upload_id, None)
        raise HTTPException(status.HTTP_409_CONFLICT, "Folder Dokumen-AI berubah. Ulangi unggah.")

    body = await request.body()
    if len(body) > _MAX_CHUNK:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Potongan terlalu besar.")
    if info["written"] + len(body) > info["limit"]:
        _uploads.pop(upload_id, None)
        tmp.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Sisa kuota penyimpanan Anda tidak cukup untuk berkas ini. Hapus berkas yang "
            "tidak dipakai di menu Penyimpanan atau ajukan tambahan kuota.",
        )

    def _append() -> None:
        with _open_nofollow(tmp, os.O_APPEND) as fh:
            fh.write(body)

    await asyncio.to_thread(_append)
    info["written"] += len(body)
    info["t"] = time.time()
    if not last:
        return {"ok": True, "written": info["written"]}

    _uploads.pop(upload_id, None)
    if info["written"] == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Berkas kosong.")
    try:
        doc = await doc_library.save_upload(user.id, name, tmp)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _doc_out(doc)


@router.delete("/{doc_id}")
async def delete_document(doc_id: int, user: User = Depends(get_current_active_user)) -> dict:
    _require_enabled()
    if not await doc_library.delete_doc(user.id, doc_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dokumen tidak ditemukan.")
    return {"ok": True}


@router.post("/{doc_id}/reindex")
async def reindex_document(doc_id: int, user: User = Depends(get_current_active_user)) -> dict:
    _require_enabled()
    if not await doc_library.reindex(user.id, doc_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dokumen tidak ditemukan.")
    return {"ok": True}


@router.get("/{doc_id}/file")
async def download_document(
    doc_id: int, user: User = Depends(get_current_active_user)
) -> FileResponse:
    doc = await doc_library.get_doc(user.id, doc_id)
    path = doc_library.safe_file(user.id, doc.filename) if doc else None
    if doc is None or path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dokumen tidak ditemukan.")
    return FileResponse(path, filename=doc.filename)


@router.post("/chat")
async def library_chat(
    payload: LibraryChatRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Jawab pertanyaan dari dokumen pribadi pengguna (SSE).

    Event: {"status": ...}, {"doc_sources": [{n, doc_id, name, section}]}, {"delta": ...},
    diakhiri `data: [DONE]`.
    """
    _require_enabled()
    key = f"assistant:{user.id}"  # anggaran per pengguna sama dengan Asisten AI
    limited = _chat_limiter.check(key)
    if not limited.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Terlalu banyak permintaan. Coba lagi dalam ~{limited.retry_after} detik.",
            headers={"Retry-After": str(limited.retry_after)},
        )
    _chat_limiter.record_failure(key)

    clean = AssistantChatRequest(
        messages=[type(m)(role=m.role, content=m.content) for m in payload.messages]
    )
    model = await assistant_svc.resolve_model(session, user)
    tanya = [m.content.strip() for m in clean.messages if m.role == "user" and m.content.strip()]
    kueri = "\n".join(tanya[-2:])[-1500:]
    prompt_chars = sum(len(m.content or "") for m in clean.messages)

    async def event_stream() -> AsyncIterator[str]:
        mulai = time.monotonic()
        balasan = 0
        try:
            yield _sse({"status": "Mencari di dokumen Anda…"})
            hits = await doc_library.retrieve(user.id, kueri, payload.doc_ids or None)
            context, sources = doc_library.format_context(hits)
            yield _sse({"doc_sources": sources})
            if context:
                block = (
                    "KUTIPAN DOKUMEN SAYA (paling relevan dengan pertanyaan):\n\n" + context
                )
                yield _sse({"status": "Menyusun jawaban dari dokumen…"})
            else:
                block = (
                    "KUTIPAN DOKUMEN SAYA: tidak ditemukan bagian dokumen yang relevan "
                    "dengan pertanyaan ini."
                )
                yield _sse({"status": "Tidak ada bagian dokumen yang relevan…"})
            async for chunk in assistant_svc.stream_chat(
                clean, model, system_override=DOC_QA_PROMPT, context_block=block
            ):
                balasan += len(chunk)
                yield _sse({"delta": chunk})
        finally:
            yield "data: [DONE]\n\n"
            await assistant_usage_svc.catat(
                user.id,
                model,
                is_vision=False,
                sumber="dokumen",
                prompt_chars=prompt_chars,
                reply_chars=balasan,
                durasi_detik=time.monotonic() - mulai,
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
