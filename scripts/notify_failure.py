#!/usr/bin/env python3
"""Kirim email peringatan saat computehub.service GAGAL (dipicu systemd OnFailure).

Berdiri sendiri (tanpa import app) — baca kredensial SMTP dari backend/.env.
Penerima: FIRST_ADMIN_EMAIL (fallback ALERT_EMAIL_TO). Best-effort: kegagalan
kirim email tidak boleh mengganggu apa pun (exit 0 selalu).
"""

from __future__ import annotations

import smtplib
import socket
import subprocess
import sys
from datetime import datetime
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


def recent_log(unit: str) -> str:
    try:
        r = subprocess.run(
            ["journalctl", "--user", "-u", unit, "-n", "25", "--no-pager", "-o", "short"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout[-4000:]
    except Exception:  # noqa: BLE001
        return "(log tidak tersedia)"


def main() -> int:
    unit = sys.argv[1] if len(sys.argv) > 1 else "computehub.service"
    mode = sys.argv[2] if len(sys.argv) > 2 else "failed"
    env = load_env(ENV_PATH)
    host = env.get("SMTP_HOST", "")
    if not host:
        print("SMTP belum dikonfigurasi; lewati email.")
        return 0
    port = int(env.get("SMTP_PORT", "587") or 587)
    username = env.get("SMTP_USERNAME", "")
    password = env.get("SMTP_PASSWORD", "")
    sender = env.get("SMTP_FROM", username or "computehub@localhost")
    to = env.get("FIRST_ADMIN_EMAIL", "") or env.get("ALERT_EMAIL_TO", "")
    if not to:
        print("Tidak ada penerima (FIRST_ADMIN_EMAIL/ALERT_EMAIL_TO).")
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = socket.gethostname()
    msg = EmailMessage()
    if mode == "unhealthy":
        msg["Subject"] = f"[PENTING] ComputeHub TIDAK MERESPONS di {hostname}"
        body_head = (
            f"Health check http://127.0.0.1:8088/health GAGAL pada {now}\n"
            "(3x percobaan). Backend mungkin hang/crash-loop — periksa segera.\n"
        )
    else:
        msg["Subject"] = f"[PENTING] {unit} GAGAL di {hostname}"
        body_head = (
            f"Layanan {unit} masuk kondisi FAILED di server {hostname} pada {now}.\n"
            "Platform kemungkinan TIDAK BISA DIAKSES sampai ditangani manual.\n"
        )
    msg["From"] = formataddr(("UNISMUH ComputeHub", sender))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gmail.com")
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(
        body_head
        + "\nLangkah cepat:\n"
        f"  systemctl --user status {unit}\n"
        f"  journalctl --user -u {unit} -n 50\n"
        f"  systemctl --user restart {unit}\n\n"
        f"Log terakhir:\n{recent_log(unit)}\n"
    )
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            if username:
                s.login(username, password)
            s.send_message(msg)
        print(f"Email peringatan terkirim ke {to}.")
    except Exception as exc:  # noqa: BLE001
        print(f"Gagal kirim email: {exc!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
