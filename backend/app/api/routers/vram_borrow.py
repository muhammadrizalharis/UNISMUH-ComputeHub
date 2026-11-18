"""API pinjam VRAM kantong untuk container project peminjam (tanpa kunci).

Pemanggil dikenali dari IP container Docker-nya (koneksi langsung ke host; permintaan
lewat proxy publik ditolak agar IP tidak bisa dipalsukan) -> project compose. Hanya
project yang didaftarkan super admin sebagai peminjam yang dilayani.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.services import container_identity
from app.services import ollama_gateway as gw
from app.services import vram_borrow

router = APIRouter()


class BorrowIn(BaseModel):
    mb: float = Field(gt=0, le=90112, description="VRAM yang dipinjam di muka (MB)")
    gpu: int | None = Field(default=None, ge=0, description="GPU tertentu (opsional)")


class ReturnIn(BaseModel):
    lease_id: str | None = None


async def _caller(request: Request) -> tuple[str, str]:
    ip = gw.devbox_peer_ip(request.client.host if request.client else None, request.headers)
    meta = await asyncio.to_thread(container_identity.for_ip, ip or "")
    project = (meta or {}).get("project", "")
    if not project:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Pemanggil bukan container Docker Compose yang dikenali (panggil langsung dari container).",
        )
    if project not in await asyncio.to_thread(vram_borrow.get_projects):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Project '{project}' belum didaftarkan sebagai peminjam cadangan VRAM (computehub-devbox).",
        )
    return project, meta.get("name", "") or project


@router.get("/borrow")
async def borrow_status(request: Request) -> dict:
    """Status pinjaman & pemakaian VRAM project pemanggil."""
    project, _ = await _caller(request)
    st = await asyncio.to_thread(vram_borrow.status, project)
    return {"project": project, **(st["projects"][0] if st["projects"] else {})}


@router.post("/borrow")
async def borrow(payload: BorrowIn, request: Request) -> dict:
    """Pinjam VRAM di muka sebelum memuat model. Tanpa batas waktu."""
    from app.services import vram_pocket

    project, name = await _caller(request)
    try:
        lease = await asyncio.to_thread(
            vram_borrow.borrow, project, payload.mb, payload.gpu, name
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    cfg = await asyncio.to_thread(vram_pocket.get_config)
    return {
        "lease_id": lease.id,
        "project": project,
        "gpu": lease.gpu_index,
        "mb": lease.mb,
        "pocket_enabled": cfg.enabled,
        "catatan": (
            "Pinjaman kembali ke cadangan saat dikembalikan, atau otomatis "
            f"{int(vram_borrow.IDLE_RETURN_SECONDS)} detik setelah GPU project ini diam."
        ),
    }


@router.post("/return")
async def give_back(request: Request, payload: ReturnIn | None = None) -> dict:
    """Kembalikan pinjaman (satu lease_id, atau semua milik project pemanggil)."""
    project, _ = await _caller(request)
    n = await asyncio.to_thread(
        vram_borrow.give_back, project, payload.lease_id if payload else None
    )
    return {"project": project, "dikembalikan": n}
