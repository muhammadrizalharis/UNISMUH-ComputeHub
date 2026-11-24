"""Model RUANG KELAS: dosen/admin membuat kelas, mahasiswa bergabung via kode kelas.

Satu kelas boleh punya beberapa pengajar (dosen/asisten). Keanggotaan ikut terhapus
(ON DELETE CASCADE) bila kelas atau akun pengguna dihapus. Tabel additive -> dibuat
otomatis oleh create_all saat backend menyala.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ROLE_TEACHER = "pengajar"
ROLE_STUDENT = "mahasiswa"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    join_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ClassMember(Base):
    __tablename__ = "class_members"
    __table_args__ = (UniqueConstraint("classroom_id", "user_id", name="uq_class_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # pengajar | mahasiswa
    role: Mapped[str] = mapped_column(String(16), default=ROLE_STUDENT, nullable=False)
    joined_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    added_by: Mapped[int | None] = mapped_column(nullable=True, default=None)


class ClassMaterial(Base):
    """Materi kelas (A2): SALINAN BEKU file/folder dari workspace pengajar.

    Isinya disimpan di luar workspace siapa pun (lihat services/class_materials), jadi
    suntingan pengajar setelah dibagikan tidak mengubah materi yang diambil mahasiswa.
    """

    __tablename__ = "class_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # file | dir
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ClassMaterialCopy(Base):
    """Catatan mahasiswa yang sudah mengambil salinan materi (bahan ringkasan progres)."""

    __tablename__ = "class_material_copies"
    __table_args__ = (UniqueConstraint("material_id", "user_id", name="uq_material_copy"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("class_materials.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dest_path: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    copied_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
