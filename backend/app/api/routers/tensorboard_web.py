"""Proxy tampilan TensorBoard milik user -> <domain>/tensorboard/<uid>/.

TensorBoard tidak punya login sendiri, jadi semua akses lewat sini:
  1. Tab dibuka dengan TIKET sekali-pakai berumur pendek (POST /api/v1/tensorboard/start
     atau /ticket, butuh login ComputeHub) yang ditukar menjadi COOKIE HttpOnly ber-path
     /tensorboard/<uid>. Tiap permintaan memeriksa sesi tunggal ComputeHub, jadi
     logout / login di perangkat lain langsung memutus akses.
  2. Hanya PEMILIK: sub cookie harus sama dengan <uid> di path.
  3. Upstream adalah IP container di jaringan Docker internal (tak terjangkau dari luar).
Setiap permintaan yang lolos memperbarui jam "terakhir dibuka" (dasar mati otomatis).
"""

from __future__ import annotations

import datetime as dt
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.api.deps import session_active
from app.core.config import settings
from app.core.logging import get_logger
from app.services import tensorboard as tb_svc
from app.services.tensorboard import tensorboard_manager

logger = get_logger(__name__)
router = APIRouter()

TICKET_PARAM = "ch_ticket"
COOKIE_NAME = "ch_tensorboard"
_TICKET_TYPE = "tensorboard_ticket"
_SESSION_TYPE = "tensorboard_session"
_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
    "trailer", "transfer-encoding", "upgrade", "host", "content-length", "authorization",
}
_UPSTREAM_STRIP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "set-cookie"}

_used_tickets: dict[str, float] = {}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ticket_seconds() -> int:
    return max(10, int(settings.TENSORBOARD_TICKET_SECONDS))


