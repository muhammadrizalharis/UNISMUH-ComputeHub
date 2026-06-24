"""Skema peringatan (alert) batas resource."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class AlertConfigOut(BaseModel):
    enabled: bool
    cpu_cores: float
    ram_gb: float
    vram_gb: float
    disk_percent: float
    cooldown_minutes: int
    email_on_breach: bool
    email_to: str
    updated_at: dt.datetime | None = None
    # info turunan
    smtp_configured: bool = False
    smtp_from: str = ""
    recipients: list[str] = []


class AlertConfigUpdate(BaseModel):
    enabled: bool | None = None
    cpu_cores: float | None = Field(default=None, ge=0)
    ram_gb: float | None = Field(default=None, ge=0)
    vram_gb: float | None = Field(default=None, ge=0)
    disk_percent: float | None = Field(default=None, ge=0, le=100)
    cooldown_minutes: int | None = Field(default=None, ge=0)
    email_on_breach: bool | None = None
    email_to: str | None = None


class AlertOut(BaseModel):
    id: int
    created_at: dt.datetime
    scope: str
    subject: str
    metric: str
    value: float
    threshold: float
    message: str
    emailed: bool
    email_error: str | None = None
    pdf_path: str | None = None

    class Config:
        from_attributes = True


class AlertRunResult(BaseModel):
    created: int
    smtp_configured: bool
    alerts: list[AlertOut]


class EmailTestResult(BaseModel):
    ok: bool
    recipients: list[str]
    detail: str = ""
