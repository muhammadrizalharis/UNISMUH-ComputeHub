"""Notifikasi email status job batch (latar belakang) ke PEMILIK: selesai / gagal.

Tujuan: user tidak menunggu sia-sia — begitu job selesai atau ERROR, email masuk
sehingga bisa segera ditindaklanjuti (mis. memperbaiki error) tanpa menebak-nebak.

Best-effort: TIDAK pernah melempar & no-op bila SMTP belum dikonfigurasi -> kegagalan
email tak boleh mengganggu scheduler. Dipanggil fire-and-forget (asyncio.create_task).
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services import email as email_svc

logger = get_logger(__name__)


def _fmt_dur(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "sesaat"
    s = int(seconds)
    if s < 60:
        return f"{s} detik"
    if s < 3600:
        return f"{s // 60} menit {s % 60} detik"
    return f"{s // 3600} jam {(s % 3600) // 60} menit"


async def notify_job_finished(job_id: int) -> None:
    """Kirim email ke pemilik saat job SELESAI/GAGAL. Best-effort (tak melempar)."""
    try:
        if not settings.JOB_NOTIFY_EMAIL or not settings.smtp_configured:
            return
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status not in (JobStatus.succeeded, JobStatus.failed):
                return
            user = await session.get(User, job.user_id)
            if user is None:
                return
            to = (user.email or "").strip()
            if not to:
                return

            name = (job.name or f"Job #{job.id}").strip()
            greet = (user.name or user.username or "").strip() or "Halo"
            base = settings.public_base_url
            link = f"{base}/jobs/{job.id}" if base else ""
            dur = _fmt_dur(job.actual_runtime_seconds)

            if job.status == JobStatus.succeeded:
                subject = f'Job "{name}" selesai — {settings.PROJECT_NAME}'
                lines = [
                    f"Halo {greet},",
                    "",
                    f'Kabar baik! Job Anda "{name}" telah selesai dikerjakan di GPU.',
                    "",
                    "  Status : Selesai (berhasil)",
                    f"  Durasi : {dur}",
                ]
                if job.exit_code is not None:
                    lines.append(f"  Exit   : {job.exit_code}")
            else:
                subject = f'Job "{name}" gagal dijalankan — {settings.PROJECT_NAME}'
                err = (job.error_message or "Tidak ada detail error.").strip()
                if len(err) > 600:
                    err = err[:600] + " …"
                lines = [
                    f"Halo {greet},",
                    "",
                    f'Job Anda "{name}" berhenti karena error. Silakan segera periksa '
                    "agar waktu tidak terbuang menunggu.",
                    "",
                    "  Status : Gagal",
                    f"  Durasi : {dur}",
                    f"  Pesan  : {err}",
                ]
            if link:
                lines += ["", "Lihat detail & log lengkap di:", f"  {link}"]
            lines += ["", f"— Tim {settings.PROJECT_NAME}"]
            body = "\n".join(lines)

            await asyncio.to_thread(email_svc.send_email, [to], subject, body)
            logger.info(
                "Email status job #%d (%s) terkirim ke %s.",
                job_id,
                job.status.value,
                to,
            )
    except Exception as exc:  # noqa: BLE001 — best-effort, jangan ganggu scheduler
        logger.warning("Gagal kirim email status job #%d: %r", job_id, exc)
