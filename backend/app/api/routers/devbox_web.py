"""Proxy VS Code web (serve-web) di dalam devbox -> <domain>/devbox-ide/<uid>/.

Kenapa ada ini: pintu masuk devbox semula hanya VS Code Remote Tunnel (relay Microsoft
Azure). Jalur kampus ke relay itu punya PMTU black hole (21 Sep 2026: 13/20 jabat tangan
TLS menggantung; user "kadang bisa, kadang menggantung" lalu devbox mati otomatis).
Lewat domain kampus tidak ada satu pun hop Microsoft: browser -> nginx kampus -> backend
ini -> container devbox (jaringan Docker lokal).

KEAMANAN (lapisan yang berlaku bersamaan):
  1. Container hanya bisa dijangkau dari host (jaringan bridge, ICC mati); serve-web tetap
     memasang token koneksi acak per devbox. Proxy menyuntikkannya ke setiap permintaan
     upstream; browser juga memegangnya sebagai cookie `vscode-tkn` ber-path
     /devbox-ide/<uid> karena klien VS Code mengirimnya IN-BAND di jabat tangan WebSocket
     (tanpa itu server menjawab "Unauthorized client refused"). Token itu tak berguna di
     luar proxy: upstream-nya IP jaringan Docker internal.
  2. Browser membuka IDE lewat TIKET sekali-pakai berumur pendek (JWT dari
     POST /api/v1/devbox/web-ticket, butuh Bearer token ComputeHub), yang ditukar menjadi
     COOKIE sesi IDE HttpOnly ber-path /devbox-ide/<uid>. Cookie memuat sub+sid; tiap
     permintaan memeriksa sesi tunggal ComputeHub (cache singkat) -> logout/login di
     perangkat lain langsung memutus IDE.
  3. Hanya PEMILIK devbox: sub cookie harus sama dengan <uid> di path. Admin pun tidak bisa
     membuka IDE mahasiswa lewat jalur ini (kode/berkas mahasiswa = privasi).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
import websockets
from fastapi import APIRouter, Request, Response, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.api.deps import session_active
from app.core.config import settings
from app.core.logging import get_logger
from app.services import devbox as devbox_svc

logger = get_logger(__name__)
router = APIRouter()

_TICKET_TYPE = "devbox_web_ticket"
_SESSION_TYPE = "devbox_web_session"
_COOKIE_NAME = "ch_devbox_web"
_TICKET_PARAM = "ch_ticket"
# Header hop-by-hop yang tak boleh diteruskan proxy (RFC 7230 §6.1) + yang kita susun ulang.
_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
    "trailer", "transfer-encoding", "upgrade", "host", "content-length",
}
_UPSTREAM_STRIP = {"connection", "keep-alive", "transfer-encoding", "upgrade"}

# Tiket yang sudah ditukar (jti -> kedaluwarsa). Sekali pakai: URL berisi tiket yang
# bocor di riwayat browser / log proxy tidak bisa dipakai ulang.
_used_tickets: dict[str, float] = {}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def make_ticket(user_id: int, sid: str) -> str:
    exp = _now() + dt.timedelta(seconds=max(10, int(settings.DEVBOX_WEB_TICKET_SECONDS)))
    payload = {
        "sub": str(int(user_id)),
        "sid": sid,
        "type": _TICKET_TYPE,
        "jti": secrets.token_urlsafe(16),
        "iat": _now(),
        "exp": exp,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def make_session_cookie(user_id: int, sid: str) -> str:
    exp = _now() + dt.timedelta(minutes=max(1, int(settings.DEVBOX_WEB_SESSION_MINUTES)))
    payload = {"sub": str(int(user_id)), "sid": sid, "type": _SESSION_TYPE, "iat": _now(), "exp": exp}
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
    """Tukar tiket -> klaim, hanya bila milik <user_id> dan belum pernah dipakai."""
    payload = _decode(token, _TICKET_TYPE)
    if payload is None or payload["uid"] != int(user_id):
        return None
    jti = str(payload.get("jti") or "")
    now = time.time()
    for k in [k for k, v in _used_tickets.items() if v < now]:
        _used_tickets.pop(k, None)
    if not jti or jti in _used_tickets:
        return None
    _used_tickets[jti] = now + max(10, int(settings.DEVBOX_WEB_TICKET_SECONDS)) + 5
    return payload


def verify_session_cookie(value: str | None, user_id: int) -> dict[str, Any] | None:
    if not value:
        return None
    payload = _decode(value, _SESSION_TYPE)
    if payload is None or payload["uid"] != int(user_id):
        return None
    return payload


def cookie_path(user_id: int) -> str:
    # Tanpa '/' penutup: cocok untuk /devbox-ide/19 DAN /devbox-ide/19/... (RFC 6265).
    return devbox_svc.web_base_path(user_id).rstrip("/")


def build_upstream_headers(
    incoming: list[tuple[str, str]], token: str, host: str, scheme: str, client_ip: str
) -> list[tuple[str, str]]:
    """Header ke serve-web: buang hop-by-hop, ganti cookie sesi kita dengan token koneksi
    serve-web, tambah X-Forwarded-* agar URL absolut yang disusun server tetap benar."""
    out: list[tuple[str, str]] = []
    cookies: list[str] = []
    for name, value in incoming:
        lname = name.lower()
        if lname in _HOP_HEADERS:
            continue
        if lname == "cookie":
            for part in value.split(";"):
                part = part.strip()
                if part and not part.startswith((_COOKIE_NAME + "=", devbox_svc._WEB_TOKEN_COOKIE + "=")):
                    cookies.append(part)
            continue
        out.append((name, value))
    cookies.append(f"{devbox_svc._WEB_TOKEN_COOKIE}={token}")
    out.append(("cookie", "; ".join(cookies)))
    out.append(("x-forwarded-proto", scheme))
    out.append(("x-forwarded-host", host))
    out.append(("x-forwarded-for", client_ip))
    return out


def filter_response_headers(headers: httpx.Headers) -> list[tuple[str, str]]:
    """Header balasan serve-web ke browser: hop-by-hop dibuang; Set-Cookie `vscode-tkn`
    dari upstream dibuang karena proxy sendiri yang memasangnya dengan path yang benar
    (upstream memasangnya tanpa Path -> bisa bocor ke prefix induk)."""
    out: list[tuple[str, str]] = []
    for name, value in headers.multi_items():
        lname = name.lower()
        if lname in _UPSTREAM_STRIP:
            continue
        if lname == "set-cookie" and value.lstrip().startswith(devbox_svc._WEB_TOKEN_COOKIE + "="):
            continue
        out.append((name, value))
    return out


_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
            follow_redirects=False,
        )
    return _client


def _html(status: int, judul: str, isi: str) -> HTMLResponse:
    return HTMLResponse(
        status_code=status,
        content=(
            "<!doctype html><html lang='id'><head><meta charset='utf-8'>"
            f"<title>{judul} — UNISMUH ComputeHub</title>"
            "<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;"
            "display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:32rem;"
            "padding:2rem;text-align:center}a{color:#7dd3fc}</style></head><body><main>"
            f"<h1 style='font-size:1.25rem'>{judul}</h1><p>{isi}</p>"
            "<p><a href='/devbox'>Kembali ke menu Devbox</a></p></main></body></html>"
        ),
    )


async def _authorize(request: Request, uid: int) -> dict[str, Any] | Response:
    """Klaim sesi IDE yang sah, atau Response (redirect tukar tiket / halaman tolak)."""
    claims = verify_session_cookie(request.cookies.get(_COOKIE_NAME), uid)
    if claims is not None and await session_active(uid, claims["sid"]):
        return claims

    ticket = request.query_params.get(_TICKET_PARAM)
    if ticket:
        payload = consume_ticket(ticket, uid)
        if payload is not None and await session_active(uid, payload["sid"]):
            params = [(k, v) for k, v in request.query_params.multi_items() if k != _TICKET_PARAM]
            target = request.url.path + (f"?{urlencode(params)}" if params else "")
            resp = RedirectResponse(url=target, status_code=303)
            umur = max(60, int(settings.DEVBOX_WEB_SESSION_MINUTES) * 60)
            resp.set_cookie(
                key=_COOKIE_NAME,
                value=make_session_cookie(uid, payload["sid"]),
                max_age=umur,
                httponly=True,
                secure=bool(settings.AUTH_COOKIE_SECURE),
                samesite="lax",
                path=cookie_path(uid),
            )
            target_box = devbox_svc.devbox_manager.web_target(uid)
            if target_box is not None:
                # Dibaca JS klien VS Code utk jabat tangan WS (bukan HttpOnly, by design).
                resp.set_cookie(
                    key=devbox_svc._WEB_TOKEN_COOKIE,
                    value=target_box[2],
                    max_age=umur,
                    httponly=False,
                    secure=bool(settings.AUTH_COOKIE_SECURE),
                    samesite="lax",
                    path=cookie_path(uid),
                )
            return resp
    if request.headers.get("accept", "").startswith("text/html") or request.url.path.rstrip("/") == cookie_path(uid):
        return _html(
            401, "Sesi IDE tidak sah",
            "Buka VS Code lewat tombol <b>Buka VS Code di browser</b> pada menu Devbox "
            "ComputeHub. Tautan langsung tidak bisa dipakai tanpa masuk terlebih dahulu.",
        )
    return JSONResponse(status_code=401, content={"detail": "Sesi IDE devbox tidak sah."})


async def _proxy_http(request: Request, uid: int) -> Response:
    auth = await _authorize(request, uid)
    if isinstance(auth, Response):
        return auth
    target = devbox_svc.devbox_manager.web_target(uid)
    if target is None:
        return _html(
            503, "Devbox belum menyala",
            "VS Code di server belum siap. Nyalakan devbox dari menu Devbox lalu coba lagi.",
        )
    ip, port, token = target
    url = f"http://{ip}:{port}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    headers = build_upstream_headers(
        request.headers.items(), token, request.headers.get("host", ""),
        request.headers.get("x-forwarded-proto", request.url.scheme),
        request.client.host if request.client else "",
    )
    body = request.stream() if request.method not in ("GET", "HEAD", "OPTIONS") else None
    try:
        req = _http().build_request(request.method, url, headers=headers, content=body)
        upstream = await _http().send(req, stream=True)
    except httpx.HTTPError as exc:
        logger.warning("Proxy devbox #%d gagal ke %s: %s", uid, url, exc)
        return _html(502, "IDE tidak menjawab", "VS Code di server tidak menjawab. Coba muat ulang.")
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=dict(filter_response_headers(upstream.headers)),
        background=BackgroundTask(upstream.aclose),
    )


_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _mount(prefix: str) -> None:
    @router.api_route(prefix + "/{uid:int}", methods=_METHODS, include_in_schema=False)
    async def _root(request: Request, uid: int) -> Response:  # noqa: ANN001
        return await _proxy_http(request, uid)

    @router.api_route(prefix + "/{uid:int}/{path:path}", methods=_METHODS, include_in_schema=False)
    async def _sub(request: Request, uid: int, path: str) -> Response:  # noqa: ANN001
        return await _proxy_http(request, uid)

    @router.websocket(prefix + "/{uid:int}/{path:path}")
    async def _ws(websocket: WebSocket, uid: int, path: str) -> None:  # noqa: ANN001
        await _proxy_ws(websocket, uid)


async def _proxy_ws(websocket: WebSocket, uid: int) -> None:
    claims = verify_session_cookie(websocket.cookies.get(_COOKIE_NAME), uid)
    if claims is None or not await session_active(uid, claims["sid"]):
        await websocket.close(code=4401)
        return
    target = devbox_svc.devbox_manager.web_target(uid)
    if target is None:
        await websocket.close(code=4503)
        return
    ip, port, token = target
    url = f"ws://{ip}:{port}{websocket.url.path}"
    if websocket.url.query:
        url += f"?{websocket.url.query}"
    headers = [
        (k, v) for k, v in build_upstream_headers(
            websocket.headers.items(), token, websocket.headers.get("host", ""),
            websocket.headers.get("x-forwarded-proto", "https"),
            websocket.client.host if websocket.client else "",
        )
        if k.lower() not in {"sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions",
                             "sec-websocket-protocol", "origin"}
    ]
    protocols = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    try:
        upstream = await websockets.connect(
            url,
            additional_headers=headers,
            subprotocols=protocols or None,  # type: ignore[arg-type]
            max_size=None,
            ping_interval=None,
            open_timeout=20,
            compression=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Proxy WS devbox #%d gagal ke %s: %s", uid, url, exc)
        await websocket.close(code=4502)
        return
    await websocket.accept(subprotocol=upstream.subprotocol)

    async def ke_upstream() -> None:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                await upstream.send(msg["bytes"])
            elif msg.get("text") is not None:
                await upstream.send(msg["text"])

    async def ke_browser() -> None:
        async for data in upstream:
            if isinstance(data, (bytes, bytearray)):
                await websocket.send_bytes(bytes(data))
            else:
                await websocket.send_text(data)

    tasks = [asyncio.create_task(ke_upstream()), asyncio.create_task(ke_browser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect, websockets.ConnectionClosed):
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await upstream.close()
        except Exception:  # noqa: BLE001
            pass
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001
                pass


_mount("/" + (settings.DEVBOX_WEB_PATH or "/devbox-ide").strip("/"))
