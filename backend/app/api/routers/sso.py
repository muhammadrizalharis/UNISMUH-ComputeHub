"""Router SSO Unismuh (OIDC Authorization Code + PKCE).

ADDITIVE: endpoint di bawah HANYA aktif bila `settings.SSO_ENABLED`. Login lokal
(username/password) di `auth.py` tidak disentuh.

Alur:
  GET /auth/sso/login    -> mulai PKCE+state+nonce (cookie tertanda), redirect ke SSO.
  GET /auth/sso/callback -> verifikasi, buat/tautkan user (kunci = klaim `sub`),
                            terbitkan token ComputeHub (access+refresh) seperti login biasa,
                            redirect ke FE `/sso/callback#access_token=...`.
  GET /auth/sso/status   -> {enabled} (dipakai FE utk menampilkan tombol SSO).
"""

from __future__ import annotations

import logging
import secrets
import time
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import invalidate_auth_cache
from app.api.routers.auth import _issue_tokens, _set_refresh_cookie
from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.services import sso as sso_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Cookie sementara (tertanda) penyimpan state/nonce/code_verifier antar /login -> /callback.
_TX_COOKIE = "ch_sso_tx"
_TX_TTL_SECONDS = 600


def _tx_cookie_path() -> str:
    return f"{settings.API_V1_PREFIX}/auth/sso"


def _fail_redirect(fe_base: str, message: str) -> RedirectResponse:
    """Kembali ke FE dengan pesan error (di fragment, tak masuk log server)."""
    return RedirectResponse(
        f"{fe_base}/sso/callback#error={quote(message)}", status_code=302
    )


@router.get("/status")
async def sso_status() -> dict:
    """Status SSO untuk FE (tampilkan tombol hanya bila aktif)."""
    return {"enabled": bool(settings.SSO_ENABLED)}


@router.get("/login")
async def sso_login() -> RedirectResponse:
    """Mulai alur login SSO: PKCE + state + nonce, lalu redirect ke authorization endpoint."""
    if not settings.SSO_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO tidak aktif.")
    try:
        url, tx = await sso_service.build_authorization_url()
    except sso_service.SsoError as exc:
        logger.warning("SSO login gagal (discovery): %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SSO tidak dapat dihubungi. Coba lagi nanti.",
        ) from exc
    tx_token = jwt.encode(
        {**tx, "exp": int(time.time()) + _TX_TTL_SECONDS},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(
        key=_TX_COOKIE,
        value=tx_token,
        max_age=_TX_TTL_SECONDS,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",  # lax: dikirim saat navigasi top-level GET balik dari SSO
        path=_tx_cookie_path(),
    )
    return resp


async def _upsert_user(session: AsyncSession, identity: sso_service.SsoIdentity) -> User | None:
    """Cari user by `sub` -> by email (tautkan) -> buat baru. None bila akun nonaktif.

    User LAMA: pertahankan peran & status app (jangan turunkan admin jadi dosen).
    User BARU: peran dipetakan dari SSO/domain email.
    """
    user = (
        await session.execute(select(User).where(User.sso_sub == identity.sub))
    ).scalar_one_or_none()

    if user is None and identity.email:
        user = (
            await session.execute(
                select(User).where(func.lower(User.email) == identity.email)
            )
        ).scalar_one_or_none()
        if user is not None:
            user.sso_sub = identity.sub  # tautkan akun lokal yang sudah ada ke SSO

    if user is None:
        username = identity.preferred_username or None
        if username:
            taken = (
                await session.execute(select(User.id).where(User.username == username))
            ).scalar_one_or_none()
            if taken is not None:
                username = None
        user = User(
            name=identity.name,
            email=identity.email,
            username=username,
            hashed_password=hash_password(secrets.token_urlsafe(32)),  # tak bisa login lokal
            sso_sub=identity.sub,
            role=sso_service.map_role(identity.roles, identity.email),
            is_active=True,
        )
        session.add(user)
        await session.flush()
        logger.info(
            "SSO: akun baru %s (sub=%s) role=%s", user.email, identity.sub, user.role.value
        )
    elif identity.name and user.name != identity.name:
        user.name = identity.name  # sinkron nama; peran/status TIDAK diubah

    if not user.is_active:
        return None
    return user


@router.get("/callback")
async def sso_callback(request: Request, session: AsyncSession = Depends(get_db)):
    """Terima code dari SSO, verifikasi, terbitkan token ComputeHub, redirect ke FE."""
    if not settings.SSO_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO tidak aktif.")
    fe_base = settings.public_base_url or ""

    if request.query_params.get("error"):
        return _fail_redirect(fe_base, f"SSO menolak login: {request.query_params.get('error')}")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    tx_cookie = request.cookies.get(_TX_COOKIE)
    if not code or not state or not tx_cookie:
        return _fail_redirect(fe_base, "Parameter callback tidak lengkap.")

    try:
        tx = jwt.decode(tx_cookie, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return _fail_redirect(fe_base, "Sesi login SSO kedaluwarsa. Silakan coba lagi.")
    if not secrets.compare_digest(state, str(tx.get("state", ""))):
        return _fail_redirect(fe_base, "State tidak cocok (anti-CSRF).")

    try:
        identity = await sso_service.complete_login(
            code, str(tx.get("code_verifier", "")), str(tx.get("nonce", ""))
        )
    except sso_service.SsoError as exc:
        logger.warning("SSO callback gagal: %s", exc)
        return _fail_redirect(fe_base, "Verifikasi SSO gagal. Silakan coba lagi.")

    try:
        user = await _upsert_user(session, identity)
        if user is None:
            return _fail_redirect(fe_base, "Akun dinonaktifkan. Hubungi admin lab / IT.")
        sid = secrets.token_urlsafe(24)
        user.session_token = sid
        session.add(user)
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("SSO gagal menyimpan user: %s", exc)
        await session.rollback()
        return _fail_redirect(fe_base, "Gagal membuat sesi. Silakan coba lagi.")

    invalidate_auth_cache(user.id)
    tokens = _issue_tokens(user, sid)
    fe_url = (
        f"{fe_base}/sso/callback#access_token={quote(tokens.access_token)}"
        f"&expires_in={tokens.expires_in or 0}"
    )
    resp = RedirectResponse(fe_url, status_code=302)
    _set_refresh_cookie(resp, tokens.refresh_token, tokens.refresh_expires_in or 0)
    resp.delete_cookie(_TX_COOKIE, path=_tx_cookie_path())
    return resp
