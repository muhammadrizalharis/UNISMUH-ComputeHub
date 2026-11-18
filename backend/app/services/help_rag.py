"""RAG bot Panduan: dokumen panduan resmi -> potongan -> embedding bge-m3 -> Qdrant.

Basis pengetahuan ringkas (helpbot._KNOWLEDGE) tetap disuntik penuh ke prompt.
Modul ini MENAMBAHKAN kutipan paling relevan dari dokumen panduan yang lebih
panjang (PDF Panduan Mahasiswa + berkas di docs/panduan/), sehingga bot tetap
akurat walau dokumentasi terus bertambah.

Sinkronisasi indeks bersifat content-addressed: ID titik = hash isi potongan.
Hanya potongan baru yang di-embed; potongan yang sudah tidak ada dihapus.
Semua kegagalan (Qdrant/embedding mati) membuat bot kembali ke perilaku lama.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services import doc_extract

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[3]
GUIDE_PDF = ROOT / "frontend" / "public" / "panduan-mahasiswa.pdf"
GUIDE_MD = ROOT / "docs" / "PANDUAN-PENGGUNA.md"
EXTRA_DIR = ROOT / "docs" / "panduan"

CHUNK_CHARS = 900
_MIN_DOC_CHARS = 200          # berkas lebih pendek (mis. templat kosong) dilewati
_EMBED_BATCH = 16
_NS = uuid.UUID("6f1c2a52-6a52-4c1e-9a3e-2b8f0c6d7e11")
_HEADING = re.compile(r"^(#{1,6}\s+.+|==\s*.+\s*==|\d{1,2}\.?\s+[A-Z].{2,70})$")

_state: dict = {"last_sync": None, "chunks": 0, "error": None}
_task: asyncio.Task | None = None


@dataclass
class Chunk:
    source: str
    section: str
    text: str

    @property
    def point_id(self) -> str:
        digest = hashlib.sha256(f"{self.source}\n{self.text}".encode()).hexdigest()
        return str(uuid.uuid5(_NS, digest))


def status() -> dict:
    return {"enabled": settings.help_rag_enabled, **_state}


# ------------------------------------------------------------------ korpus
def source_files() -> list[Path]:
    files = [p for p in (GUIDE_PDF, GUIDE_MD) if p.is_file()]
    if EXTRA_DIR.is_dir():
        files += sorted(
            p for p in EXTRA_DIR.iterdir()
            if p.is_file() and not p.name.startswith(".") and doc_extract.is_allowed(p.name)
            and p.name.lower() != "readme.md"
        )
    return files


async def read_source(path: Path) -> str:
    data = path.read_bytes()
    if doc_extract.extension_of(path.name) in (".md", ".txt"):
        return doc_extract.clean_text(data.decode("utf-8", "replace"))
    return (await doc_extract.extract(path.name, data)).text


def _paragraphs(text: str) -> list[tuple[str, str]]:
    """Pecah teks jadi (judul_bagian, paragraf). Baris judul selalu memulai paragraf baru."""
    out: list[tuple[str, str]] = []
    section = ""
    cur: list[str] = []

    def end() -> None:
        nonlocal cur
        body = "\n".join(cur).strip()
        if body:
            out.append((section, body))
        cur = []

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            end()
            continue
        if len(line) <= 80 and _HEADING.match(line):
            end()
            section = line.strip("#= ").strip()
        cur.append(line)
    end()
    return out


def _split_long(p: str, size: int) -> list[str]:
    if len(p) <= size:
        return [p]
    pieces: list[str] = []
    cur = ""
    for s in re.split(r"(?<=[.!?])\s+|\n", p):
        while len(s) > size:
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(s[:size])
            s = s[size:]
        if cur and len(cur) + len(s) + 1 > size:
            pieces.append(cur)
            cur = ""
        cur = f"{cur} {s}".strip() if cur else s
    if cur:
        pieces.append(cur)
    return pieces


def chunk_text(source: str, text: str, size: int = CHUNK_CHARS) -> list[Chunk]:
    """Potong teks menjadi ±size karakter; potongan tidak melintasi judul bagian."""
    out: list[Chunk] = []
    buf: list[str] = []
    buf_section = ""

    def flush() -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if len(body) >= 40:
            out.append(Chunk(source, buf_section, body))
        buf = []

    for section, para in _paragraphs(text):
        if buf and section != buf_section:
            flush()
        for piece in _split_long(para, size):
            if buf and sum(len(b) + 1 for b in buf) + len(piece) > size:
                flush()
            if not buf:
                buf_section = section
            buf.append(piece)
    flush()
    return out


async def build_corpus() -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in source_files():
        try:
            text = await read_source(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG panduan: gagal membaca %s: %s", path.name, exc)
            continue
        if len(text) < _MIN_DOC_CHARS:
            continue
        chunks += chunk_text(path.name, text)
    return chunks


# ------------------------------------------------------------ embedding & qdrant
def _qdrant() -> str:
    return settings.HELP_RAG_QDRANT_URL.strip().rstrip("/")


def _coll() -> str:
    return f"{_qdrant()}/collections/{settings.HELP_RAG_COLLECTION}"


async def embed(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    url = settings.HELP_RAG_EMBED_URL.strip().rstrip("/") + "/api/embed"
    resp = await client.post(url, json={"model": settings.HELP_RAG_EMBED_MODEL, "input": texts})
    resp.raise_for_status()
    vecs = resp.json().get("embeddings") or []
    if len(vecs) != len(texts):
        raise ValueError("jumlah embedding tidak cocok")
    return vecs


async def _ensure_collection(client: httpx.AsyncClient, dim: int) -> None:
    resp = await client.get(_coll())
    if resp.status_code == 200:
        return
    resp = await client.put(_coll(), json={"vectors": {"size": dim, "distance": "Cosine"}})
    resp.raise_for_status()


async def _existing_ids(client: httpx.AsyncClient) -> set[str]:
    ids: set[str] = set()
    offset = None
    while True:
        body: dict = {"limit": 512, "with_payload": False, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        resp = await client.post(f"{_coll()}/points/scroll", json=body)
        resp.raise_for_status()
        res = resp.json().get("result") or {}
        ids |= {str(p["id"]) for p in res.get("points") or []}
        offset = res.get("next_page_offset")
        if offset is None:
            return ids


async def sync() -> dict:
    """Samakan isi koleksi Qdrant dengan dokumen panduan. Kembalikan ringkasan."""
    chunks = await build_corpus()
    wanted = {c.point_id: c for c in chunks}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
        probe = await embed(client, ["dimensi"])
        await _ensure_collection(client, len(probe[0]))
        have = await _existing_ids(client)
        missing = [wanted[i] for i in wanted if i not in have]
        for i in range(0, len(missing), _EMBED_BATCH):
            batch = missing[i : i + _EMBED_BATCH]
            vecs = await embed(client, [f"{c.section}\n{c.text}".strip() for c in batch])
            points = [
                {
                    "id": c.point_id,
                    "vector": v,
                    "payload": {"source": c.source, "section": c.section, "text": c.text},
                }
                for c, v in zip(batch, vecs)
            ]
            resp = await client.put(f"{_coll()}/points?wait=true", json={"points": points})
            resp.raise_for_status()
        stale = [i for i in have if i not in wanted]
        if stale:
            resp = await client.post(
                f"{_coll()}/points/delete?wait=true", json={"points": stale}
            )
            resp.raise_for_status()
    _state.update(last_sync=time.time(), chunks=len(wanted), error=None)
    return {"chunks": len(wanted), "added": len(missing), "removed": len(stale)}


async def retrieve(question: str) -> list[dict]:
    """Kutipan panduan paling relevan. Gagal / nonaktif -> [] (bot tetap jalan)."""
    q = (question or "").strip()
    if not q or not settings.help_rag_enabled:
        return []

    async def _run() -> list[dict]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            vec = (await embed(client, [q[:1000]]))[0]
            resp = await client.post(
                f"{_coll()}/points/search",
                json={
                    "vector": vec,
                    "limit": max(1, settings.HELP_RAG_TOP_K),
                    "with_payload": True,
                    "score_threshold": settings.HELP_RAG_MIN_SCORE,
                },
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            hits = resp.json().get("result") or []
        return [
            {
                "source": (h.get("payload") or {}).get("source", ""),
                "section": (h.get("payload") or {}).get("section", ""),
                "text": (h.get("payload") or {}).get("text", ""),
                "score": round(float(h.get("score") or 0), 3),
            }
            for h in hits
            if (h.get("payload") or {}).get("text")
        ]

    try:
        return await asyncio.wait_for(_run(), timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG panduan: pencarian gagal: %s", exc)
        return []


def format_excerpts(hits: list[dict]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        where = h["source"] + (f" › {h['section']}" if h.get("section") else "")
        parts.append(f"[{i}] ({where})\n{h['text']}")
    return "\n\n".join(parts)


# ------------------------------------------------------------- loop latar
async def _loop() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            info = await sync()
            if info["added"] or info["removed"]:
                logger.info("RAG panduan disinkronkan: %s", info)
        except Exception as exc:  # noqa: BLE001
            _state["error"] = str(exc)[:300]
            logger.warning("RAG panduan: sinkronisasi gagal: %s", exc)
        await asyncio.sleep(max(60, settings.HELP_RAG_REINDEX_SECONDS))


async def start() -> None:
    global _task
    if settings.help_rag_enabled and _task is None:
        _task = asyncio.create_task(_loop(), name="help-rag-sync")


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _task = None
