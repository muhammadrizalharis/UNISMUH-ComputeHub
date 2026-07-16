"""Schemas User."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr


class UserCreate(UserBase):
    # Password OPSIONAL: bila kosong, sistem meng-generate password acak kuat
    # (ditampilkan SEKALI ke admin + dikirim ke email user). Admin cukup isi
    # nama + email + role.
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole = UserRole.mahasiswa


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None


class AvatarUpdate(BaseModel):
    # Data URL gambar (data:image/...;base64,...) atau null untuk menghapus foto.
    avatar: str | None = None


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str | None = None
    role: UserRole
    is_active: bool
    is_superadmin: bool = False
    is_sso: bool = False
    created_at: dt.datetime
    avatar: str | None = None


class UserCreateResult(UserOut):
    # Password plaintext yang DIGENERATE — hanya dikembalikan SEKALI saat pembuatan
    # akun (tak pernah disimpan/ditampilkan lagi). None bila admin memberi password.
    generated_password: str | None = None
    email_sent: bool = False
