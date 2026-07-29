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

import asyncio
import logging
import secrets
import subprocess
import sys
import time
from pathlib import Path
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
from app.models.user import User, UserRole
from app.services import email as email_svc
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
    """Status SSO untuk FE: tombol SSO + mode satu pintu (sso_only)."""
    return {
        "enabled": bool(settings.SSO_ENABLED),
        "sso_only": bool(settings.SSO_ONLY_LOGIN),
    }


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


async def _upsert_user(
    session: AsyncSession, identity: sso_service.SsoIdentity
) -> tuple[User | None, str]:
    """Cari user by `sub` -> by email (tautkan) -> buat baru.

    Return (user, "") bila boleh masuk; (None, pesan) bila ditolak.
    User LAMA: peran dosen/mahasiswa DISINKRON dari SSO tiap login; akun ADMIN tak
    pernah diubah otomatis; status aktif/nonaktif tetap wewenang app (persetujuan/
    penonaktifan admin tidak dilawan oleh SSO).
    User BARU: peran dari peran resmi SSO; peran TAK DIKENALI (staf) -> akun dibuat
    NONAKTIF sebagai PERMINTAAN AKSES + pengelola diberi tahu (Telegram+email).
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
        role = sso_service.map_role(identity.roles, identity.email)
        pending = role is None  # staf / peran tak dikenali -> wajib persetujuan
        user = User(
            name=identity.name,
            email=identity.email,
            username=username,
            hashed_password=hash_password(secrets.token_urlsafe(32)),  # tak bisa login lokal
            sso_sub=identity.sub,
            # Placeholder dosen utk akun pending; pengelola bisa mengubahnya di menu
            # Pengguna SEBELUM mengaktifkan (akun nonaktif tak bisa dipakai apa pun).
            role=role or UserRole.dosen,
            is_active=not pending,
        )
        session.add(user)
        await session.flush()
        logger.info(
            "SSO: akun baru %s (sub=%s) role=%s pending=%s",
            user.email, identity.sub, user.role.value, pending,
        )
        if pending:
            # Simpan permintaan WALAU login ditolak (callback tak akan commit lagi).
            await session.commit()
            await _kabari_pengelola_pending(session, user)
            return None, (
                "Permintaan akses Anda sudah tercatat dan pengelola telah diberi tahu. "
                "Anda bisa masuk setelah akun disetujui admin."
            )
    else:
        if identity.name and user.name != identity.name:
            user.name = identity.name  # sinkron nama
        # SINKRON PERAN dari SSO di TIAP login untuk peran yang DIKENALI: jabatan di
        # SSO = sumber kebenaran dosen/mahasiswa (mis. mahasiswa lulus jadi dosen,
        # atau akun yang dulu salah label). Dua pengecualian yang disengaja:
        # - Akun ADMIN tidak pernah diubah otomatis (diatur manual di app).
        # - Peran SSO TAK DIKENALI (staf) pada akun AKTIF dibiarkan: akun aktif
        #   berperan non-admin dengan peran SSO staf hanya bisa ada karena SUDAH
        #   disetujui pengelola (akun baru staf selalu lahir nonaktif) -> jangan
        #   dilawan; mencabutnya kembali = keputusan manual admin di menu Pengguna.
        if user.role != UserRole.admin:
            role_sso = sso_service.map_role(identity.roles, identity.email)
            if role_sso is not None and role_sso != user.role:
                logger.info(
                    "SSO: sinkron peran %s: %s -> %s",
                    user.email, user.role.value, role_sso.value,
                )
                user.role = role_sso

    if not user.is_active:
        # Simpan hasil sinkron nama/peran walau login ditolak — pengelola jadi bisa
        # melihat peran TERBARU versi SSO di menu Pengguna saat menimbang persetujuan.
        await session.commit()
        return None, (
            "Akun Anda belum aktif (menunggu persetujuan/aktivasi pengelola). "
            "Hubungi admin lab / IT bila mendesak."
        )
    return user, ""


async def _kabari_pengelola_pending(session: AsyncSession, user: User) -> None:
    """Best-effort: kabari semua admin ada PERMINTAAN AKSES staf (Telegram + email)."""
    try:
        rows = await session.execute(
            select(User.email).where(User.role == UserRole.admin, User.is_active.is_(True))
        )
        recipients = sorted({e.strip() for (e,) in rows if e and e.strip()})
        subject = f"Permintaan akses staf: {user.name or user.email} — {settings.PROJECT_NAME}"
        body = (
            f"{user.name or 'Pengguna'} ({user.email}) login lewat SSO tetapi perannya "
            "tidak dikenali (bukan dosen/mahasiswa — kemungkinan STAF kampus).\n\n"
            "Akun sudah dibuat berstatus NONAKTIF sebagai permintaan akses.\n"
            "Tindak lanjut: buka menu Pengguna → atur role yang pantas → aktifkan.\n"
            + (f"\nBuka: {settings.public_base_url}/users" if settings.public_base_url else "")
        )
        skrip = Path(__file__).resolve().parents[3] / "scripts" / "notify_telegram.py"
        if skrip.exists():
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, str(skrip), f"\U0001f511 {subject}", body],
                    capture_output=True, timeout=30, check=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Telegram permintaan staf gagal: %r", exc)
        if recipients and settings.smtp_configured:
            await asyncio.to_thread(email_svc.send_email, recipients, subject, body)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Notifikasi permintaan staf gagal: %r", exc)


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
        user, tolak = await _upsert_user(session, identity)
        if user is None:
            return _fail_redirect(fe_base, tolak or "Akun tidak dapat digunakan.")
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
