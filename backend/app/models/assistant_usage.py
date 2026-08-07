"""Catatan pemakaian Asisten AI per AKUN ComputeHub.

Di tingkat OS, seluruh beban Ollama tercatat atas nama akun layanan `ollama`
sehingga tidak terlihat siapa pemakainya. `llm_attrib` sudah menjawab sisi USER
LINUX (lewat pemilik socket), tetapi permintaan yang datang dari web ComputeHub
selalu tampak sebagai proses backend — bukan mahasiswa/dosen yang meminta.

Tabel ini menutup celah itu: satu baris = satu permintaan asisten, atas nama
akun ComputeHub yang benar-benar memintanya.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AssistantUsage(Base):
    __tablename__ = "assistant_usage"
    # Kueri utama = rekap per user pada rentang tanggal.
    __table_args__ = (Index("ix_assistant_usage_user_ts", "user_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    model: Mapped[str] = mapped_column(String(128), default="")
    # Model vision jauh lebih berat (~30 GB VRAM) -> dibedakan untuk analisis beban.
    is_vision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sumber: Mapped[str] = mapped_column(String(16), default="chat")
    prompt_chars: Mapped[int] = mapped_column(Integer, default=0)
    reply_chars: Mapped[int] = mapped_column(Integer, default=0)
    durasi_detik: Mapped[float] = mapped_column(Float, default=0.0)
