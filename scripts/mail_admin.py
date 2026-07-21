#!/usr/bin/env python3
"""Kirim email singkat ke admin (FIRST_ADMIN_EMAIL) — dipakai skrip operasional.

Pemakaian: mail_admin.py "Subjek" [body-file]   (tanpa body-file -> baca stdin)
Standalone (tanpa import app); SMTP dari backend/.env. Selalu exit 0 (best-effort).
"""

from __future__ import annotations

import smtplib
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / "backend" / ".env"


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def main() -> int:
    subject = sys.argv[1] if len(sys.argv) > 1 else "(tanpa subjek)"
    body = (
        Path(sys.argv[2]).read_text()
        if len(sys.argv) > 2 and Path(sys.argv[2]).is_file()
        else sys.stdin.read()
    )
    env = load_env(ENV_PATH)
    host = env.get("SMTP_HOST", "")
    to = env.get("FIRST_ADMIN_EMAIL", "") or env.get("ALERT_EMAIL_TO", "")
    if not host or not to:
        print("SMTP/penerima belum dikonfigurasi; lewati email.")
        return 0
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(
        ("UNISMUH ComputeHub", env.get("SMTP_FROM", env.get("SMTP_USERNAME", "")))
    )
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gmail.com")
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body or "(kosong)")
    try:
        with smtplib.SMTP(host, int(env.get("SMTP_PORT", "587") or 587), timeout=20) as s:
            s.starttls()
            if env.get("SMTP_USERNAME"):
                s.login(env["SMTP_USERNAME"], env.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        print(f"Email terkirim ke {to}.")
    except Exception as exc:  # noqa: BLE001
        print(f"Gagal kirim email: {exc!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
