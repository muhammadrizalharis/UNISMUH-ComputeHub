#!/usr/bin/env python3
"""Laporan penggunaan BULANAN (PDF) -> email ke semua admin + super admin.

Dijalankan systemd timer tiap tanggal 1 (merangkum bulan sebelumnya).
Jalankan manual:
  cd backend && PYTHONPATH=. .venv/bin/python ../scripts/monthly_report.py [YYYY-MM]
Best-effort: kegagalan apa pun hanya tercatat di stdout (exit 0).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys

from sqlalchemy import case, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobDevice, JobStatus
from app.models.user import User, UserRole
from app.services import email as email_svc


def _period(arg: str | None) -> tuple[dt.datetime, dt.datetime, str]:
    """Rentang [awal, akhir) bulan target. Default = bulan LALU."""
    if arg:
        y, m = map(int, arg.split("-"))
        start = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    else:
        now = dt.datetime.now(dt.timezone.utc)
        first_this = dt.datetime(now.year, now.month, 1, tzinfo=dt.timezone.utc)
        start = (first_this - dt.timedelta(days=1)).replace(day=1)
    end = (start + dt.timedelta(days=32)).replace(day=1)
    label = start.strftime("%B %Y")
    return start, end, label


def _fmt_jam(seconds: float) -> str:
    h = seconds / 3600
    return f"{h:.1f} jam" if h >= 0.1 else f"{int(seconds)} dtk"


def _san(s: str) -> str:
    return (s or "").encode("latin-1", "replace").decode("latin-1")


def _build_pdf(label: str, rows: list, totals: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_fill_color(31, 102, 242)
    pdf.rect(0, 0, 210, 22, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 14)
    pdf.set_xy(10, 6)
    pdf.cell(0, 8, _san(f"UNISMUH ComputeHub - Laporan Penggunaan {label}"))
    pdf.set_text_color(30, 41, 59)
    pdf.set_xy(10, 28)

    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 8, "Ringkasan Platform", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    for line in (
        f"Total job selesai   : {totals['jobs']} (gagal {totals['failed']})",
        f"Total waktu GPU     : {_fmt_jam(totals['gpu_seconds'])}",
        f"Pengguna aktif      : {totals['users']}",
    ):
        pdf.cell(0, 6, _san(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 8, "Rincian per Pengguna (urut waktu GPU)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "B", 9)
    widths = (62, 24, 16, 16, 32)
    for w, h in zip(widths, ("Nama", "Peran", "Job", "Gagal", "Waktu GPU")):
        pdf.cell(w, 7, _san(h), border=1)
    pdf.ln()
    pdf.set_font("helvetica", "", 9)
    for name, role, jobs, failed, gpu_s in rows[:40]:
        pdf.cell(widths[0], 6, _san((name or "-")[:38]), border=1)
        pdf.cell(widths[1], 6, _san(role), border=1)
        pdf.cell(widths[2], 6, str(jobs), border=1, align="R")
        pdf.cell(widths[3], 6, str(failed), border=1, align="R")
        pdf.cell(widths[4], 6, _san(_fmt_jam(gpu_s)), border=1, align="R")
        pdf.ln()
    if not rows:
        pdf.cell(0, 6, _san("(tidak ada aktivitas pada periode ini)"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("helvetica", "I", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 5, _san(
        f"Dibuat otomatis {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} - "
        f"{settings.public_base_url or 'ComputeHub'}"
    ))
    return bytes(pdf.output())


async def main() -> None:
    start, end, label = _period(sys.argv[1] if len(sys.argv) > 1 else None)
    async with AsyncSessionLocal() as session:
        gpu_seconds = func.coalesce(
            func.sum(
                case(
                    (Job.device == JobDevice.gpu, Job.actual_runtime_seconds),
                    else_=0.0,
                )
            ),
            0.0,
        )
        failed = func.coalesce(
            func.sum(case((Job.status == JobStatus.failed, 1), else_=0)), 0
        )
        res = (
            await session.execute(
                select(User.name, User.role, func.count(Job.id), failed, gpu_seconds)
                .join(User, Job.user_id == User.id)
                .where(Job.finished_at.is_not(None), Job.finished_at >= start, Job.finished_at < end)
                .group_by(User.id, User.name, User.role)
                .order_by(gpu_seconds.desc())
            )
        ).all()
        rows = [(n, r.value if hasattr(r, "value") else str(r), int(j), int(f), float(g)) for n, r, j, f, g in res]
        totals = {
            "jobs": sum(x[2] for x in rows),
            "failed": sum(x[3] for x in rows),
            "gpu_seconds": sum(x[4] for x in rows),
            "users": len(rows),
        }

        admin_rows = (
            await session.execute(
                select(User.email).where(User.role == UserRole.admin, User.is_active.is_(True))
            )
        ).scalars().all()
    recipients = sorted({(settings.FIRST_ADMIN_EMAIL or "").strip(), *[a.strip() for a in admin_rows]} - {""})
    if not recipients or not settings.smtp_configured:
        print("SMTP/penerima tidak tersedia; laporan tidak dikirim.")
        return

    pdf_bytes = _build_pdf(label, rows, totals)
    fname = f"laporan-computehub-{start.strftime('%Y-%m')}.pdf"
    body = (
        f"Laporan penggunaan UNISMUH ComputeHub periode {label} terlampir (PDF).\n\n"
        f"Ringkas: {totals['jobs']} job selesai ({totals['failed']} gagal), "
        f"total waktu GPU {_fmt_jam(totals['gpu_seconds'])}, {totals['users']} pengguna aktif.\n\n"
        f"- Tim {settings.PROJECT_NAME}"
    )
    await asyncio.to_thread(
        email_svc.send_email,
        recipients,
        f"Laporan penggunaan {label} - {settings.PROJECT_NAME}",
        body,
        [(fname, pdf_bytes, "application", "pdf")],
    )
    print(f"Laporan {label} terkirim ke: {', '.join(recipients)} ({len(pdf_bytes)//1024} KB)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 — best-effort
        print(f"Laporan bulanan gagal: {exc!r}")
