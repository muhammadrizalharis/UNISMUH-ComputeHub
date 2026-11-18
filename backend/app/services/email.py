"""Pengiriman email (SMTP) — opsional, dengan lampiran PDF.

Gracefully no-op kalau SMTP belum dikonfigurasi (SMTP_HOST kosong): pemanggil
menangkap RuntimeError dan tetap menyimpan alert + PDF ke disk.
"""

from __future__ import annotations

import datetime as dt
import smtplib
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path
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


_NOTIFY_TELEGRAM = Path(__file__).resolve().parents[3] / "scripts" / "notify_telegram.py"
_ALERT_REPEAT_SECONDS = 6 * 3600

# Status pengiriman (per proses). Email bisa gagal diam-diam karena pemberitahuannya
# sendiri lewat email, jadi kegagalan dilaporkan ke Telegram admin dan ditampilkan di web.
_lock = threading.Lock()
_status: dict = {
    "last_ok_at": None,
    "last_error": "",
    "last_error_at": None,
    "consecutive_failures": 0,
    "last_check_at": None,
    "last_check_ok": None,
}
_last_alert_at = 0.0


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _telegram(judul: str, isi: str) -> None:
    """Best-effort; tidak pernah melempar."""
    if not _NOTIFY_TELEGRAM.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(_NOTIFY_TELEGRAM), judul, isi],
            capture_output=True, timeout=30, check=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Notifikasi Telegram SMTP gagal: %s", exc)


def _record_ok(check: bool = False) -> None:
    global _last_alert_at
    with _lock:
        pulih = _status["consecutive_failures"] > 0
        _status["consecutive_failures"] = 0
        if check:
            _status["last_check_at"] = _now_iso()
            _status["last_check_ok"] = True
        else:
            _status["last_ok_at"] = _now_iso()
        if pulih:
            _last_alert_at = 0.0
    if pulih:
        _telegram("ComputeHub: email pulih", "Pengiriman email (SMTP) kembali berfungsi.")


def _record_fail(exc: BaseException, check: bool = False) -> None:
    global _last_alert_at
    detail = f"{type(exc).__name__}: {exc}"[:300]
    with _lock:
        _status["consecutive_failures"] += 1
        _status["last_error"] = detail
        _status["last_error_at"] = _now_iso()
        if check:
            _status["last_check_at"] = _status["last_error_at"]
            _status["last_check_ok"] = False
        kirim = time.monotonic() - _last_alert_at >= _ALERT_REPEAT_SECONDS or _last_alert_at == 0.0
        if kirim:
            _last_alert_at = time.monotonic()
    if kirim:
        _telegram(
            "ComputeHub: email GAGAL",
            f"Pengiriman email (SMTP) gagal: {detail}\n"
            "Notifikasi job & peringatan lewat email tidak sampai. "
            "Periksa SMTP_USERNAME/SMTP_PASSWORD di .env, lalu tekan 'Kirim email uji' "
            "di halaman Peringatan.",
        )


def status() -> dict:
    with _lock:
        return {"configured": settings.smtp_configured, **_status}


def check_connection() -> bool:
    """Uji koneksi + login SMTP TANPA mengirim email (BLOCKING). Mencatat status."""
    if not settings.smtp_configured:
        return False
    try:
        _deliver(None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Uji SMTP gagal: %s", exc)
        _record_fail(exc, check=True)
        return False
    _record_ok(check=True)
    return True


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


def _deliver(msg: EmailMessage | None) -> None:
    """Kirim `msg`; bila None hanya sambung + login (uji kesehatan)."""
    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    timeout = settings.SMTP_TIMEOUT
    if settings.SMTP_USE_SSL:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx) as srv:
            if settings.SMTP_USERNAME:
                _login(srv)
            if msg is not None:
                srv.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as srv:
            srv.ehlo()
            if settings.SMTP_USE_TLS:
                srv.starttls(context=ssl.create_default_context())
                srv.ehlo()
            if settings.SMTP_USERNAME:
                _login(srv)
            if msg is not None:
                srv.send_message(msg)


def _send_with_retry(msg: EmailMessage) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            _deliver(msg)
            return
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
    assert last_exc is not None
    raise last_exc


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

    try:
        _send_with_retry(msg)
    except Exception as exc:
        _record_fail(exc)
        raise
    _record_ok()
    logger.info("Email terkirim ke %s: %s", ", ".join(recipients), subject)
