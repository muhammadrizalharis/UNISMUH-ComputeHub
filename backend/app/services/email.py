"""Pengiriman email (SMTP) — opsional, dengan lampiran PDF.

Gracefully no-op kalau SMTP belum dikonfigurasi (SMTP_HOST kosong): pemanggil
menangkap RuntimeError dan tetap menyimpan alert + PDF ke disk.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# (filename, data_bytes, maintype, subtype)
Attachment = tuple[str, bytes, str, str]


def send_email(
    recipients: list[str],
    subject: str,
    body: str,
    attachments: list[Attachment] | None = None,
) -> None:
    """Kirim email (BLOCKING). Panggil via asyncio.to_thread."""
    if not settings.smtp_configured:
        raise RuntimeError("SMTP belum dikonfigurasi (set SMTP_HOST di .env).")
    recipients = [r.strip() for r in recipients if r and r.strip()]
    if not recipients:
        raise RuntimeError("Tidak ada penerima email.")

    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USERNAME or "computehub@localhost"
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    for filename, data, maintype, subtype in attachments or []:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    timeout = settings.SMTP_TIMEOUT

    if settings.SMTP_USE_SSL:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx) as srv:
            if settings.SMTP_USERNAME:
                srv.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            srv.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as srv:
            srv.ehlo()
            if settings.SMTP_USE_TLS:
                srv.starttls(context=ssl.create_default_context())
                srv.ehlo()
            if settings.SMTP_USERNAME:
                srv.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            srv.send_message(msg)

    logger.info("Email terkirim ke %s: %s", ", ".join(recipients), subject)
