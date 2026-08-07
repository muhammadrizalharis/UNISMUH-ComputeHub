"""Cuplikan berkala koneksi ke layanan LLM bersama (bahan riwayat harian).

`llm_attrib` hanya memotret keadaan SAAT ITU. Begitu momennya lewat, jejak siapa
yang memakai Ollama hilang. Modul ini menyimpan cuplikannya secara berkala supaya
riwayat harian bisa direkonstruksi kapan pun diminta — sejajar dengan
`os_user_samples` untuk pemakaian resource.

Satu baris = satu pihak pada satu waktu cuplik.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class LlmConnSample(Base):
    __tablename__ = "llm_conn_samples"
    # Kueri utama = rentang tanggal untuk satu/semua pihak.
    __table_args__ = (Index("ix_llm_conn_samples_nama_ts", "nama", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True, nullable=False
    )
    # User Linux (pemilik socket) atau asal koneksi masuk (host/container).
    nama: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # -1 untuk koneksi MASUK: asalnya bukan proses lokal sehingga tak punya pemilik.
    uid: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    sumber: Mapped[str] = mapped_column(String(8), default="klien", nullable=False)
    koneksi: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- Beban LAYANAN saat cuplikan diambil (hasil UKUR, bukan perkiraan) ---
    # Ollama satu proses: VRAM/CPU/RAM-nya milik bersama, tak bisa dipecah per klien
    # oleh sistem operasi. Nilai ini disimpan apa adanya sebagai konteks.
    layanan_vram_mb: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    layanan_cpu_percent: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    layanan_ram_mb: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Porsi koneksi pihak ini terhadap seluruh koneksi (0..1) -> dasar ESTIMASI bagian.
    pangsa: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
