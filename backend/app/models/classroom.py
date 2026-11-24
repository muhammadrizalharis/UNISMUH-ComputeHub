"""Model RUANG KELAS: dosen/admin membuat kelas, mahasiswa bergabung via kode kelas.

Satu kelas boleh punya beberapa pengajar (dosen/asisten). Keanggotaan ikut terhapus
(ON DELETE CASCADE) bila kelas atau akun pengguna dihapus. Tabel additive -> dibuat
otomatis oleh create_all saat backend menyala.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
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
