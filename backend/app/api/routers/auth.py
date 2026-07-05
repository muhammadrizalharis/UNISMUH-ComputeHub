"""Router autentikasi: login (JWT) & me.

Registrasi mandiri DIMATIKAN: akun hanya dibuat oleh admin lewat menu Pengguna
(`POST /api/v1/users`). Ini disengaja untuk server bersama kampus.
"""

from __future__ import annotations

import secrets
import time

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_active_user,
    get_user_by_login,
    invalidate_auth_cache,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import SlidingWindowRateLimiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.models.user import User, UserRole
from app.schemas.auth import ChangePasswordRequest, RefreshRequest, Token
from app.schemas.user import AvatarUpdate, UserOut

router = APIRouter()

# Anti brute-force: hitung percobaan login GAGAL per alamat IP.
_login_limiter = SlidingWindowRateLimiter(
    max_attempts=settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    block_seconds=settings.LOGIN_RATE_LIMIT_BLOCK_SECONDS,
)


def _client_key(request: Request) -> str:
    """Kunci rate-limit = IP ASLI klien.

    Di balik proxy/tunnel (cloudflared) IP koneksi TCP selalu 127.0.0.1 untuk SEMUA
    user -> rate-limit jadi global (1 penyerang bisa mengunci login semua orang). Maka
    bila TRUST_PROXY_HEADERS, ambil IP asli dari CF-Connecting-IP / X-Forwarded-For.
    """
    if settings.TRUST_PROXY_HEADERS:
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _refresh_token_minutes(role: UserRole) -> int:
    """Masa berlaku refresh token (menit) per peran: admin jauh lebih lama."""
    if role == UserRole.admin:
        return settings.REFRESH_TOKEN_EXPIRE_MINUTES_ADMIN
    return settings.REFRESH_TOKEN_EXPIRE_MINUTES


def _issue_tokens(user: User, sid: str) -> Token:
    """Terbitkan pasangan access (umur pendek) + refresh (per-peran) token."""
    refresh_minutes = _refresh_token_minutes(user.role)
    access = create_access_token(
        subject=str(user.id), role=user.role.value, session_id=sid
    )
    refresh = create_refresh_token(
        subject=str(user.id),
        role=user.role.value,
        session_id=sid,
        expires_minutes=refresh_minutes,
    )
    return Token(
        access_token=access,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=refresh,
        refresh_expires_in=refresh_minutes * 60,
    )


def _set_refresh_cookie(response: Response, token: str | None, max_age_seconds: int) -> None:
    """Pasang refresh token sbg cookie HttpOnly (OBS-4) — tak terbaca JS. No-op bila mati."""
    if not settings.AUTH_REFRESH_COOKIE_ENABLED or not token:
        return
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        value=token,
        max_age=max(0, int(max_age_seconds)),
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=f"{settings.API_V1_PREFIX}/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Hapus cookie refresh (dipakai saat logout)."""
    response.delete_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        path=f"{settings.API_V1_PREFIX}/auth",
    )


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
) -> Token:
    """Login OAuth2 password flow. Isi `username` dengan username (CH...) atau email."""
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

    user = await get_user_by_login(session, form_data.username)
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
            detail="Username/email atau password salah.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Akun dinonaktifkan."
        )

    _login_limiter.reset(key)
    # Sesi tunggal (SEMUA peran): buat ID sesi baru & simpan sebagai satu-satunya
    # sesi sah. Login ini otomatis menggugurkan sesi/token di perangkat lain.
    sid = secrets.token_urlsafe(24)
    user.session_token = sid
    session.add(user)
    await session.commit()
    invalidate_auth_cache(user.id)
    tokens = _issue_tokens(user, sid)
    _set_refresh_cookie(response, tokens.refresh_token, tokens.refresh_expires_in or 0)
    return tokens


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    session: AsyncSession = Depends(get_db),
) -> Token:
    """Tukar refresh token dengan ACCESS token baru (refresh TIDAK diperpanjang).

    Refresh hanya sah bila: tanda tangan valid, bertipe `refresh`, belum
    kedaluwarsa, akun aktif, dan `sid` masih sama dengan sesi aktif user
    (sesi tunggal -> login di perangkat lain menggugurkan refresh token ini).
    Karena refresh tidak diperpanjang, ada BATAS KERAS: admin wajib login ulang
    setelah masa refresh (mis. 30 hari).
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesi berakhir. Silakan login kembali.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # Refresh token: cookie HttpOnly (diutamakan) atau body (backward-compat).
    refresh_tok = request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME) or (
        payload.refresh_token if payload else None
    )
    if not refresh_tok:
        raise invalid
    try:
        data = decode_access_token(refresh_tok)
    except jwt.PyJWTError:
        raise invalid
    if data.get("type") != "refresh":
        raise invalid
    sub = data.get("sub")
    sid = data.get("sid")
    if sub is None or not sid:
        raise invalid
    try:
        uid = int(sub)
    except (TypeError, ValueError):
        raise invalid
    user = await session.get(User, uid)
    if user is None or not user.is_active:
        raise invalid
    if user.session_token != sid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi berakhir: akun ini login di perangkat lain.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access = create_access_token(
        subject=str(user.id), role=user.role.value, session_id=sid
    )
    # Sinkronkan cookie dgn sisa umur refresh token (refresh TIDAK diperpanjang).
    exp = data.get("exp")
    remaining = int(exp - time.time()) if exp else 0
    if remaining > 0:
        _set_refresh_cookie(response, refresh_tok, remaining)
    return Token(
        access_token=access,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=refresh_tok,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Logout: HAPUS sesi aktif dari server (session_token=None) sehingga SEMUA
    token (access & refresh) milik user ini langsung TIDAK berlaku lagi.

    Tanpa ini, refresh token masih sah s/d kedaluwarsa (mis. 30 hari utk admin)
    walau user sudah logout ("terhapus dari sistem"). Cookie refresh juga dihapus.
    """
    _clear_refresh_cookie(response)
    user = await session.get(User, current_user.id)
    if user is not None:
        user.session_token = None
        session.add(user)
        await session.commit()
        invalidate_auth_cache(user.id)


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
    try:
        validate_password_strength(
            payload.new_password,
            identifiers=[user.email, user.email.split("@")[0], user.username or ""],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    user.hashed_password = hash_password(payload.new_password)
    session.add(user)
    await session.commit()


@router.put("/avatar", response_model=UserOut)
async def update_avatar(
    payload: AvatarUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Set / hapus foto profil SENDIRI.

    Foto dikirim sebagai data URL base64 (sudah diperkecil 256px di sisi klien)
    lalu disimpan di kolom `users.avatar`. Pendekatan ini membuat foto SINKRON di
    semua perangkat & TERLIHAT admin, tanpa menyimpan berkas di disk server.
    Kirim `avatar: null` untuk menghapus foto.
    """
    avatar = (payload.avatar or "").strip() or None
    if avatar is not None:
        if not avatar.startswith("data:image/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Foto harus berupa data URL gambar (data:image/...).",
            )
        if len(avatar) > settings.AVATAR_MAX_CHARS:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Ukuran foto terlalu besar. Gunakan gambar yang lebih kecil.",
            )
    user = await session.get(User, current_user.id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan."
        )
    user.avatar = avatar
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

