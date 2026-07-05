"""Skema untuk asisten AI notebook (chat ala Copilot, provider OpenAI-compatible)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["user", "assistant"]


class AssistantMessage(BaseModel):
    role: Role
    content: str = Field(default="", max_length=20_000)
    # Gambar terlampir sbg data URL base64 ("data:image/...;base64,..."). Memicu model
    # VISION. Jumlah & ukuran divalidasi di service. Umumnya hanya pada pesan user.
    images: list[str] = Field(default_factory=list, max_length=8)


class AssistantChatRequest(BaseModel):
    """Riwayat percakapan + konteks notebook opsional (kode sel saat ini)."""

    messages: list[AssistantMessage] = Field(default_factory=list, max_length=40)
    # Konteks notebook (gabungan kode sel) agar jawaban relevan; dipangkas di service.
    notebook_context: str | None = Field(default=None, max_length=60_000)
    # Kode sel yang sedang difokuskan user (mis. untuk "perbaiki sel ini").
    cell_code: str | None = Field(default=None, max_length=40_000)


class AssistantStatus(BaseModel):
    enabled: bool
    configured: bool
    model: str
    provider: str
    # Model vision (input gambar); kosong = fitur gambar tak tersedia. UI memakai ini
    # untuk menampilkan/menyembunyikan tombol lampirkan gambar.
    vision_model: str = ""
