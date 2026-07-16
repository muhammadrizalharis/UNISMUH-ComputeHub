"""Model User & role."""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class UserRole(str, enum.Enum):
    admin = "admin"
    dosen = "dosen"
    mahasiswa = "mahasiswa"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Username login, auto-generate "CH" + bagian lokal email saat admin buat user.
    # Nullable: akun lama (sebelum fitur ini) belum punya -> login tetap via email.
    username: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True, default=None
    )
    hashed_password: Mapped[str] = mapped_column(String(255))
    # Klaim `sub` dari SSO Unismuh (OIDC) = kunci stabil akun SSO. Nullable: akun lokal
    # (username/password) tak punya. Uniqueness ditegakkan di kode (sub global unik dari
    # Keycloak) — dibuat index (bukan UNIQUE constraint) agar aman utk ADD COLUMN migrasi.
    sso_sub: Mapped[str | None] = mapped_column(
        String(255), index=True, nullable=True, default=None
    )
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, length=20),
        default=UserRole.mahasiswa,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # Foto profil opsional sebagai data URL base64 terkompres (256px di klien).
    # Disimpan di DB agar SINKRON lintas perangkat & TERLIHAT admin
    # (kecil; bukan berkas di disk server).
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    # Sesi tunggal (1 perangkat per akun, BERLAKU SEMUA PERAN) demi keamanan &
    # privasi: menyimpan ID sesi (sid) yang dibawa JWT login terakhir. Setiap login
    # baru menimpa nilai ini sehingga token di perangkat lama otomatis tidak sah lagi.
    session_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )

    jobs: Mapped[list["Job"]] = relationship(  # noqa: F821
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def is_superadmin(self) -> bool:
        """True bila akun ini = administrator utama (FIRST_ADMIN_EMAIL).

        Administrator utama DILINDUNGI: tidak bisa dihapus, diturunkan rolenya,
        atau dinonaktifkan oleh admin lain. Hanya ia yang boleh mengelola admin lain.
        """
        from app.core.config import settings  # lazy: hindari import siklik

        target = (settings.FIRST_ADMIN_EMAIL or "").strip().lower()
        return bool(target) and (self.email or "").strip().lower() == target

    @property
    def is_sso(self) -> bool:
        """True bila akun login via SSO Unismuh (punya klaim `sub`).

        User SSO TIDAK punya password lokal (dikelola SSO/Google/SIMAK) -> fitur
        "Ganti Password" di aplikasi disembunyikan (FE) & endpoint-nya ditolak.
        """
        return bool(self.sso_sub)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} email={self.email!r} role={self.role.value}>"
