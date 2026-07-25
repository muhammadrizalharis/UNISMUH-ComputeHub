#!/usr/bin/env python3
"""Kirim peringatan (email + Telegram) saat computehub.service GAGAL.

Dipicu systemd OnFailure, dan oleh health_watchdog.sh saat /health tidak merespons.
Berdiri sendiri (tanpa import app) — kredensial SMTP dari backend/.env, kredensial
Telegram dari ~/.computehub/net-health.env (dipakai bersama bot kill-switch).
Best-effort: kegagalan kirim tidak boleh mengganggu apa pun (exit 0 selalu).
"""

from __future__ import annotations

import smtplib
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / "backend" / ".env"
TELEGRAM_ENV_PATH = Path.home() / ".computehub" / "net-health.env"


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


def send_telegram(subject: str, body: str) -> None:
    """Kirim peringatan ke Telegram admin. Diam-diam dilewati bila belum diatur.

    Sengaja memakai file env yang sama dengan bot kill-switch supaya admin cukup
    mengisi token/chat id di SATU tempat.
    """
    env = load_env(TELEGRAM_ENV_PATH)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chats = [c.strip() for c in env.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chats:
        print("Telegram belum dikonfigurasi; lewati.")
        return
    text = f"\U0001f6a8 {subject}\n\n{body}"[:3900]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in chats:
        try:
            data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15):
                pass
            print(f"Peringatan Telegram terkirim ke {chat_id}.")
        except Exception as exc:  # noqa: BLE001
            print(f"Gagal kirim Telegram ke {chat_id}: {exc!r}")


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
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = socket.gethostname()

    if mode == "unhealthy":
        subject = f"[PENTING] ComputeHub TIDAK MERESPONS di {hostname}"
        body_head = (
            f"Health check http://127.0.0.1:8088/health GAGAL pada {now}\n"
            "(3x percobaan). Backend mungkin hang/crash-loop — periksa segera.\n"
        )
    elif mode == "boot":
        subject = f"[INFO] Server {hostname} baru saja HIDUP KEMBALI"
        body_head = (
            f"Server booting ulang pada {now}. Artinya sebelumnya server MATI\n"
            "(listrik padam / reboot / crash). ComputeHub start otomatis.\n"
        )
    else:
        subject = f"[PENTING] {unit} GAGAL di {hostname}"
        body_head = (
            f"Layanan {unit} masuk kondisi FAILED di server {hostname} pada {now}.\n"
            "Platform kemungkinan TIDAK BISA DIAKSES sampai ditangani manual.\n"
        )
    langkah = (
        "\nLangkah cepat:\n"
        f"  systemctl --user status {unit}\n"
        f"  journalctl --user -u {unit} -n 50\n"
        f"  systemctl --user restart {unit}\n"
    )

    # Telegram lebih dulu: paling cepat sampai, dan tetap jalan walau SMTP mati.
    send_telegram(subject, body_head + langkah)

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

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("UNISMUH ComputeHub", sender))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gmail.com")
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body_head + langkah + f"\nLog terakhir:\n{recent_log(unit)}\n")
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