def make_ticket(user_id: int, sid: str) -> str:
    payload = {
        "sub": str(int(user_id)), "sid": sid, "type": _TICKET_TYPE,
        "jti": secrets.token_urlsafe(16), "iat": _now(),
        "exp": _now() + dt.timedelta(seconds=_ticket_seconds()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def make_session_cookie(user_id: int, sid: str) -> str:
    menit = max(1, int(settings.TENSORBOARD_SESSION_MINUTES))
    payload = {
        "sub": str(int(user_id)), "sid": sid, "type": _SESSION_TYPE, "iat": _now(),
        "exp": _now() + dt.timedelta(minutes=menit),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode(token: str, expected_type: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type or not payload.get("sid"):
        return None
    try:
        payload["uid"] = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    return payload


def consume_ticket(token: str, user_id: int) -> dict[str, Any] | None:
    payload = _decode(token, _TICKET_TYPE)
    if payload is None or payload["uid"] != int(user_id):
        return None
    jti = str(payload.get("jti") or "")
    now = time.time()
    for k in [k for k, v in _used_tickets.items() if v < now]:
        _used_tickets.pop(k, None)
    if not jti or jti in _used_tickets:
        return None
    _used_tickets[jti] = now + _ticket_seconds() + 5
    return payload


def verify_session_cookie(value: str | None, user_id: int) -> dict[str, Any] | None:
    if not value:
        return None
    payload = _decode(value, _SESSION_TYPE)
    if payload is None or payload["uid"] != int(user_id):
        return None
    return payload


def cookie_path(user_id: int) -> str:
    return tb_svc.base_path(user_id).rstrip("/")


def upstream_headers(incoming: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Header ke TensorBoard: tanpa hop-by-hop, tanpa Authorization, tanpa cookie apa pun."""
    return [
        (k, v) for k, v in incoming
        if k.lower() not in _HOP_HEADERS and k.lower() != "cookie"
    ]


def _html(status_code: int, judul: str, isi: str) -> HTMLResponse:
    return HTMLResponse(
        status_code=status_code,
        content=(
            "<!doctype html><html lang='id'><head><meta charset='utf-8'>"
            f"<title>{judul} — UNISMUH ComputeHub</title>"
            "<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;"
            "display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:32rem;"
            "padding:2rem;text-align:center}a{color:#7dd3fc}</style></head><body><main>"
            f"<h1 style='font-size:1.25rem'>{judul}</h1><p>{isi}</p>"
            "<p><a href='/storage'>Kembali ke Penyimpanan</a></p></main></body></html>"
        ),
    )


async def _authorize(request: Request, uid: int) -> dict[str, Any] | Response:
    claims = verify_session_cookie(request.cookies.get(COOKIE_NAME), uid)
    if claims is not None and await session_active(uid, claims["sid"]):
        return claims
    ticket = request.query_params.get(TICKET_PARAM)
    if ticket:
        payload = consume_ticket(ticket, uid)
        if payload is not None and await session_active(uid, payload["sid"]):
            params = [(k, v) for k, v in request.query_params.multi_items() if k != TICKET_PARAM]
            target = request.url.path + (f"?{urlencode(params)}" if params else "")
            resp = RedirectResponse(url=target, status_code=303)
            resp.set_cookie(
                key=COOKIE_NAME,
                value=make_session_cookie(uid, payload["sid"]),
                max_age=max(60, int(settings.TENSORBOARD_SESSION_MINUTES) * 60),
                httponly=True,
                secure=bool(settings.AUTH_COOKIE_SECURE),
                samesite="lax",
                path=cookie_path(uid),
            )
            return resp
    if request.headers.get("accept", "").startswith("text/html") or (
        request.url.path.rstrip("/") == cookie_path(uid)
    ):
        return _html(
            401, "Sesi TensorBoard tidak sah",
            "Buka grafik lewat tombol <b>Lihat grafik</b> di ComputeHub. Tautan langsung "
            "tidak bisa dipakai tanpa masuk terlebih dahulu.",
        )
    return JSONResponse(status_code=401, content={"detail": "Sesi TensorBoard tidak sah."})


_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=60.0, pool=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            follow_redirects=False,
        )
    return _client


async def _proxy(request: Request, uid: int) -> Response:
    if not tb_svc.enabled():
        return _html(404, "TensorBoard nonaktif", "Fitur ini sedang dinonaktifkan admin.")
    auth = await _authorize(request, uid)
    if isinstance(auth, Response):
        return auth
    target = tensorboard_manager.target(uid)
    if target is None:
        return _html(
            503, "TensorBoard sudah berhenti",
            "TensorBoard dimatikan otomatis karena lama tidak dibuka. Tekan "
            "<b>Lihat grafik</b> lagi di ComputeHub untuk menyalakannya.",
        )
    tensorboard_manager.touch(uid)
    ip, port = target
    url = f"http://{ip}:{port}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    body = request.stream() if request.method not in ("GET", "HEAD", "OPTIONS") else None
    try:
        req = _http().build_request(
            request.method, url, headers=upstream_headers(request.headers.items()), content=body
        )
        upstream = await _http().send(req, stream=True)
    except httpx.HTTPError as exc:
        logger.warning("Proxy TensorBoard #%d gagal: %s", uid, exc)
        return _html(502, "TensorBoard tidak menjawab", "Coba muat ulang halaman sebentar lagi.")
    headers = [(k, v) for k, v in upstream.headers.multi_items() if k.lower() not in _UPSTREAM_STRIP]
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=dict(headers),
        background=BackgroundTask(upstream.aclose),
    )


_METHODS = ["GET", "POST", "HEAD"]


def _mount(prefix: str) -> None:
    @router.api_route(prefix + "/{uid:int}", methods=_METHODS, include_in_schema=False)
    async def _root(request: Request, uid: int) -> Response:  # noqa: ANN001
        if request.url.path.endswith("/"):
            return await _proxy(request, uid)
        # TensorBoard memakai URL relatif: tanpa '/' penutup aset salah alamat.
        q = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(url=f"{request.url.path}/{q}", status_code=307)

    @router.api_route(prefix + "/{uid:int}/{path:path}", methods=_METHODS, include_in_schema=False)
    async def _sub(request: Request, uid: int, path: str) -> Response:  # noqa: ANN001
        return await _proxy(request, uid)


_mount(tb_svc.path_prefix())
