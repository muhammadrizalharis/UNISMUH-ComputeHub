"""Router autentikasi: login (JWT) & me.

Registrasi mandiri DIMATIKAN: akun hanya dibuat oleh admin lewat menu Pengguna
(`POST /api/v1/users`). Ini disengaja untuk server bersama kampus.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_user_by_email
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import SlidingWindowRateLimiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, Token
from app.schemas.user import UserOut

router = APIRouter()

# Anti brute-force: hitung percobaan login GAGAL per alamat IP.
_login_limiter = SlidingWindowRateLimiter(
    max_attempts=settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    block_seconds=settings.LOGIN_RATE_LIMIT_BLOCK_SECONDS,
)


def _client_key(request: Request) -> str:
    """Kunci rate-limit = alamat IP klien (apa adanya dari koneksi TCP)."""
    client = request.client
    return client.host if client else "unknown"


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
) -> Token:
    """Login OAuth2 password flow. Isi `username` dengan email."""
    key = _client_key(request)
    gate = _login_limiter.check(key)
    if not gate.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Terlalu banyak percobaan login. "
                f"Coba lagi dalam {gate.retry_after} detik."
            ),
            headers={"Retry-After": str(gate.retry_after)},
        )

    user = await get_user_by_email(session, form_data.username)
    if user is None or not verify_password(form_data.password, user.hashed_password):
        fail = _login_limiter.record_failure(key)
        if not fail.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Terlalu banyak percobaan login gagal. "
                    f"Coba lagi dalam {fail.retry_after} detik."
                ),
                headers={"Retry-After": str(fail.retry_after)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email atau password salah.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Akun dinonaktifkan."
        )

    _login_limiter.reset(key)
    token = create_access_token(subject=str(user.id), role=user.role.value)
    return Token(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserOut)
async def read_me(current_user: User = Depends(get_current_active_user)) -> User:
    return current_user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Ganti password SENDIRI (wajib verifikasi password lama)."""
    user = await session.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan.")
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password lama salah.")
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password baru harus berbeda dari password lama.",
        )
    user.hashed_password = hash_password(payload.new_password)
    session.add(user)
    await session.commit()

