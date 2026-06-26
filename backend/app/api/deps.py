"""Dependencies FastAPI: autentikasi & otorisasi role."""

from __future__ import annotations

import time
from collections.abc import Iterable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Kredensial tidak valid atau token kedaluwarsa.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise _credentials_exc
    except jwt.PyJWTError as exc:
        raise _credentials_exc from exc

    user = await session.get(User, int(user_id))
    if user is None:
        raise _credentials_exc
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Akun dinonaktifkan."
        )
    return current_user


# Cache ringan utk auth frekuensi-tinggi (mis. polling monitoring): user_id -> kadaluwarsa.
# Menghindari lookup Supabase (Tokyo, ~800ms) tiap request. TTL pendek -> perubahan
# status aktif tetap berlaku cepat (maks AUTH_CACHE_TTL_SECONDS).
_auth_active_cache: dict[int, float] = {}


async def require_authenticated(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> int:
    """Auth RINGAN utk endpoint baca frekuensi-tinggi (mis. monitoring): verifikasi
    JWT + status aktif (DI-CACHE singkat) TANPA memuat objek User penuh tiap request.
    Kembalikan user_id. JANGAN dipakai utk endpoint yang butuh objek User / mutasi."""
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        user_id = int(sub) if sub is not None else None
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise _credentials_exc from exc
    if user_id is None:
        raise _credentials_exc
    now = time.monotonic()
    exp = _auth_active_cache.get(user_id)
    if exp is not None and exp > now:
        return user_id
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        _auth_active_cache.pop(user_id, None)
        raise _credentials_exc
    _auth_active_cache[user_id] = now + settings.AUTH_CACHE_TTL_SECONDS
    return user_id


def require_roles(*roles: UserRole):
    """Dependency factory: batasi akses ke role tertentu."""
    allowed: Iterable[UserRole] = roles

    async def _checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak: role tidak mencukupi.",
            )
        return current_user

    return _checker


# Shortcut umum.
require_admin = require_roles(UserRole.admin)
