"""API TensorBoard per pengguna (grafik eksperimen di web).

  GET  /tensorboard/status        -> TensorBoard user sedang menyala? (folder, sisa idle)
  GET  /tensorboard/runs          -> folder berisi log TensorBoard (sumber /persist / job)
  POST /tensorboard/start         -> nyalakan untuk folder pilihan + URL tiket sekali-pakai
  POST /tensorboard/ticket        -> URL tiket baru untuk TensorBoard yang sudah menyala
  POST /tensorboard/stop          -> matikan sekarang
Tampilan grafiknya sendiri di-proxy di /tensorboard/<uid>/ (routers/tensorboard_web.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_active_user, get_db
from app.api.routers import tensorboard_web
from app.models.job import Job
from app.models.user import User, UserRole
from app.services import tensorboard as tb_svc
from app.services.tensorboard import TensorboardError, tensorboard_manager

router = APIRouter()

Source = Literal["persist", "job"]


class StartBody(BaseModel):
    source: Source = "persist"
    job_id: int | None = None
    path: str = Field(default="", max_length=1024)


def _guard() -> None:
    if not tb_svc.enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fitur TensorBoard nonaktif.")


async def _resolve_base(
    source: str, job_id: int | None, session: AsyncSession, user: User
) -> tuple[Path, str]:
    """(folder akar sumber, kunci sumber) — hanya milik user (admin: job siapa pun)."""
    if source == "persist":
        return await run_in_threadpool(tb_svc.persist_base, user.id), "persist"
    if job_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="job_id wajib diisi.")
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job tidak ditemukan.")
    if user.role != UserRole.admin and job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bukan job Anda.")
    if not job.working_dir or not Path(job.working_dir).is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Folder job tidak ditemukan (belum dijalankan atau sudah dibersihkan otomatis).",
        )
    return Path(job.working_dir), f"job:{job.id}"


def _ticket_url(user: User) -> str:
    ticket = tensorboard_web.make_ticket(user.id, user.session_token or "")
    return f"{tb_svc.base_path(user.id)}?{tensorboard_web.TICKET_PARAM}={ticket}"


@router.get("/status")
async def tb_status(current_user: User = Depends(get_current_active_user)) -> dict:
    return tensorboard_manager.status(current_user.id)


@router.get("/runs")
async def tb_runs(
    source: Source = "persist",
    job_id: int | None = None,
    path: str = Query(default="", max_length=1024),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    _guard()
    base, key = await _resolve_base(source, job_id, session, current_user)
    try:
        rel = tb_svc.normalize_rel(path)
        hasil = await run_in_threadpool(tb_svc.find_runs, base, rel)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"source": key, "path": rel, **hasil}


@router.post("/start")
async def tb_start(
    body: StartBody,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    _guard()
    base, key = await _resolve_base(body.source, body.job_id, session, current_user)
    try:
        rel = tb_svc.normalize_rel(body.path)
        hasil = await run_in_threadpool(tb_svc.find_runs, base, rel)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not hasil["runs"]:
        lokasi = f"'{rel}'" if rel else "ini"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Belum ada log TensorBoard di folder {lokasi}. Tulis log dengan "
                "SummaryWriter / callback TensorBoard, lalu coba lagi."
            ),
        )
    try:
        info = await tensorboard_manager.ensure(current_user.id, base, key, rel)
    except TensorboardError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {**info, "ticket_url": _ticket_url(current_user)}


@router.post("/ticket")
async def tb_ticket(current_user: User = Depends(get_current_active_user)) -> dict:
    _guard()
    if tensorboard_manager.target(current_user.id) is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="TensorBoard belum menyala.")
    tensorboard_manager.touch(current_user.id)
    return {"ticket_url": _ticket_url(current_user)}


@router.post("/stop", status_code=status.HTTP_204_NO_CONTENT)
async def tb_stop(current_user: User = Depends(get_current_active_user)) -> None:
    await tensorboard_manager.shutdown(current_user.id)
