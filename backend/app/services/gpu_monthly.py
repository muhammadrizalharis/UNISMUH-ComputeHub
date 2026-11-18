"""Laporan jam GPU bulanan per pengguna (untuk pimpinan / admin).

Aturan hitung SAMA dengan kuota GPU harian (services/quota.py): hanya job yang
memegang GPU, punya durasi tercatat, dan (bila GPU_COUNT_ACTUAL_USAGE aktif)
benar-benar memakai VRAM. Job dimasukkan ke bulan saat ia SELESAI, menurut zona
waktu laporan (WITA).
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.job import Job
from app.models.user import User
from app.services.quota import _actual_usage_filter

DEVBOX_JOB_NAME = "Devbox VS Code"  # sama dengan services/devbox.DEVBOX_JOB_NAME

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _tz() -> dt.tzinfo:
    try:
        return ZoneInfo(settings.REPORT_TIMEZONE or "UTC")
    except Exception:  # noqa: BLE001
        return dt.timezone.utc


def current_month() -> str:
    return dt.datetime.now(_tz()).strftime("%Y-%m")


def month_range(month: str) -> tuple[dt.datetime, dt.datetime]:
    """'YYYY-MM' -> (awal, akhir) dalam UTC; akhir eksklusif. ValueError bila salah."""
    m = _MONTH_RE.match(month or "")
    if not m:
        raise ValueError("Format bulan harus YYYY-MM.")
    year, mon = int(m.group(1)), int(m.group(2))
    if not 1 <= mon <= 12 or not 2000 <= year <= 2100:
        raise ValueError("Bulan tidak valid.")
    tz = _tz()
    start = dt.datetime(year, mon, 1, tzinfo=tz)
    end = dt.datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=tz)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def _kind(name: str | None, is_interactive: bool) -> str:
    if name == DEVBOX_JOB_NAME:
        return "devbox"
    return "interactive" if is_interactive else "batch"


async def summary(session: AsyncSession, month: str) -> dict:
    start, end = month_range(month)
    rows = (
        await session.execute(
            select(
                Job.user_id,
                Job.name,
                Job.is_interactive,
                func.count(Job.id),
                func.coalesce(func.sum(Job.actual_runtime_seconds), 0.0),
                func.max(func.coalesce(Job.peak_vram_mb, 0.0)),
            )
            .where(
                Job.finished_at >= start,
                Job.finished_at < end,
                Job.actual_runtime_seconds.is_not(None),
                Job.gpu_index.is_not(None),
                *_actual_usage_filter(),
            )
            .group_by(Job.user_id, Job.name, Job.is_interactive)
        )
    ).all()

    per_user: dict[int, dict] = {}
    for user_id, name, is_interactive, count, secs, peak in rows:
        u = per_user.setdefault(
            user_id,
            {"user_id": user_id, "sessions": 0, "gpu_seconds": 0.0, "batch_seconds": 0.0,
             "interactive_seconds": 0.0, "devbox_seconds": 0.0, "peak_vram_mb": 0.0},
        )
        secs = float(secs or 0.0)
        u["sessions"] += int(count or 0)
        u["gpu_seconds"] += secs
        u[f"{_kind(name, bool(is_interactive))}_seconds"] += secs
        u["peak_vram_mb"] = max(u["peak_vram_mb"], float(peak or 0.0))

    if per_user:
        users = (
            await session.execute(
                select(User.id, User.username, User.name, User.email, User.role).where(
                    User.id.in_(per_user.keys())
                )
            )
        ).all()
        for uid, username, name, email, role in users:
            per_user[uid].update(
                username=username or "",
                name=name or "",
                email=email or "",
                role=getattr(role, "value", str(role)),
            )
    out = []
    for u in per_user.values():
        u.setdefault("username", "")
        u.setdefault("name", "(akun terhapus)")
        u.setdefault("email", "")
        u.setdefault("role", "")
        for k in ("gpu_seconds", "batch_seconds", "interactive_seconds", "devbox_seconds"):
            u[k] = round(u[k], 1)
        out.append(u)
    out.sort(key=lambda r: r["gpu_seconds"], reverse=True)

    by_role: dict[str, dict] = {}
    for u in out:
        r = by_role.setdefault(u["role"] or "-", {"role": u["role"] or "-", "users": 0, "gpu_seconds": 0.0})
        r["users"] += 1
        r["gpu_seconds"] = round(r["gpu_seconds"] + u["gpu_seconds"], 1)

    return {
        "month": month,
        "timezone": settings.REPORT_TIMEZONE,
        "total_gpu_seconds": round(sum(u["gpu_seconds"] for u in out), 1),
        "users": out,
        "by_role": sorted(by_role.values(), key=lambda r: r["gpu_seconds"], reverse=True),
    }


CSV_COLUMNS = [
    "bulan", "username", "nama", "email", "peran", "sesi", "jam_gpu",
    "jam_batch", "jam_notebook", "jam_devbox", "puncak_vram_mb",
]


def csv_rows(data: dict) -> list[dict]:
    jam = lambda s: f"{s / 3600:.2f}"  # noqa: E731
    return [
        {
            "bulan": data["month"], "username": u["username"], "nama": u["name"],
            "email": u["email"], "peran": u["role"], "sesi": u["sessions"],
            "jam_gpu": jam(u["gpu_seconds"]), "jam_batch": jam(u["batch_seconds"]),
            "jam_notebook": jam(u["interactive_seconds"]), "jam_devbox": jam(u["devbox_seconds"]),
            "puncak_vram_mb": round(u["peak_vram_mb"]),
        }
        for u in data["users"]
    ]
