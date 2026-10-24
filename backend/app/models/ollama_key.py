"""Kunci API gerbang Ollama — izinkan teman/eksternal memakai Ollama server lewat
domain, TANPA akses ke server. Tiap kunci: pemilik, model yang boleh, batas laju,
kedaluwarsa. Hanya hash yang disimpan; kunci mentah ditampilkan sekali saat dibuat.

Tabel additive -> dibuat otomatis saat restart (create_all).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class OllamaApiKey(Base):
    __tablename__ = "ollama_api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    # Nama pemilik/keperluan kunci (untuk ditampilkan di daftar).
    name: Mapped[str] = mapped_column(String(120), default="")
    # 8 karakter awal kunci (prefix) untuk dikenali tanpa membuka kunci penuh.
    key_prefix: Mapped[str] = mapped_column(String(16), default="", index=True)
    # SHA-256 heksadesimal dari kunci penuh — kunci mentah TIDAK disimpan.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Daftar model yang boleh (dipisah baris baru). Kosong = SEMUA model diblokir
    # (admin wajib memilih minimal satu agar kunci berguna).
    allowed_models: Mapped[str] = mapped_column(Text, default="")

    max_concurrent: Mapped[int] = mapped_column(Integer, default=2)
    rate_per_min: Mapped[int] = mapped_column(Integer, default=30)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)

    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_email: Mapped[str] = mapped_column(String(255), default="")
    note: Mapped[str] = mapped_column(Text, default="")

    # Snapshot identitas PEMILIK kunci (dipilih dari daftar user web saat dibuat).
    # Disimpan sebagai salinan agar info tetap ada walau user berubah/dihapus.
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    owner_name: Mapped[str] = mapped_column(String(255), default="")
    owner_email: Mapped[str] = mapped_column(String(255), default="")
    owner_role: Mapped[str] = mapped_column(String(20), default="")
    owner_nim: Mapped[str] = mapped_column(String(64), default="")

    def models_list(self) -> list[str]:
        return [m.strip() for m in (self.allowed_models or "").splitlines() if m.strip()]
