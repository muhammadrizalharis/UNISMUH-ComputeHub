"""Router sesi INTERAKTIF (notebook/console ala Colab) — REST + WebSocket.

REST  : buat / lihat / interrupt / restart / hapus sesi kernel.
WS    : `/ws/{session_id}?token=<JWT>` -> kirim {type:'execute',cell_id,code},
        terima streaming output (stream/result/error/status/execute_reply).
"""

from __future__ import annotations

import asyncio
import contextlib
import io

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.websockets import WebSocketState

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.models.user import User
from app.services.interactive import SessionQueued, kernel_manager

logger = get_logger(__name__)
router = APIRouter()


class CloneRequest(BaseModel):
    url: str
    ref: str | None = None


class PushRequest(BaseModel):
    message: str = ""
    token: str


def _require_session(session_id: str, user: User):
    sess = kernel_manager.get(session_id, user.id)
    if sess is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sesi tidak ditemukan."
        )
    return sess


# ------------------------------------------------------------------ REST
@router.post("/sessions")
async def create_session(
    response: Response,
    source: str = "paste",
    ticket_id: str | None = None,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Buat/lanjutkan sesi interaktif.

    Bila semua kapasitas GPU terpakai, user MASUK ANTRIAN: balasan 202 berisi
    {queued, ticket_id, position, eta_seconds}. Frontend memantau /queue lalu
    memanggil ulang dgn ticket_id saat giliran tiba (auto-mulai).
    """
    if not settings.INTERACTIVE_ENABLED:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Sesi interaktif dinonaktifkan.")
    try:
        sess = await kernel_manager.create(
            current_user.id, source=source, ticket_id=ticket_id
        )
    except SessionQueued as q:
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "queued": True,
            "ticket_id": q.ticket_id,
            "position": q.position,
            "eta_seconds": q.eta_seconds,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal membuat sesi interaktif: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal memulai kernel: {exc}",
        )
    return sess.info()


@router.get("/queue")
async def queue_status(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Status antrian sesi interaktif user (dipantau frontend saat menunggu)."""
    return kernel_manager.queue_status(current_user.id)


@router.post("/queue/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_queue(
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Keluar dari antrian (mis. user menutup halaman / membatalkan)."""
    kernel_manager.leave_queue(current_user.id)


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_active_user),
) -> list[dict]:
    return kernel_manager.list_for(current_user.id)


@router.post("/sessions/shutdown-mine", status_code=status.HTTP_204_NO_CONTENT)
async def shutdown_my_sessions(
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Hentikan semua sesi interaktif milik user ini (dipanggil saat logout)."""
    await kernel_manager.drop_user_sessions(current_user.id)


@router.post("/sessions/{session_id}/interrupt")
async def interrupt_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    sess = kernel_manager.get(session_id, current_user.id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesi tidak ditemukan.")
    await sess.interrupt()
    return {"ok": True}


@router.post("/sessions/{session_id}/restart")
async def restart_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    sess = kernel_manager.get(session_id, current_user.id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesi tidak ditemukan.")
    await sess.restart()
    return sess.info()


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
) -> None:
    await kernel_manager.shutdown_session(session_id, current_user.id)


# ----------------------------------------------------- project (zip / github)
@router.post("/sessions/{session_id}/upload")
async def upload_project(
    session_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Unggah .zip -> ekstrak ke workdir kernel + kembalikan file tree."""
    sess = _require_session(session_id, current_user)
    data = await file.read()
    try:
        tree = await sess.load_zip(data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal memuat zip sesi %s: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal memuat project: {exc}",
        )
    return {"tree": tree}


@router.post("/sessions/{session_id}/clone")
async def clone_project(
    session_id: str,
    body: CloneRequest,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Clone repo GitHub -> ke workdir kernel + kembalikan file tree."""
    sess = _require_session(session_id, current_user)
    try:
        tree = await sess.load_git(body.url, body.ref)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal clone repo sesi %s: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal clone repo: {exc}",
        )
    return {"tree": tree}


@router.get("/sessions/{session_id}/files")
async def list_files(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    sess = _require_session(session_id, current_user)
    return {"tree": sess.file_tree()}


@router.get("/sessions/{session_id}/file")
async def read_file(
    session_id: str,
    path: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    sess = _require_session(session_id, current_user)
    try:
        return sess.read_text_file(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/sessions/{session_id}/download")
async def download_project(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """Unduh seluruh folder project sesi (zip/github) sebagai .zip."""
    sess = _require_session(session_id, current_user)
    try:
        name, data = await sess.zip_project()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal zip project sesi %s: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal menyiapkan unduhan project.",
        )
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/sessions/{session_id}/push")
async def push_project(
    session_id: str,
    body: PushRequest,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Commit & push perubahan ke GitHub (khusus sesi yang di-clone dari repo).
    Token dikirim sekali per-request, TIDAK disimpan."""
    sess = _require_session(session_id, current_user)
    try:
        return await sess.git_push(
            body.message, body.token, current_user.name, current_user.email
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal push sesi %s: %s", session_id, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal push (kesalahan internal).",
        )


# ------------------------------------------------------------------ WebSocket
async def _ws_authenticate(websocket: WebSocket) -> User | None:
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        uid = payload.get("sub")
        if uid is None:
            return None
    except Exception:  # noqa: BLE001
        return None
    async with AsyncSessionLocal() as db:
        user = await db.get(User, int(uid))
    if user is None or not user.is_active:
        return None
    return user


@router.websocket("/ws/{session_id}")
async def ws_execute(websocket: WebSocket, session_id: str) -> None:
    user = await _ws_authenticate(websocket)
    if user is None:
        await websocket.close(code=4401)  # unauthorized
        return
    sess = kernel_manager.get(session_id, user.id)
    if sess is None:
        await websocket.close(code=4404)  # session tidak ada
        return

    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(message: dict) -> None:
        if websocket.client_state != WebSocketState.CONNECTED:
            return
        async with send_lock:
            if websocket.client_state != WebSocketState.CONNECTED:
                return
            try:
                await websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                # Klien menutup koneksi saat sel masih mengirim output -> abaikan.
                pass

    async def run_cell(cell_id: str | None, code: str) -> None:
        await send({"type": "status", "state": "busy", "cell_id": cell_id})

        async def on_msg(m: dict) -> None:
            await send({**m, "cell_id": cell_id})

        try:
            result = await sess.execute(code, on_msg)
            await send({"type": "execute_reply", "cell_id": cell_id, **result})
        except Exception as exc:  # noqa: BLE001
            await send({
                "type": "error", "cell_id": cell_id,
                "ename": type(exc).__name__, "evalue": str(exc), "traceback": [],
            })
        finally:
            await send({"type": "status", "state": "idle", "cell_id": cell_id})

    exec_task: asyncio.Task | None = None
    try:
        await send({"type": "ready", **sess.info()})
        while True:
            raw = await websocket.receive_json()
            mtype = raw.get("type")
            if mtype == "execute":
                if exec_task is not None and not exec_task.done():
                    await send({
                        "type": "error", "cell_id": raw.get("cell_id"),
                        "ename": "Busy", "evalue": "Kernel sedang menjalankan sel lain.",
                        "traceback": [],
                    })
                    continue
                exec_task = asyncio.create_task(
                    run_cell(raw.get("cell_id"), raw.get("code", ""))
                )
            elif mtype == "interrupt":
                await sess.interrupt()
                await send({"type": "interrupted"})
            elif mtype == "ping":
                await send({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("WS interaktif error (sesi %s): %s", session_id, exc)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        # Klien sudah pergi -> batalkan eksekusi sel yatim agar tidak mencoba
        # mengirim ke socket tertutup ("Task exception was never retrieved").
        if exec_task is not None and not exec_task.done():
            exec_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await exec_task
