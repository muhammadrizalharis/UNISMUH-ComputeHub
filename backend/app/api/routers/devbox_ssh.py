"""Proxy Remote-SSH devbox: WebSocket di domain kampus <-> sshd di container.

Kenapa: VS Code Desktop yang memakai Remote Tunnel harus melewati relay Microsoft, dan
jalur kampus ke sana putus-nyambung (PMTU black hole). Remote-SSH jauh lebih ringan,
tetapi butuh jalur TCP ke server — sementara port SSH host TIDAK boleh (dan tidak bisa)
dibuka untuk mahasiswa. Jalan tengahnya: bungkus SSH di dalam WebSocket HTTPS yang lewat
pintu yang SUDAH terbukti sehat (domain kampus + nginx), lalu backend meneruskannya ke
sshd milik devbox user.

Laptop user memakai `ProxyCommand` (pembungkus WebSocket) yang dipasang otomatis oleh
pemasang sekali-klik, jadi pengguna tidak pernah menyentuh konfigurasi apa pun.

KEAMANAN:
  - WebSocket hanya terbuka bila membawa TOKEN AKSES SSH milik user (JWT ber-tipe khusus,
    umur DEVBOX_SSH_TOKEN_DAYS) DAN akun ComputeHub-nya masih aktif -> menonaktifkan akun
    memutus jalur ini juga.
  - Token terikat SIDIK JARI kunci yang sedang berlaku, BUKAN sesi login web: pemasang
    cukup dijalankan sekali dan tidak rusak saat user login/logout di browser.
  - Token hanya berlaku untuk devbox MILIKNYA (sub == uid di path).
  - Lapis kedua: sshd sendiri hanya menerima kunci publik yang diterbitkan ComputeHub.
  - Menerbitkan kunci baru mencabut yang lama SEKALIGUS membatalkan token lama
    (authorized_keys ditulis ulang + sidik jari berubah).
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import jwt
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.user import User
from app.services import devbox as devbox_svc
from app.services import devbox_keys

logger = get_logger(__name__)
router = APIRouter()

_TOKEN_TYPE = "devbox_ssh"


def make_token(user_id: int, kid: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(int(user_id)),
        "kid": kid,
        "type": _TOKEN_TYPE,
        "iat": now,
        "exp": now + dt.timedelta(days=max(1, int(settings.DEVBOX_SSH_TOKEN_DAYS))),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str | None, user_id: int) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != _TOKEN_TYPE or not payload.get("kid"):
        return None
    try:
        if int(payload["sub"]) != int(user_id):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    if payload["kid"] != devbox_keys.fingerprint(user_id):
        return None  # kunci sudah diterbitkan ulang -> token lama ikut mati
    return payload


async def _akun_aktif(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
    return bool(user and user.is_active)


def ssh_base_path(user_id: int) -> str:
    prefix = "/" + (settings.DEVBOX_SSH_PATH or "/devbox-ssh").strip("/")
    return f"{prefix}/{int(user_id)}"


async def _connect_sshd(user_id: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """Sambung ke sshd devbox; nyalakan devbox lebih dulu bila sedang mati."""
    target = devbox_svc.devbox_manager.ssh_target(user_id)
    if target is None and settings.DEVBOX_SSH_AUTOSTART:
        # "Buka VS Code lalu connect" harus cukup: koneksi SSH yang sah menyalakan devbox.
        try:
            await devbox_svc.devbox_manager.ensure(user_id)
        except devbox_svc.DevboxError as exc:
            logger.info("Devbox #%d tidak bisa dinyalakan lewat SSH: %s", user_id, exc)
            return None
        for _ in range(int(settings.DEVBOX_START_TIMEOUT_SECONDS) // 2):
            await asyncio.sleep(2.0)
            target = devbox_svc.devbox_manager.ssh_target(user_id)
            if target is not None:
                break
    if target is None:
        return None
    ip, port = target
    try:
        return await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=15.0)
    except (OSError, asyncio.TimeoutError) as exc:
        logger.warning("Devbox #%d: sshd %s:%s tak terjangkau: %s", user_id, ip, port, exc)
        return None


@router.websocket("/{uid:int}")
async def ssh_ws(websocket: WebSocket, uid: int) -> None:
    claims = verify_token(websocket.query_params.get("token"), uid)
    if claims is None or not await _akun_aktif(uid):
        await websocket.close(code=4401)
        return
    conn = await _connect_sshd(uid)
    if conn is None:
        await websocket.close(code=4503)
        return
    reader, writer = conn
    await websocket.accept()

    async def ke_sshd() -> None:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data is None and msg.get("text") is not None:
                data = msg["text"].encode()
            if data:
                writer.write(data)
                await writer.drain()

    async def ke_klien() -> None:
        while True:
            data = await reader.read(65536)
            if not data:
                return
            await websocket.send_bytes(data)

    tasks = [asyncio.create_task(ke_sshd()), asyncio.create_task(ke_klien())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, asyncio.TimeoutError):
            pass
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001
                pass
