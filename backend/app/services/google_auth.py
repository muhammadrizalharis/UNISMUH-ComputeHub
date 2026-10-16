"""Google OIDC untuk akun lokal; identitas hanya berasal dari ID token terverifikasi."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import settings
from app.services.sso import SsoError, _pkce_pair, _verify_jwt

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"


class GoogleAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str


def authorization_url(state: str, nonce: str) -> tuple[str, str]:
    verifier, challenge = _pkce_pair()
    query = urlencode({
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return f"{AUTHORIZE_URL}?{query}", verifier


async def complete_login(code: str, verifier: str, nonce: str) -> GoogleIdentity:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(TOKEN_URL, data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            })
            response.raise_for_status()
            tokens = response.json()
        if not isinstance(tokens, dict):
            raise GoogleAuthError("Respons token Google tidak valid.")
        token = tokens.get("id_token")
        if not isinstance(token, str) or not token:
            raise GoogleAuthError("Google tidak mengembalikan ID token.")
        try:
            claims = await asyncio.to_thread(
                _verify_jwt, token, JWKS_URL,
                issuer="https://accounts.google.com",
                audience=settings.GOOGLE_CLIENT_ID, nonce=nonce,
            )
        except jwt.InvalidIssuerError:
            # Google mendokumentasikan kedua bentuk issuer ini.
            claims = await asyncio.to_thread(
                _verify_jwt, token, JWKS_URL, issuer="accounts.google.com",
                audience=settings.GOOGLE_CLIENT_ID, nonce=nonce,
            )
    except (httpx.HTTPError, jwt.PyJWTError, SsoError, ValueError) as exc:
        raise GoogleAuthError("Verifikasi akun Google gagal. Silakan coba lagi.") from exc
    sub = claims.get("sub")
    email = claims.get("email")
    if (
        claims.get("email_verified") is not True
        or not isinstance(sub, str) or not sub or len(sub) > 255
        or not isinstance(email, str) or "@" not in email or len(email) > 255
    ):
        raise GoogleAuthError("Identitas Google tidak lengkap atau email belum terverifikasi.")
    name = claims.get("name")
    return GoogleIdentity(sub, email.strip().lower(), (name if isinstance(name, str) else email)[:255])
