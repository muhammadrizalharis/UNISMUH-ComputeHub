"""Pencarian web untuk Asisten AI: SearXNG (daftar hasil) + Crawl4AI (isi halaman).

Hanya dipakai bila pengguna menyalakan sakelar "Cari di web". Kueri dibentuk dari
pesan terakhir pengguna (blok kode dibuang agar kode pribadi tidak ikut terkirim
ke mesin pencari). Hasil disisipkan ke prompt sebagai sumber bernomor [n].
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_CODE_FENCE = re.compile(r"```.*?(```|$)", re.S)
_INLINE_CODE = re.compile(r"`([^`]{0,80})`")
_SPACES = re.compile(r"\s+")
_MAX_QUERY_CHARS = 200
_WORD = re.compile(r"[\w.+#-]{2,}", re.U)
# Kata tanya/pengisi Bahasa Indonesia yang hanya mengaburkan kueri mesin pencari.
_STOPWORDS = {
    "apa", "apakah", "kenapa", "mengapa", "bagaimana", "gimana", "cara", "caranya",
    "tolong", "dong", "ya", "yang", "di", "ke", "dari", "dan", "atau", "untuk", "pada",
    "saya", "aku", "kamu", "ini", "itu", "bisa", "muncul", "ada", "adalah", "dengan",
    "mohon", "bantu", "jelaskan", "sih", "kok", "nya", "agar", "supaya", "kalau", "jika",
}
# Kata umum bahasa Inggris: hanya diabaikan saat menilai relevansi, TIDAK dibuang dari
# kueri (pesan error seperti "CUDA out of memory" harus utuh).
_EN_COMMON = {"the", "a", "an", "is", "of", "to", "in", "on", "and", "or", "how", "why", "what", "for"}
_PAGE_CHARS = 3_000
_SNIPPET_CHARS = 400


@dataclass
class Source:
    n: int
    title: str
    url: str
    snippet: str = ""
    content: str = ""   # isi halaman (Crawl4AI) bila berhasil dibaca

    def public(self) -> dict:
        return {"n": self.n, "title": self.title, "url": self.url}


@dataclass
class WebContext:
    query: str
    sources: list[Source] = field(default_factory=list)
    text: str = ""      # blok teks siap sisip ke prompt ("" = tak ada hasil)


def build_query(message: str) -> str:
    """Kueri pencarian dari pesan pengguna: tanpa blok kode, satu baris, maks 200 char."""
    s = _CODE_FENCE.sub(" ", message or "")
    s = _INLINE_CODE.sub(r"\1", s)
    s = _SPACES.sub(" ", s).strip()
    kept = [w for w in s.split(" ") if w.lower().strip("?,.!:;") not in _STOPWORDS]
    if len(kept) >= 2:
        s = " ".join(kept)
    if len(s) > _MAX_QUERY_CHARS:
        cut = s[:_MAX_QUERY_CHARS]
        s = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return s


def _safe_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def _terms(text: str) -> set[str]:
    return {
        w.lower().strip(".-") for w in _WORD.findall(text or "")
        if len(w) >= 3 and w.lower() not in _STOPWORDS and w.lower() not in _EN_COMMON
    }


def _relevance(query_terms: set[str], title: str, snippet: str) -> int:
    """Jumlah kata kueri yang muncul di judul/cuplikan (0 = hampir pasti tak relevan)."""
    hay = (title + " " + snippet).lower()
    return sum(1 for t in query_terms if t in hay)


async def search(query: str, limit: int) -> list[Source]:
    base = settings.ASSISTANT_SEARXNG_URL.strip().rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        resp = await client.get(
            f"{base}/search", params={"q": query, "format": "json", "safesearch": 1}
        )
        resp.raise_for_status()
        data = resp.json()
    terms = _terms(query)
    need = 1 if len(terms) <= 3 else 2
    out: list[Source] = []
    seen: set[str] = set()
    for r in data.get("results") or []:
        url = (r.get("url") or "").strip()
        if not _safe_url(url) or url in seen:
            continue
        seen.add(url)
        title = _SPACES.sub(" ", (r.get("title") or url)).strip()[:200]
        snippet = _SPACES.sub(" ", (r.get("content") or "")).strip()[:_SNIPPET_CHARS]
        if terms and _relevance(terms, title, snippet) < need:
            continue
        out.append(Source(n=len(out) + 1, title=title, url=url, snippet=snippet))
        if len(out) >= limit:
            break
    return out


async def fetch_page(url: str) -> str:
    """Isi halaman sebagai Markdown via Crawl4AI ("" bila gagal / tak dikonfigurasi)."""
    base = settings.ASSISTANT_CRAWL4AI_URL.strip().rstrip("/")
    if not base:
        return ""
    headers = {"Content-Type": "application/json"}
    token = settings.ASSISTANT_CRAWL4AI_TOKEN.strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            resp = await client.post(f"{base}/md", json={"url": url}, headers=headers)
            resp.raise_for_status()
            obj = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("Crawl4AI gagal untuk %s: %s", url, exc)
        return ""
    if obj.get("success") is False:
        return ""
    return (obj.get("markdown") or "").strip()


_LINK_ONLY = re.compile(r"^(?:[-*+]\s*)?(?:\[[^\]]*\]\([^)]*\)[\s|·•,]*)+$")


def _compact(md: str, limit: int) -> str:
    """Ringkas Markdown halaman: buang gambar & baris navigasi (hanya tautan), potong panjang."""
    lines = []
    for line in md.splitlines():
        t = line.strip()
        if len(t) < 3 or t.startswith("![") or _LINK_ONLY.match(t):
            continue
        lines.append(t)
    text = "\n".join(lines)
    return text[:limit]


def format_context(sources: list[Source], budget: int) -> str:
    """Susun blok sumber bernomor dalam batas `budget` karakter."""
    parts: list[str] = []
    used = 0
    for s in sources:
        body = s.content or s.snippet
        head = f"[{s.n}] {s.title}\nURL: {s.url}\n"
        room = budget - used - len(head) - 2
        if room <= 80:
            break
        chunk = head + body[:room]
        parts.append(chunk)
        used += len(chunk) + 2
    return "\n\n".join(parts)


async def gather(message: str) -> WebContext:
    """Cari di web untuk satu pertanyaan. Tidak pernah melempar: gagal -> konteks kosong."""
    query = build_query(message)
    ctx = WebContext(query=query)
    if not query or not settings.assistant_web_enabled:
        return ctx
    try:
        ctx.sources = await search(query, max(1, settings.ASSISTANT_WEB_RESULTS))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("SearXNG gagal: %s", exc)
        return ctx
    top = ctx.sources[: max(0, settings.ASSISTANT_WEB_FETCH_PAGES)]
    if top and settings.ASSISTANT_CRAWL4AI_URL.strip():
        pages = await asyncio.gather(*(fetch_page(s.url) for s in top))
        for s, md in zip(top, pages):
            if md:
                s.content = _compact(md, _PAGE_CHARS)
    ctx.text = format_context(ctx.sources, settings.ASSISTANT_WEB_MAX_CHARS)
    return ctx
