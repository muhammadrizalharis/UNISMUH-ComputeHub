"""Skema untuk asisten AI notebook (chat ala Copilot, provider OpenAI-compatible)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["user", "assistant"]


class AssistantDocument(BaseModel):
    """Isi teks dokumen terlampir (hasil POST /assistant/extract), dikirim ulang oleh
    peramban bersama riwayat. Dipangkas lagi di service sesuai jendela konteks."""

    name: str = Field(default="dokumen", max_length=200)
    text: str = Field(default="", max_length=100_000)


class AssistantMessage(BaseModel):
    role: Role
    content: str = Field(default="", max_length=20_000)
    # Gambar terlampir sbg data URL base64 ("data:image/...;base64,..."). Memicu model
    # VISION. Jumlah & ukuran divalidasi di service. Umumnya hanya pada pesan user.
    images: list[str] = Field(default_factory=list, max_length=8)
    # Dokumen terlampir (PDF/DOCX/...) yang sudah diekstrak jadi teks.
    documents: list[AssistantDocument] = Field(default_factory=list, max_length=5)


class AssistantChatRequest(BaseModel):
    """Riwayat percakapan + konteks notebook opsional (kode sel saat ini)."""

    messages: list[AssistantMessage] = Field(default_factory=list, max_length=40)
    # Konteks notebook (gabungan kode sel) agar jawaban relevan; dipangkas di service.
    notebook_context: str | None = Field(default=None, max_length=60_000)
    # Kode sel yang sedang difokuskan user (mis. untuk "perbaiki sel ini").
    cell_code: str | None = Field(default=None, max_length=40_000)
    # Versi Python sesi notebook (3.10/3.11/...) -> asisten tahu library image mana
    # yang terpasang. None = versi default.
    python_version: str | None = Field(default=None, max_length=16)
    # Sakelar "Cari di web": cari dulu lewat SearXNG lalu jawab dengan sumber [n].
    web_search: bool = False


class AssistantStatus(BaseModel):
    enabled: bool
    configured: bool
    model: str
    provider: str
    # Model vision (input gambar); kosong = fitur gambar tak tersedia. UI memakai ini
    # untuk menampilkan/menyembunyikan tombol lampirkan gambar.
    vision_model: str = ""
    # Fitur pendukung (layanan local-ai). False -> tombolnya disembunyikan di UI.
    documents: bool = False
    doc_max_mb: int = 0
    web_search: bool = False
