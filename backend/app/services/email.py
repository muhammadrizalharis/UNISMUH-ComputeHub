"""Pengiriman email (SMTP) — opsional, dengan lampiran PDF.

Gracefully no-op kalau SMTP belum dikonfigurasi (SMTP_HOST kosong): pemanggil
menangkap RuntimeError dan tetap menyimpan alert + PDF ke disk.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# (filename, data_bytes, maintype, subtype)
Attachment = tuple[str, bytes, str, str]


def _html_body(text: str, title: str) -> str:
    """Bungkus teks polos jadi HTML sederhana. Multipart text+HTML lebih 'legit' di
    mata filter spam + tautan (https) jadi bisa diklik."""
    import html as _html
    import re as _re

    safe = _html.escape(text)
    safe = _re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#4f46e5">\1</a>', safe)
    safe = safe.replace("\n", "<br>")
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:0;background:#f8fafc">'
        '<div style="max-width:560px;margin:0 auto;padding:20px;'
        'font-family:Segoe UI,Roboto,Arial,sans-serif;font-size:14px;'
        'color:#1e293b;line-height:1.6">'
        '<div style="font-weight:700;color:#4f46e5;font-size:16px;margin-bottom:12px">'
        f'{_html.escape(title)}</div>'
        f'<div>{safe}</div>'
        '</div></body></html>'
    )


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
    from_addr = settings.SMTP_FROM or settings.SMTP_USERNAME or "computehub@localhost"
    from_name = settings.SMTP_FROM_NAME.strip() or settings.PROJECT_NAME
    domain = from_addr.rsplit("@", 1)[-1] if "@" in from_addr else "localhost"
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    # Header standar WAJIB: email tanpa Date/Message-ID kerap ditandai SPAM. Reply-To &
    # Auto-Submitted menandai ini notifikasi otomatis yang sah (bukan bulk/marketing).
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Reply-To"] = from_addr
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body)
    msg.add_alternative(_html_body(body, from_name), subtype="html")

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
