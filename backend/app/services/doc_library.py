"""Tanya Dokumen pribadi: berkas di /persist/Dokumen-AI -> teks -> potongan -> Qdrant.

Folder pengguna adalah SUMBER KEBENARAN. Berkas yang ditaruh lewat halaman Tanya
Dokumen, menu Penyimpanan, atau Devbox ikut diindeks; berkas yang dihapus/dipindah
keluar dari folder otomatis dikeluarkan dari indeks (lihat ``sync_folder``).

Satu koleksi Qdrant untuk semua pengguna; setiap titik membawa ``user_id`` dan
pencarian SELALU difilter ``user_id`` sehingga pengguna hanya mengakses dokumennya
sendiri. Tidak ada batas jumlah/ukuran selain kuota disk pengguna.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
import unicodedata
import uuid
from pathlib import Path, PurePath

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.user_document import UserDocument
from app.services import doc_extract, help_rag, storage_guard
from app.services import workspace as workspace_svc

logger = get_logger(__name__)

_EMBED_BATCH = 16
_NS = uuid.UUID("0b8e9f5c-37a4-4d55-9c7e-5f1f2d3c8a90")
_NAME_MAX = 150
_STALE_UPLOAD = 24 * 3600
_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')

_queue: asyncio.Queue[int] | None = None
_workers: list[asyncio.Task] = []
_queued: set[int] = set()
_collection_ready = False


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ------------------------------------------------------------------ berkas
def folder(user_id: int) -> Path:
    return workspace_svc.user_root(user_id) / settings.DOCS_LIBRARY_FOLDER


def folder_ok(user_id: int) -> bool:
    """Folder dokumen benar-benar milik pengguna (bukan symlink ke tempat lain).

    Pengguna bisa membuat symlink dari notebook/Devbox, sedangkan backend punya akses ke
    /persist semua pengguna -> wajib dicek sebelum membaca/menulis.
    """
    d = folder(user_id)
    try:
        expected = workspace_svc.user_root(user_id).resolve() / settings.DOCS_LIBRARY_FOLDER
        return d.resolve() == expected and not d.is_symlink()
    except OSError:
        return False


def safe_file(user_id: int, name: str) -> Path | None:
    """Path berkas dokumen bila aman dibaca (berkas biasa langsung di folder, bukan symlink)."""
    if not folder_ok(user_id) or not name or "/" in name or name in (".", ".."):
        return None
    p = folder(user_id) / name
    if p.is_symlink() or not p.is_file():
        return None
    return p


def safe_filename(name: str) -> str:
    """Nama berkas aman (tanpa path/karakter kontrol), ekstensi dipertahankan."""
    base = unicodedata.normalize("NFC", PurePath((name or "").replace("\\", "/")).name)
    base = _BAD_CHARS.sub("_", base).strip(" .")
    ext = doc_extract.extension_of(base)
    stem = base[: -len(ext)] if ext else base
    stem = stem[: _NAME_MAX - len(ext)].strip(" .") or "dokumen"
    return stem + ext


def unique_path(directory: Path, name: str) -> Path:
    target = directory / name
    if not target.exists():
        return target
    ext = doc_extract.extension_of(name)
    stem = name[: -len(ext)] if ext else name
    for i in range(2, 1000):
        cand = directory / f"{stem} ({i}){ext}"
        if not cand.exists():
            return cand
    raise ValueError("Terlalu banyak berkas dengan nama yang sama.")


def _scan(user_id: int) -> dict[str, tuple[int, float]]:
    """{nama: (ukuran, mtime)} berkas yang didukung di folder (tidak rekursif).

    Sisa unggahan yang terputus (.<id>.unggah) lebih dari sehari ikut dibersihkan.
    """
    d = folder(user_id)
    out: dict[str, tuple[int, float]] = {}
    if not d.is_dir() or not folder_ok(user_id):
        return out
    now = time.time()
    for p in d.iterdir():
        if p.name.startswith(".") and p.name.endswith(".unggah") and p.is_file():
            if now - p.stat().st_mtime > _STALE_UPLOAD:
                p.unlink(missing_ok=True)
            continue
        if p.name.startswith(".") or not p.is_file() or p.is_symlink():
            continue
        if not doc_extract.is_allowed(p.name):
            continue
        st = p.stat()
        out[p.name] = (st.st_size, st.st_mtime)
    return out


# ------------------------------------------------------------------ qdrant
def _coll() -> str:
    return (
        f"{settings.HELP_RAG_QDRANT_URL.strip().rstrip('/')}"
        f"/collections/{settings.DOCS_LIBRARY_COLLECTION}"
    )


def _point_id(doc_id: int, idx: int) -> str:
    return str(uuid.uuid5(_NS, f"{doc_id}:{idx}"))


async def _ensure_collection(client: httpx.AsyncClient) -> None:
    global _collection_ready
    if _collection_ready:
        return
    resp = await client.get(_coll())
    if resp.status_code != 200:
        dim = len((await help_rag.embed(client, ["dimensi"]))[0])
        resp = await client.put(_coll(), json={"vectors": {"size": dim, "distance": "Cosine"}})
        resp.raise_for_status()
    for field in ("user_id", "doc_id"):
        resp = await client.put(
            f"{_coll()}/index?wait=true",
            json={"field_name": field, "field_schema": "integer"},
        )
        resp.raise_for_status()
    _collection_ready = True


async def _delete_points(client: httpx.AsyncClient, doc_id: int) -> None:
    resp = await client.post(
        f"{_coll()}/points/delete?wait=true",
        json={"filter": {"must": [{"key": "doc_id", "match": {"value": int(doc_id)}}]}},
    )
    if resp.status_code != 404:
        resp.raise_for_status()


async def remove_index(doc_id: int) -> None:
    """Hapus titik dokumen dari Qdrant (best-effort)."""
    if not settings.help_rag_enabled:
        return
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            await _delete_points(client, doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tanya Dokumen: gagal menghapus indeks dokumen #%s: %s", doc_id, exc)


# ------------------------------------------------------------------ sinkron folder
async def sync_folder(user_id: int) -> list[UserDocument]:
    """Samakan tabel dengan isi folder lalu kembalikan daftar dokumen (terbaru dulu)."""
    files = await asyncio.to_thread(_scan, user_id)
    removed: list[int] = []
    to_queue: list[int] = []
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(select(UserDocument).where(UserDocument.user_id == user_id))
        ).all()
        known = {r.filename: r for r in rows}
        for r in rows:
            info = files.get(r.filename)
            if info is None:
                removed.append(r.id)
                await session.delete(r)
            elif (r.size_bytes, round(r.mtime, 3)) != (info[0], round(info[1], 3)):
                # Berkas diganti dengan isi baru -> indeks ulang.
                r.size_bytes, r.mtime = info
                r.status, r.error = "antre", None
                to_queue.append(r.id)
        for name, (size, mtime) in files.items():
            if name not in known:
                row = UserDocument(user_id=user_id, filename=name, size_bytes=size, mtime=mtime)
                session.add(row)
                await session.flush()
                to_queue.append(row.id)
        await session.commit()
        for doc_id in removed:
            await remove_index(doc_id)
        for doc_id in to_queue:
            enqueue(doc_id)
        rows = (
            await session.scalars(
                select(UserDocument)
                .where(UserDocument.user_id == user_id)
                .order_by(UserDocument.created_at.desc(), UserDocument.id.desc())
            )
        ).all()
        # Antrean hilang saat backend restart -> pastikan dokumen tertunda tetap diproses.
        for r in rows:
            if r.status in ("antre", "proses") and r.id not in _queued:
                enqueue(r.id)
        return list(rows)


async def save_upload(user_id: int, name: str, tmp: Path) -> UserDocument:
    """Pindahkan berkas unggahan sementara (di folder yang sama) ke nama finalnya lalu
    masukkan ke antrean indeks."""
    if not folder_ok(user_id):
        tmp.unlink(missing_ok=True)
        raise ValueError("Folder Dokumen-AI tidak valid.")
    d = folder(user_id)
    target = unique_path(d, safe_filename(name))
    await asyncio.to_thread(tmp.replace, target)
    st = target.stat()
    storage_guard.adjust_usage(user_id, st.st_size)
    async with AsyncSessionLocal() as session:
        row = UserDocument(
            user_id=user_id, filename=target.name, size_bytes=st.st_size, mtime=st.st_mtime
        )
        session.add(row)
        try:
            await session.commit()
            await session.refresh(row)
        except IntegrityError:
            # sync_folder lain sudah lebih dulu mencatat berkas ini.
            await session.rollback()
            row = (
                await session.scalars(
                    select(UserDocument).where(
                        UserDocument.user_id == user_id, UserDocument.filename == target.name
                    )
                )
            ).one()
    enqueue(row.id)
    return row


async def get_doc(user_id: int, doc_id: int) -> UserDocument | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(UserDocument, doc_id)
        return row if row is not None and row.user_id == user_id else None


async def delete_doc(user_id: int, doc_id: int) -> bool:
    """Pindahkan berkas ke Tempat Sampah pengguna dan hapus dari indeks."""
    row = await get_doc(user_id, doc_id)
    if row is None:
        return False
    rel = f"{settings.DOCS_LIBRARY_FOLDER}/{row.filename}"
    try:
        await asyncio.to_thread(workspace_svc.delete, user_id, rel)
    except FileNotFoundError:
        pass
    storage_guard.mark_dirty(user_id)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(UserDocument).where(UserDocument.id == doc_id))
        await session.commit()
    await remove_index(doc_id)
    return True


async def reindex(user_id: int, doc_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        row = await session.get(UserDocument, doc_id)
        if row is None or row.user_id != user_id:
            return False
        row.status, row.error = "antre", None
        await session.commit()
    enqueue(doc_id)
    return True


# ------------------------------------------------------------------ pengindeksan
async def _set(doc_id: int, **fields) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.get(UserDocument, doc_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        await session.commit()


async def process(doc_id: int) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.get(UserDocument, doc_id)
        if row is None:
            return
        user_id, filename = row.user_id, row.filename
    path = safe_file(user_id, filename)
    if path is None:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(UserDocument).where(UserDocument.id == doc_id))
            await session.commit()
        await remove_index(doc_id)
        return

    await _set(doc_id, status="proses", error=None)
    try:
        data = await asyncio.to_thread(path.read_bytes)
        st = path.stat()
        res = await doc_extract.extract(
            filename,
            data,
            max_bytes=None,
            max_chars=settings.DOCS_LIBRARY_MAX_CHARS,
            timeout_scale=4.0,
        )
        chunks = help_rag.chunk_text(filename, res.text)
        if not chunks:
            raise doc_extract.ExtractError("Teks dokumen terlalu pendek untuk diindeks.")
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            await _ensure_collection(client)
            await _delete_points(client, doc_id)
            for i in range(0, len(chunks), _EMBED_BATCH):
                batch = chunks[i : i + _EMBED_BATCH]
                vecs = await help_rag.embed(
                    client, [f"{c.section}\n{c.text}".strip() for c in batch]
                )
                points = [
                    {
                        "id": _point_id(doc_id, i + j),
                        "vector": v,
                        "payload": {
                            "user_id": user_id,
                            "doc_id": doc_id,
                            "name": filename,
                            "section": c.section,
                            "text": c.text,
                            "idx": i + j,
                        },
                    }
                    for j, (c, v) in enumerate(zip(batch, vecs))
                ]
                resp = await client.put(f"{_coll()}/points?wait=true", json={"points": points})
                resp.raise_for_status()
        await _set(
            doc_id,
            status="siap",
            error=None,
            engine=res.engine,
            chars=res.chars,
            chunks=len(chunks),
            truncated=res.truncated,
            size_bytes=st.st_size,
            mtime=st.st_mtime,
            indexed_at=_utcnow(),
        )
    except doc_extract.ExtractError as exc:
        await _set(doc_id, status="gagal", error=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tanya Dokumen: gagal mengindeks dokumen #%s: %s", doc_id, exc)
        await _set(
            doc_id,
            status="gagal",
            error="Layanan pembaca/pengindeks dokumen sedang bermasalah. Coba proses ulang nanti.",
        )


def enqueue(doc_id: int) -> None:
    if _queue is None or doc_id in _queued:
        return
    _queued.add(doc_id)
    _queue.put_nowait(doc_id)


async def _worker() -> None:
    assert _queue is not None
    while True:
        doc_id = await _queue.get()
        try:
            await process(doc_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tanya Dokumen: worker error #%s: %s", doc_id, exc)
        finally:
            _queued.discard(doc_id)
            _queue.task_done()


async def start() -> None:
    global _queue
    if not settings.docs_library_enabled or _workers:
        return
    _queue = asyncio.Queue()
    for i in range(max(1, settings.DOCS_LIBRARY_WORKERS)):
        _workers.append(asyncio.create_task(_worker(), name=f"doc-library-{i}"))
    try:
        async with AsyncSessionLocal() as session:
            pending = (
                await session.scalars(
                    select(UserDocument.id).where(UserDocument.status.in_(("antre", "proses")))
                )
            ).all()
        for doc_id in pending:
            enqueue(doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tanya Dokumen: gagal memuat antrean: %s", exc)


async def stop() -> None:
    global _queue
    for t in _workers:
        t.cancel()
    for t in _workers:
        try:
            await t
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _workers.clear()
    _queued.clear()
    _queue = None


# ------------------------------------------------------------------ pencarian
async def retrieve(
    user_id: int, question: str, doc_ids: list[int] | None = None
) -> list[dict]:
    """Potongan paling relevan dari dokumen MILIK user. Gagal -> []."""
    q = (question or "").strip()
    if not q or not settings.docs_library_enabled:
        return []
    must: list[dict] = [{"key": "user_id", "match": {"value": int(user_id)}}]
    if doc_ids:
        must.append({"key": "doc_id", "match": {"any": [int(i) for i in doc_ids]}})

    async def _run() -> list[dict]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            vec = (await help_rag.embed(client, [q[:1500]]))[0]
            resp = await client.post(
                f"{_coll()}/points/search",
                json={
                    "vector": vec,
                    "filter": {"must": must},
                    "limit": max(1, settings.DOCS_LIBRARY_TOP_K),
                    "with_payload": True,
                    "score_threshold": settings.DOCS_LIBRARY_MIN_SCORE,
                },
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            hits = resp.json().get("result") or []
        out = []
        for h in hits:
            p = h.get("payload") or {}
            if p.get("user_id") != int(user_id) or not p.get("text"):
                continue  # pertahanan berlapis: jangan pernah bocor lintas pengguna
            out.append(
                {
                    "doc_id": int(p.get("doc_id") or 0),
                    "name": p.get("name", ""),
                    "section": p.get("section", ""),
                    "text": p["text"],
                    "idx": int(p.get("idx") or 0),
                    "score": round(float(h.get("score") or 0), 3),
                }
            )
        return out

    try:
        return await asyncio.wait_for(_run(), timeout=15.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tanya Dokumen: pencarian gagal: %s", exc)
        return []


def format_context(hits: list[dict]) -> tuple[str, list[dict]]:
    """(blok kutipan untuk model, daftar sumber untuk UI) dalam batas karakter."""
    budget = max(1000, settings.DOCS_LIBRARY_CONTEXT_CHARS)
    parts: list[str] = []
    sources: list[dict] = []
    for h in hits:
        n = len(sources) + 1
        where = h["name"] + (f" › {h['section']}" if h.get("section") else "")
        block = f"[D{n}] ({where})\n{h['text']}"
        if parts and sum(len(p) for p in parts) + len(block) > budget:
            break
        parts.append(block)
        sources.append(
            {"n": n, "doc_id": h["doc_id"], "name": h["name"], "section": h.get("section", "")}
        )
    return "\n\n".join(parts), sources

