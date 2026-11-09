"""Schemas autentikasi."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # detik (umur access token)
    refresh_token: str | None = None
    refresh_expires_in: int | None = None  # detik (umur refresh token)


class RefreshRequest(BaseModel):
    # Opsional: bila kosong, refresh token diambil dari cookie HttpOnly (lihat OBS-4).
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class TokenPayload(BaseModel):
    sub: str | None = None
    role: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ---- 2FA / TOTP (opt-in) ----
class MfaStatus(BaseModel):
    enabled: bool
    enrolled_at: str | None = None
    recovery_remaining: int = 0
    # True bila akun ini bisa memakai login password (bukan murni SSO).
    supported: bool = True


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str  # data URI image/svg+xml untuk dipindai


class MfaEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class MfaEnableOut(BaseModel):
    enabled: bool
    recovery_codes: list[str]


class MfaDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(default="", max_length=32)


class MfaRecoveryRegenRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=10)
