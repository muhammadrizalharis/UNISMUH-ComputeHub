"""Pengiriman email (SMTP) — opsional, dengan lampiran PDF.

Gracefully no-op kalau SMTP belum dikonfigurasi (SMTP_HOST kosong): pemanggil
menangkap RuntimeError dan tetap menyimpan alert + PDF ke disk.
"""

from __future__ import annotations

import smtplib
import ssl
import time
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


_RETRIES = 3
_RETRY_DELAYS = (3, 10)


def _decode(raw: bytes | str) -> str:
    return raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)


def _login(srv: smtplib.SMTP) -> None:
    """Login dengan AUTH PLAIN lebih dulu. smtplib.login() bawaan mencoba metode
    berikutnya saat ditolak; Gmail lalu memutus koneksi sehingga galat asli (535
    kredensial salah) tertutupi "Connection unexpectedly closed"."""
    srv.ehlo_or_helo_if_needed()
    methods = (srv.esmtp_features.get("auth") or "").upper().split()
    if "PLAIN" in methods:
        srv.user, srv.password = settings.SMTP_USERNAME, settings.SMTP_PASSWORD
        code, resp = srv.auth("PLAIN", srv.auth_plain)
        if code not in (235, 503):
            raise smtplib.SMTPAuthenticationError(code, resp)
    else:
        srv.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)


def _deliver(msg: EmailMessage) -> None:
    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    timeout = settings.SMTP_TIMEOUT
    if settings.SMTP_USE_SSL:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx) as srv:
            if settings.SMTP_USERNAME:
                _login(srv)
            srv.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as srv:
            srv.ehlo()
            if settings.SMTP_USE_TLS:
                srv.starttls(context=ssl.create_default_context())
                srv.ehlo()
            if settings.SMTP_USERNAME:
                _login(srv)
            srv.send_message(msg)


def send_email(
    recipients: list[str],
    subject: str,
    body: str,
    attachments: list[Attachment] | None = None,
) -> None:
    """Kirim email (BLOCKING). Panggil via asyncio.to_thread.

    Gangguan jaringan/putus koneksi diulang hingga 3x (jeda 3 dtk, 10 dtk);
    kredensial ditolak langsung gagal dengan pesan yang jelas."""
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

    last_exc: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            _deliver(msg)
            break
        except smtplib.SMTPAuthenticationError as exc:
            # Kredensial ditolak -> mengulang tak ada gunanya (dan bisa memicu blokir).
            logger.error(
                "Login SMTP %s ditolak (%s %s). Periksa SMTP_USERNAME / SMTP_PASSWORD "
                "(App Password Gmail mungkin dicabut) di .env.",
                settings.SMTP_USERNAME, exc.smtp_code, _decode(exc.smtp_error),
            )
            raise
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError) as exc:
            last_exc = exc
            if attempt < _RETRIES:
                logger.warning("Kirim email percobaan %d gagal (%r); diulang.", attempt, exc)
                time.sleep(_RETRY_DELAYS[attempt - 1])
    else:
        assert last_exc is not None
        raise last_exc

    logger.info("Email terkirim ke %s: %s", ", ".join(recipients), subject)
