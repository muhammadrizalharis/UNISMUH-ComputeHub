"""Ekstraksi teks dokumen untuk lampiran Asisten AI (layanan stack local-ai).

Alur: Apache Tika dulu (cepat, tanpa GPU, mendukung hampir semua format kantor).
Bila hasilnya nyaris kosong — umumnya PDF hasil pindaian — dan Docling tersedia,
dokumen dikirim ke Docling (OCR + tabel -> Markdown). Berkas tidak disimpan:
hanya teks hasil ekstraksi yang dikembalikan ke peramban.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import PurePath

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Ekstensi yang diterima -> MIME untuk Tika. Gambar sengaja tidak di sini:
# gambar sudah ditangani model vision lewat lampiran gambar.
ALLOWED: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".rtf": "application/rtf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".html": "text/html",
    ".htm": "text/html",
    ".tex": "application/x-tex",
}

# Teks sependek ini dari PDF dianggap gagal (PDF pindaian) -> coba Docling.
_MIN_USEFUL_CHARS = 200
# Batas teks yang dikembalikan ke peramban (prompt dipangkas lagi di assistant).
MAX_RETURN_CHARS = 100_000

_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>&|<])")
_BLANKS = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")


class ExtractError(Exception):
    """Pesan ramah pengguna (Bahasa Indonesia) bila dokumen tak bisa dibaca."""


@dataclass
class Extracted:
    name: str
    text: str
    engine: str          # "tika" | "docling" | "teks"
    chars: int           # panjang teks asli (sebelum dipotong)
    truncated: bool


def extension_of(name: str) -> str:
    return PurePath(name or "").suffix.lower()


def is_allowed(name: str) -> bool:
    return extension_of(name) in ALLOWED


def clean_text(raw: str) -> str:
    """Rapikan keluaran ekstraktor: buang escape Markdown Tika & baris kosong berlebih."""
    s = (raw or "").replace("\r\n", "\n").replace("\x00", "")
    s = html.unescape(_ESCAPED.sub(r"\1", s))
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = _BLANKS.sub("\n\n", s)
    return s.strip()


def _decode_plain(data: bytes) -> str:
    for enc in ("utf-8", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


async def _tika(data: bytes, mime: str, timeout: float = 90.0) -> str:
    url = settings.ASSISTANT_TIKA_URL.strip().rstrip("/") + "/tika"
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
        resp = await client.put(
            url, content=data, headers={"Content-Type": mime, "Accept": "text/plain"}
        )
        resp.raise_for_status()
        return resp.text


async def _docling(data: bytes, name: str, timeout: float = 180.0) -> str:
    url = settings.ASSISTANT_DOCLING_URL.strip().rstrip("/") + "/v1/convert/file"
    form = {
        "to_formats": "md",
        "do_ocr": "true",
        "image_export_mode": "placeholder",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
        resp = await client.post(url, data=form, files={"files": (name, data)})
        resp.raise_for_status()
        obj = resp.json()
    if obj.get("status") not in ("success", "partial_success"):
        raise ExtractError("Docling gagal membaca dokumen ini.")
    return ((obj.get("document") or {}).get("md_content") or "")


async def extract(
    name: str,
    data: bytes,
    *,
    max_bytes: int | None = -1,
    max_chars: int = MAX_RETURN_CHARS,
    timeout_scale: float = 1.0,
) -> Extracted:
    """Ubah berkas jadi teks. Lempar ExtractError dengan pesan yang bisa ditampilkan.

    max_bytes: -1 = ASSISTANT_DOC_MAX_BYTES (lampiran chat), None = tanpa batas
    (pustaka dokumen; dibatasi kuota disk). timeout_scale memperpanjang waktu tunggu
    Tika/Docling untuk dokumen besar yang diproses di latar belakang.
    """
    if max_bytes == -1:
        max_bytes = settings.ASSISTANT_DOC_MAX_BYTES
    ext = extension_of(name)
    if ext not in ALLOWED:
        raise ExtractError(
            "Jenis berkas belum didukung. Gunakan PDF, Word, PowerPoint, Excel, "
            "OpenDocument, atau teks (txt/md/csv/json)."
        )
    if not data:
        raise ExtractError("Berkas kosong.")
    if max_bytes is not None and len(data) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise ExtractError(f"Ukuran berkas melebihi batas {mb} MB.")

    text = ""
    engine = ""
    if ext in (".txt", ".md", ".csv", ".tsv", ".json", ".tex"):
        text, engine = _decode_plain(data), "teks"
    else:
        if settings.ASSISTANT_TIKA_URL.strip():
            try:
                text, engine = (
                    clean_text(await _tika(data, ALLOWED[ext], timeout=90.0 * timeout_scale)),
                    "tika",
                )
            except httpx.HTTPError as exc:
                logger.warning("Tika gagal untuk %s: %s", name, exc)
        sparse = len(text) < _MIN_USEFUL_CHARS
        docling_ok = ext in (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm")
        if sparse and docling_ok and settings.ASSISTANT_DOCLING_URL.strip():
            try:
                alt = clean_text(
                    await _docling(
                        data,
                        PurePath(name).name or "dokumen" + ext,
                        timeout=180.0 * timeout_scale,
                    )
                )
                if len(alt) > len(text):
                    text, engine = alt, "docling"
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Docling gagal untuk %s: %s", name, exc)

    text = clean_text(text)
    if not text:
        raise ExtractError(
            "Tidak ada teks yang bisa dibaca dari dokumen ini (mungkin hasil pindaian "
            "berkualitas rendah atau terproteksi)."
        )
    total = len(text)
    return Extracted(
        name=PurePath(name).name[:200] or "dokumen",
        text=text[:max_chars],
        engine=engine,
        chars=total,
        truncated=total > max_chars,
    )
