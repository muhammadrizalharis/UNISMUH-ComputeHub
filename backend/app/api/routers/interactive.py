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
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.websockets import WebSocketState

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.models.user import User
from app.services.interactive import SessionQueued, kernel_manager
from app.services import workspace as workspace_svc
from app.services import user_policy as user_policy_svc

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


# ----------------------------------------------- Workspace persisten (/persist)
async def _storage_quota_mb(user_id: int) -> float:
    """Kuota penyimpanan efektif user (MB); 0 = tanpa batas."""
    async with AsyncSessionLocal() as db:
        eff = await user_policy_svc.effective(db, user_id)
        return float(getattr(eff, "max_storage_mb", 0.0) or 0.0)


class WorkspaceSave(BaseModel):
    path: str
    content: str


@router.get("/workspace")
async def workspace_overview(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Pohon file + ringkas pemakaian + kuota penyimpanan workspace persisten user."""
    return {
        "tree": workspace_svc.tree(current_user.id),
        "usage": workspace_svc.usage(current_user.id),
        "quota_mb": await _storage_quota_mb(current_user.id),
    }


@router.get("/workspace/file")
async def workspace_read(
    path: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Baca isi file teks di workspace user (untuk ditampilkan di editor)."""
    try:
        return workspace_svc.read_text(current_user.id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.put("/workspace/file")
async def workspace_save(
    body: WorkspaceSave,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Simpan/timpa file teks (mis. notebook .ipynb) ke workspace persisten user."""
    try:
        return workspace_svc.save_text(current_user.id, body.path, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/workspace/file", status_code=status.HTTP_204_NO_CONTENT)
async def workspace_delete(
    path: str,
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Hapus file/folder di workspace user."""
    try:
        workspace_svc.delete(current_user.id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/workspace/download")
async def workspace_download(
    path: str,
    current_user: User = Depends(get_current_active_user),
) -> FileResponse:
    """Unduh satu file dari workspace user (stream dari disk)."""
    try:
        name, target = workspace_svc.resolve_file(current_user.id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return FileResponse(
        str(target), filename=name, media_type="application/octet-stream"
    )


@router.get("/workspace/download-folder")
async def workspace_download_folder(
    path: str = "",
    current_user: User = Depends(get_current_active_user),
) -> FileResponse:
    """Unduh sebuah folder (atau SELURUH workspace bila `path` kosong) sebagai arsip .zip."""
    try:
        name, tmp = workspace_svc.zip_dir(current_user.id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal zip folder workspace user %s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal menyiapkan unduhan folder.",
        )
    return FileResponse(
        str(tmp),
        filename=name,
        media_type="application/zip",
        background=BackgroundTask(workspace_svc.cleanup_temp, tmp),
    )


@router.post("/workspace/upload")
async def workspace_upload(
    file: UploadFile = File(...),
    dir: str = "",
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Unggah satu file ke workspace persisten user (stream ke disk, batas ukuran)."""
    import os as _os

    try:
        target, rel = workspace_svc.prepare_upload_target(
            current_user.id, dir, file.filename or "file"
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    # Kuota penyimpanan per-user (0 = tanpa batas) — ditegakkan saat unggah.
    quota_mb = await _storage_quota_mb(current_user.id)
    quota_bytes = int(quota_mb * 1024 * 1024) if quota_mb > 0 else 0
    used_before = workspace_svc.usage(current_user.id)["bytes"] if quota_bytes else 0
    size = 0
    try:
        with open(target, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > workspace_svc.MAX_UPLOAD_BYTES:
                    out.close()
                    _os.remove(target)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File terlalu besar (maks {workspace_svc.MAX_UPLOAD_BYTES // 1024 // 1024} MB).",
                    )
                if quota_bytes and used_before + size > quota_bytes:
                    out.close()
                    _os.remove(target)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Kuota penyimpanan {quota_mb:.0f} MB terlampaui "
                            f"(terpakai {used_before / 1024 / 1024:.0f} MB)."
                        ),
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        try:
            _os.remove(target)
        except OSError:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menyimpan unggahan: {exc}",
        )
    finally:
        await file.close()
    return {"path": rel, "size": size}


# ------------------------------------------------------------------ WebSocket
async def _ws_authenticate(websocket: WebSocket) -> User | None:
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        uid = payload.get("sub")
        sid = payload.get("sid")
        if uid is None:
            return None
    except Exception:  # noqa: BLE001
        return None
    async with AsyncSessionLocal() as db:
        user = await db.get(User, int(uid))
    # Sesi tunggal: token harus cocok dengan sesi aktif user (sid).
    if user is None or not user.is_active or not sid or user.session_token != sid:
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
