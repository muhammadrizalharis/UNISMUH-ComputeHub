#!/usr/bin/env python3
"""Kirim peringatan singkat ke admin (email + Telegram) — dipakai skrip operasional.

Pemakaian: mail_admin.py "Subjek" [body-file]   (tanpa body-file -> baca stdin)
Standalone (tanpa import app); SMTP dari backend/.env. Selalu exit 0 (best-effort).

Dua jalur sengaja dipakai bersamaan: email kampus/Gmail kerap tersaring ke spam,
sedangkan Telegram sampai seketika. Dapat diatur lewat variabel lingkungan:
  MAIL_ADMIN_TO=<email>        ganti penerima (default FIRST_ADMIN_EMAIL)
  MAIL_ADMIN_NO_TELEGRAM=1     kirim email saja (mis. saat agen Telegram-nya yang mati)
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / "backend" / ".env"
TG_RINGKAS_AWAL = 900   # potong isi panjang (mis. log uji pemulihan) agar muat
TG_RINGKAS_AKHIR = 1500  # ekor biasanya berisi kesimpulan/galat


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


def _ringkas(body: str) -> str:
    """Pangkas bagian tengah isi panjang; awal & akhir yang paling informatif."""
    body = body.strip()
    if len(body) <= TG_RINGKAS_AWAL + TG_RINGKAS_AKHIR:
        return body
    dibuang = len(body) - TG_RINGKAS_AWAL - TG_RINGKAS_AKHIR
    return (f"{body[:TG_RINGKAS_AWAL]}\n\n… ({dibuang} karakter dipotong) …\n\n"
            f"{body[-TG_RINGKAS_AKHIR:]}")


def kirim_telegram(subject: str, body: str) -> None:
    """Best-effort; diam-diam dilewati bila modul/kredensial tidak tersedia."""
    if os.environ.get("MAIL_ADMIN_NO_TELEGRAM", "").strip() in ("1", "true", "yes"):
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from notify_telegram import kirim  # noqa: PLC0415 — sengaja lazy

        kirim(f"\U0001f6a8 {subject}", _ringkas(body))
    except Exception as exc:  # noqa: BLE001
        print(f"Gagal kirim Telegram: {exc!r}")


def main() -> int:
    subject = sys.argv[1] if len(sys.argv) > 1 else "(tanpa subjek)"
    body = (
        Path(sys.argv[2]).read_text()
        if len(sys.argv) > 2 and Path(sys.argv[2]).is_file()
        else sys.stdin.read()
    )
    # Telegram dulu: paling cepat sampai dan tetap jalan walau SMTP bermasalah.
    kirim_telegram(subject, body or "(kosong)")

    env = load_env(ENV_PATH)
    host = env.get("SMTP_HOST", "")
    to = (
        os.environ.get("MAIL_ADMIN_TO", "").strip()
        or env.get("FIRST_ADMIN_EMAIL", "")
        or env.get("ALERT_EMAIL_TO", "")
    )
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
