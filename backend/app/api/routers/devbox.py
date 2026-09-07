"""Router devbox — ngoding di VS Code sendiri dengan sumber daya ComputeHub.

Alur dari sisi user:
  1. POST /devbox/start (opsional ?gpu=true) -> container disiapkan.
  2. GET  /devbox (polling) -> saat state "needs_login", tampilkan `device_code`
     agar user mengotorisasi di https://github.com/login/device.
  3. Setelah diotorisasi, state jadi "running" + `tunnel_url` (vscode.dev) siap dibuka;
     bisa juga disambung dari VS Code Desktop lewat nama tunnel.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.logging import get_logger
from app.models.user import User, UserRole
from app.services import maintenance as maintenance_svc
from app.services.devbox import DevboxError, devbox_manager

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
async def my_devbox(current_user: User = Depends(get_current_active_user)) -> dict:
    """Status devbox milik user yang login."""
    return await devbox_manager.status(current_user.id)


@router.post("/start")
async def start_devbox(
    gpu: bool | None = None,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Nyalakan devbox.

    Tanpa parameter = OTOMATIS: GPU diberikan bila masih ada kapasitas & kuota,
    selain itu devbox tetap menyala dengan CPU (tidak pernah gagal hanya karena
    GPU penuh). Parameter `gpu` hanya dipakai untuk memaksa salah satu mode.
    """
    if not settings.DEVBOX_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fitur devbox belum diaktifkan.",
        )
    if current_user.role != UserRole.admin:
        maint = maintenance_svc.state()
        if maint.active:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=maint.message
            )
    try:
        return await devbox_manager.ensure(current_user.id, want_gpu=gpu)
    except DevboxError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal menyalakan devbox user #%s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menyalakan devbox: {exc}",
        ) from exc


@router.post("/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_devbox(current_user: User = Depends(get_current_active_user)) -> None:
    """Matikan devbox (berkas & paket tetap tersimpan untuk sesi berikutnya)."""
    await devbox_manager.shutdown_user(current_user.id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_devbox(current_user: User = Depends(get_current_active_user)) -> None:
    """Hapus container devbox (setel ulang lingkungan; /persist TIDAK terhapus)."""
    await devbox_manager.shutdown_user(current_user.id, remove=True)


@router.get("/all")
async def list_devboxes(current_user: User = Depends(get_current_active_user)) -> list[dict]:
    """Daftar seluruh devbox aktif (admin)."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Khusus admin.")
    return devbox_manager.list_all()


@router.get("/disk")
async def devbox_disk(current_user: User = Depends(get_current_active_user)) -> dict:
    """Pemakaian disk HOME devbox per user (admin) — di luar kuota /persist."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Khusus admin.")
    return await run_in_threadpool(devbox_manager.disk_usage)


@router.post("/{user_id}/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_user_devbox(
    user_id: int,
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Matikan devbox milik user tertentu (admin)."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Khusus admin.")
    await devbox_manager.shutdown_user(user_id)
