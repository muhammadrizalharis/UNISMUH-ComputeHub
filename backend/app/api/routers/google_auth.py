"""Pintu Google untuk /welcome/user; tidak menautkan akun kampus/pengelola lewat email."""

from __future__ import annotations

import secrets
import time
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import invalidate_auth_cache
from app.api.routers.auth import _client_key, _issue_tokens, _set_refresh_cookie
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.ratelimit import SlidingWindowRateLimiter
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services import accounts, google_auth

router = APIRouter()
logger = get_logger(__name__)
_COOKIE = "ch_google_tx"
_TTL = 600
_limiter = SlidingWindowRateLimiter(20, 60, 60)


def _cookie_path() -> str:
    return f"{settings.API_V1_PREFIX}/auth/google"


@router.get("/status")
async def status() -> dict:
    return {"configured": settings.google_configured}


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    if not settings.google_configured:
        raise HTTPException(503, "Login Google belum dikonfigurasi oleh pengelola.")
    key = _client_key(request)
    rate = _limiter.check(key)
    if rate.allowed:
        rate = _limiter.record_failure(key)
    if not rate.allowed:
        raise HTTPException(429, "Terlalu banyak permintaan login Google.", headers={"Retry-After": str(rate.retry_after)})
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    url, verifier = google_auth.authorization_url(state, nonce)
    tx = jwt.encode({
        "type": "google_tx", "state": state, "nonce": nonce, "verifier": verifier,
        "exp": int(time.time()) + _TTL,
    }, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        _COOKIE, tx, max_age=_TTL, httponly=True,
        secure=settings.AUTH_COOKIE_SECURE, samesite="lax", path=_cookie_path(),
    )
    return response


async def upsert_user(session: AsyncSession, identity: google_auth.GoogleIdentity) -> User:
    user = await session.scalar(select(User).where(User.google_sub == identity.sub))
    if user is None:
        existing = await session.scalar(
            select(User.id).where(func.lower(User.email) == identity.email)
        )
        if existing is not None:
            raise google_auth.GoogleAuthError(
                "Email ini sudah terdaftar pada akun lain. Hubungi admin; akun tidak ditautkan otomatis."
            )
        user = User(
            name=identity.name, email=identity.email, google_sub=identity.sub,
            username=await accounts.generate_unique_username(session, identity.email),
            hashed_password=hash_password(secrets.token_urlsafe(48)),
            role=UserRole.mahasiswa, is_local=True, is_active=True,
            access_approved=False, can_admin=False,
        )
        session.add(user)
        await session.flush()
    if not user.is_local or user.is_superadmin or user.can_admin or user.role == UserRole.admin or user.is_sso:
        raise google_auth.GoogleAuthError("Identitas Google tidak dapat digunakan pada pintu lokal.")
    if not user.is_active:
        raise google_auth.GoogleAuthError("Akun dinonaktifkan oleh admin. Hubungi pengelola.")
    return user


@router.get("/callback")
async def callback(request: Request, session: AsyncSession = Depends(get_db)) -> RedirectResponse:
    base = settings.public_base_url

    def fail(message: str) -> RedirectResponse:
        response = RedirectResponse(f"{base}/google/callback#error={quote(message)}", status_code=302)
        response.delete_cookie(_COOKIE, path=_cookie_path())
        return response

    if not settings.google_configured:
        return fail("Login Google belum dikonfigurasi oleh pengelola.")
    if request.query_params.get("error"):
        return fail("Login Google dibatalkan atau ditolak. Silakan coba lagi.")
    code, state = request.query_params.get("code"), request.query_params.get("state")
    cookie = request.cookies.get(_COOKIE)
    if not code or not state or not cookie:
        return fail("Sesi login Google tidak lengkap. Mulai lagi dari /welcome/user.")
    try:
        tx = jwt.decode(cookie, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return fail("Sesi login Google kedaluwarsa. Silakan coba lagi.")
    if tx.get("type") != "google_tx" or not secrets.compare_digest(state, str(tx.get("state", ""))):
        return fail("State login Google tidak cocok. Silakan ulangi login.")
    verifier, nonce = tx.get("verifier"), tx.get("nonce")
    if not isinstance(verifier, str) or not verifier or not isinstance(nonce, str) or not nonce:
        return fail("Sesi login Google tidak valid.")
    try:
        identity = await google_auth.complete_login(code, verifier, nonce)
        user = await upsert_user(session, identity)
        sid = secrets.token_urlsafe(24)
        user.session_token = sid
        await session.commit()
    except google_auth.GoogleAuthError as exc:
        await session.rollback()
        logger.warning("Login Google ditolak: %s", exc)
        return fail(str(exc))
    except IntegrityError:
        await session.rollback()
        logger.warning("Login Google mengalami benturan identitas; transaksi dibatalkan.")
        return fail("Identitas akun berubah bersamaan. Silakan ulangi atau hubungi admin.")
    invalidate_auth_cache(user.id)
    tokens = _issue_tokens(user, sid)
    response = RedirectResponse(
        f"{base}/google/callback#access_token={quote(tokens.access_token)}", status_code=302,
    )
    _set_refresh_cookie(response, tokens.refresh_token, tokens.refresh_expires_in or 0)
    response.delete_cookie(_COOKIE, path=_cookie_path())
    return response
