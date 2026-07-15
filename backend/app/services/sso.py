"""Integrasi SSO Unismuh (Keycloak / OpenID Connect).

Autentikasi didelegasikan ke SSO kampus via OIDC Authorization Code + PKCE (S256).
Endpoint diambil dari DISCOVERY ({issuer}/.well-known/openid-configuration) — tidak
di-hardcode. ID token diverifikasi dengan JWKS (PyJWT). Peran diambil dari
`realm_access.roles` pada ACCESS token (bukan dari email), sesuai panduan SSO Unismuh.

ADDITIVE: modul ini tidak menyentuh login lokal (username/password). Hanya aktif bila
`settings.SSO_ENABLED` dan aplikasi sudah didaftarkan ke admin SSO (client_id + secret).
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import settings
from app.models.user import UserRole

logger = logging.getLogger(__name__)


class SsoError(RuntimeError):
    """Kegagalan alur SSO (discovery / tukar token / verifikasi)."""


@dataclasses.dataclass
class SsoIdentity:
    """Identitas hasil login SSO yang sudah diverifikasi."""

    sub: str
    email: str
    name: str
    preferred_username: str
    roles: list[str]
    nim: str | None = None
    nidn: str | None = None


# Cache metadata discovery + JWKS client per issuer (hindari fetch tiap login).
_meta_cache: dict[str, tuple[float, dict]] = {}
_META_TTL = 3600.0
_jwk_clients: dict[str, jwt.PyJWKClient] = {}


async def _discovery() -> dict:
    issuer = settings.SSO_ISSUER.rstrip("/")
    cached = _meta_cache.get(issuer)
    if cached and (time.time() - cached[0]) < _META_TTL:
        return cached[1]
    url = f"{issuer}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            meta = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise SsoError(f"Gagal ambil discovery SSO ({url}): {exc}") from exc
    _meta_cache[issuer] = (time.time(), meta)
    return meta


def _jwk_client(jwks_uri: str) -> jwt.PyJWKClient:
    client = _jwk_clients.get(jwks_uri)
    if client is None:
        client = jwt.PyJWKClient(jwks_uri)
        _jwk_clients[jwks_uri] = client
    return client


def _pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) untuk PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


async def build_authorization_url() -> tuple[str, dict]:
    """Bangun URL authorization + rahasia sementara {state, nonce, code_verifier}.

    Rahasia disimpan sesaat (cookie tertanda) oleh router lalu diverifikasi di callback.
    """
    meta = await _discovery()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.SSO_CLIENT_ID,
        "response_type": "code",
        "scope": " ".join(settings.sso_scope_list),
        "redirect_uri": settings.sso_redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{meta['authorization_endpoint']}?{urlencode(params)}"
    return url, {"state": state, "nonce": nonce, "code_verifier": verifier}


async def _exchange_code(code: str, code_verifier: str, meta: dict) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.sso_redirect_uri,
        "client_id": settings.SSO_CLIENT_ID,
        "code_verifier": code_verifier,
    }
    if settings.SSO_CLIENT_SECRET:
        data["client_secret"] = settings.SSO_CLIENT_SECRET
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(meta["token_endpoint"], data=data)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        raise SsoError(f"Gagal tukar authorization code: {exc}") from exc


def _verify_jwt(
    token: str,
    jwks_uri: str,
    *,
    issuer: str,
    audience: str | None,
    nonce: str | None = None,
    verify_aud: bool = True,
) -> dict:
    """Verifikasi tanda tangan (JWKS) + iss/exp (+ aud/nonce bila diminta)."""
    signing_key = _jwk_client(jwks_uri).get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience if verify_aud else None,
        issuer=issuer,
        options={"verify_aud": verify_aud},
    )
    if nonce is not None and claims.get("nonce") != nonce:
        raise SsoError("Nonce ID token tidak cocok (anti-replay).")
    return claims


async def complete_login(code: str, code_verifier: str, expected_nonce: str) -> SsoIdentity:
    """Tukar code -> token, verifikasi, kembalikan identitas terverifikasi."""
    meta = await _discovery()
    issuer = meta.get("issuer", settings.SSO_ISSUER.rstrip("/"))
    jwks_uri = meta["jwks_uri"]
    tokens = await _exchange_code(code, code_verifier, meta)
    id_token = tokens.get("id_token")
    access_token = tokens.get("access_token")
    if not id_token or not access_token:
        raise SsoError("Respons token SSO tidak lengkap (id_token/access_token).")

    # ID token: verifikasi penuh (aud = client_id, nonce). JWKS sinkron -> threadpool.
    id_claims = await asyncio.to_thread(
        _verify_jwt, id_token, jwks_uri,
        issuer=issuer, audience=settings.SSO_CLIENT_ID, nonce=expected_nonce, verify_aud=True,
    )
    # Access token: aud default Keycloak = 'account' -> jangan validasi aud ketat;
    # cek azp == client_id sebagai gantinya (sesuai panduan SSO).
    acc_claims = await asyncio.to_thread(
        _verify_jwt, access_token, jwks_uri,
        issuer=issuer, audience=None, verify_aud=False,
    )
    azp = acc_claims.get("azp")
    if azp and azp != settings.SSO_CLIENT_ID:
        raise SsoError("azp access token tidak cocok dengan client_id.")

    roles = list((acc_claims.get("realm_access") or {}).get("roles") or [])
    email = (id_claims.get("email") or acc_claims.get("email") or "").strip().lower()
    return SsoIdentity(
        sub=str(id_claims["sub"]),
        email=email,
        name=(id_claims.get("name") or acc_claims.get("name") or email or "Pengguna SSO"),
        preferred_username=(
            id_claims.get("preferred_username")
            or acc_claims.get("preferred_username")
            or ""
        ),
        roles=roles,
        nim=id_claims.get("nim") or acc_claims.get("nim"),
        nidn=id_claims.get("nidn") or acc_claims.get("nidn"),
    )


def map_role(roles: list[str], email: str) -> UserRole:
    """Peran SSO -> peran ComputeHub. Prioritas realm_access.roles, fallback domain email.

    Hanya dipakai untuk user BARU. User lama mempertahankan peran yang sudah diset di app.
    """
    rset = {r.lower() for r in roles}
    if "dosen" in rset:
        return UserRole.dosen
    if "mahasiswa" in rset:
        return UserRole.mahasiswa
    if rset & {r.lower() for r in settings.sso_admin_role_set}:
        return UserRole.admin
    e = (email or "").strip().lower()
    if e.endswith("@" + settings.SSO_MAHASISWA_EMAIL_DOMAIN.lower()):
        return UserRole.mahasiswa
    if e.endswith("@" + settings.SSO_DOSEN_EMAIL_DOMAIN.lower()):
        return UserRole.dosen
    return UserRole.mahasiswa
