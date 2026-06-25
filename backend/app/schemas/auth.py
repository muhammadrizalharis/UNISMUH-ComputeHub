"""Schemas autentikasi."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # detik


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class TokenPayload(BaseModel):
    sub: str | None = None
    role: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
