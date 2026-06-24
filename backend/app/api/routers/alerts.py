"""Router admin: peringatan (alert) batas resource + email PDF."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.alert import Alert
from app.models.user import User
from app.schemas.alert import (
    AlertConfigOut,
    AlertConfigUpdate,
    AlertOut,
    AlertRunResult,
    EmailTestResult,
)
from app.services import alerts as alerts_svc
from app.services import email as email_svc

router = APIRouter()


async def _config_payload(session: AsyncSession) -> dict:
    cfg = await alerts_svc.get_config(session)
    recipients = await alerts_svc._recipients(session, cfg)
    return {
        "enabled": cfg.enabled,
        "cpu_cores": cfg.cpu_cores,
        "ram_gb": cfg.ram_gb,
        "vram_gb": cfg.vram_gb,
        "disk_percent": cfg.disk_percent,
        "cooldown_minutes": cfg.cooldown_minutes,
        "email_on_breach": cfg.email_on_breach,
        "email_to": cfg.email_to or "",
        "updated_at": cfg.updated_at,
        "smtp_configured": settings.smtp_configured,
        "smtp_from": settings.SMTP_FROM or settings.SMTP_USERNAME or "",
        "recipients": recipients,
    }


@router.get("/config", response_model=AlertConfigOut)
async def get_config(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    return await _config_payload(session)


@router.patch("/config", response_model=AlertConfigOut)
async def update_config(
    payload: AlertConfigUpdate,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    cfg = await alerts_svc.get_config(session)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(cfg, key, value)
    await session.commit()
    return await _config_payload(session)


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[Alert]:
    rows = await session.scalars(
        select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    )
    return list(rows.all())


@router.post("/run", response_model=AlertRunResult)
async def run_now(
    ignore_cooldown: bool = Query(default=True),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Evaluasi ambang SEKARANG (abaikan cooldown) — buat alert bila ada pelanggaran."""
    created = await alerts_svc.process(session, ignore_cooldown=ignore_cooldown)
    return {
        "created": len(created),
        "smtp_configured": settings.smtp_configured,
        "alerts": created,
    }


@router.post("/test-email", response_model=EmailTestResult)
async def test_email(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Kirim email uji ke penerima untuk memverifikasi konfigurasi SMTP."""
    cfg = await alerts_svc.get_config(session)
    recipients = await alerts_svc._recipients(session, cfg)
    if not settings.smtp_configured:
        return {"ok": False, "recipients": recipients, "detail": "SMTP belum dikonfigurasi (set SMTP_HOST di .env)."}
    if not recipients:
        return {"ok": False, "recipients": [], "detail": "Belum ada penerima (atur email_to atau akun admin)."}
    try:
        await asyncio.to_thread(
            email_svc.send_email,
            recipients,
            "[ComputeHub] Email uji peringatan",
            "Ini email uji dari UNISMUH ComputeHub. SMTP berfungsi dengan baik.",
            None,
        )
        return {"ok": True, "recipients": recipients, "detail": "Email uji terkirim."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "recipients": recipients, "detail": str(exc)[:300]}


@router.post("/user/{username}/send", response_model=AlertOut)
async def send_user_report(
    username: str,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Alert:
    """Buat & kirim laporan PDF penggunaan user secara manual (on-demand)."""
    return await alerts_svc.send_user_alert(session, username)


@router.get("/{alert_id}/pdf")
async def download_alert_pdf(
    alert_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> FileResponse:
    """Unduh PDF yang dilampirkan pada sebuah peringatan."""
    alert = await session.get(Alert, alert_id)
    if alert is None or not alert.pdf_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF peringatan tidak tersedia.")
    path = Path(alert.pdf_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Berkas PDF sudah tidak ada.")
    return FileResponse(str(path), filename=path.name, media_type="application/pdf")
