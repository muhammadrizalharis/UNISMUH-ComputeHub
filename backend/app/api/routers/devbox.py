"""Router devbox — ngoding di VS Code sendiri dengan sumber daya ComputeHub.

Alur dari sisi user:
  1. POST /devbox/start (opsional ?gpu=true) -> container + VS Code web disiapkan.
  2. GET  /devbox (polling) -> state "running" + `web_url` (path IDE di domain kampus).
  3. POST /devbox/web-ticket -> URL sekali-pakai untuk membuka IDE di tab baru
     (ditukar proxy menjadi cookie sesi IDE; lihat routers/devbox_web.py).
  Opsional (VS Code Desktop): POST /devbox/tunnel/start -> `tunnel_state` needs_login
  (tampilkan `device_code` utk github.com/login/device) -> running + `tunnel_url`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_active_user
from app.api.routers import devbox_ssh, devbox_web
from app.core.config import settings
from app.core.logging import get_logger
from app.models.user import User, UserRole
from app.services import devbox_keys, devbox_setup
from app.services import maintenance as maintenance_svc
from app.services.devbox import (
    DevboxError,
    devbox_manager,
    folder_label,
    ssh_enabled,
    ssh_host_alias,
    web_base_path,
    web_enabled,
)

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
async def my_devbox(current_user: User = Depends(get_current_active_user)) -> dict:
    """Status devbox milik user yang login."""
    return await devbox_manager.status(current_user.id)


@router.post("/web-ticket")
async def devbox_web_ticket(current_user: User = Depends(get_current_active_user)) -> dict:
    """URL sekali-pakai (umur DEVBOX_WEB_TICKET_SECONDS) untuk membuka IDE di browser.

    Tab IDE tidak membawa header Authorization, jadi tiket inilah yang ditukar proxy
    menjadi cookie sesi HttpOnly ber-path /devbox-ide/<uid>. Hanya bila devbox running.
    """
    if not web_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jalur IDE web nonaktif.")
    if devbox_manager.web_target(current_user.id) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Devbox belum menyala / VS Code di server belum siap.",
        )
    ticket = devbox_web.make_ticket(current_user.id, current_user.session_token or "")
    base = web_base_path(current_user.id)
    return {"url": f"{base}?{devbox_web._TICKET_PARAM}={ticket}", "path": base}


@router.post("/tunnel/start")
async def start_tunnel(current_user: User = Depends(get_current_active_user)) -> dict:
    """Siapkan tunnel Microsoft (VS Code Desktop) untuk devbox yang sudah menyala."""
    try:
        return await devbox_manager.start_tunnel(current_user.id)
    except DevboxError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _setup_guard(current_user: User) -> None:
    if not ssh_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Jalur VS Code Desktop (SSH) nonaktif."
        )
    if not current_user.session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesi tidak sah.")


@router.get("/desktop-setup")
async def desktop_setup(
    os_name: str = "windows",
    current_user: User = Depends(get_current_active_user),
):
    """Pemasang sekali-klik VS Code Desktop (berisi kunci privat user + konfigurasi).

    BUKAN berkas statis: dibuat di memori untuk pemilik yang sedang login, tidak
    di-cache, dan tidak pernah bisa diambil user lain.
    """
    _setup_guard(current_user)
    uid = int(current_user.id)
    alias = ssh_host_alias(uid)
    private = await run_in_threadpool(devbox_keys.read_private, uid)
    if private is None:
        private, _ = await run_in_threadpool(devbox_keys.generate, uid)
    token = devbox_ssh.make_token(uid, await run_in_threadpool(devbox_keys.fingerprint, uid))
    folder = folder_label(current_user.name, current_user.username, uid)
    windows = (os_name or "windows").lower().startswith("win")
    isi = (
        devbox_setup.build_windows(uid, alias, private, token, folder)
        if windows
        else devbox_setup.build_unix(uid, alias, private, token, folder)
    )
    nama = f"{alias}-setup." + ("ps1" if windows else "sh")
    return PlainTextResponse(
        isi,
        headers={
            "Content-Disposition": f'attachment; filename="{nama}"',
            "Cache-Control": "no-store",
        },
        media_type="application/octet-stream",
    )


@router.post("/desktop-key/rotate", status_code=status.HTTP_204_NO_CONTENT)
async def rotate_desktop_key(current_user: User = Depends(get_current_active_user)) -> None:
    """Terbitkan kunci SSH baru: laptop lama langsung kehilangan akses.

    Dipakai bila laptop hilang/dipinjam. Devbox yang sedang menyala memasang kunci baru
    seketika; bila mati, dipasang saat dinyalakan lagi.
    """
    _setup_guard(current_user)
    await run_in_threadpool(devbox_keys.generate, current_user.id)
    await devbox_manager.refresh_ssh_key(current_user.id)


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
    await devbox_manager.shutdown_user(current_user.id, alasan="dihentikan oleh pemilik")


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_devbox(current_user: User = Depends(get_current_active_user)) -> None:
    """Hapus container devbox (setel ulang lingkungan; /persist TIDAK terhapus)."""
    await devbox_manager.shutdown_user(
        current_user.id, remove=True, alasan="direset oleh pemilik (container dihapus)"
    )


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
    await devbox_manager.shutdown_user(
        user_id,
        alasan=(
            f"dihentikan oleh admin id={current_user.id} "
            f"({current_user.username or current_user.email})"
        ),
    )
