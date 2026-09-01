#!/usr/bin/env python3
"""Kirim satu pesan ke Telegram admin ComputeHub — dipakai skrip lain (backup,
uji pemulihan, laporan bulanan) supaya pemberitahuan tidak hanya lewat email.

Pemakaian:
    notify_telegram.py "Judul" "Isi pesan"
    echo "isi panjang" | notify_telegram.py "Judul" -

Kredensial dibaca dari ~/.computehub/net-health.env (chmod 600, TIDAK pernah
masuk repo): TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID (boleh dipisah koma).
Best-effort: apa pun yang gagal tetap keluar dengan status 0 supaya tidak
menggagalkan skrip pemanggil (backup lebih penting daripada notifikasinya).
"""

from __future__ import annotations

import sys
import uuid
import urllib.parse
import urllib.request
from pathlib import Path

ENV_FILE = Path.home() / ".computehub" / "net-health.env"
MAX_LEN = 3900  # batas aman Telegram (4096) dikurangi ruang judul


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def kirim(judul: str, isi: str) -> None:
    env = load_env(ENV_FILE)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chats = [c.strip() for c in env.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chats:
        print("Telegram belum dikonfigurasi; lewati.")
        return
    teks = f"{judul}\n\n{isi}".strip()[:MAX_LEN]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in chats:
        try:
            data = urllib.parse.urlencode({"chat_id": chat_id, "text": teks}).encode()
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15):
                pass
            print(f"Notifikasi Telegram terkirim ke {chat_id}.")
        except Exception as exc:  # noqa: BLE001
            print(f"Gagal kirim Telegram ke {chat_id}: {exc!r}")


def _multipart(fields: dict[str, str], filename: str, blob: bytes) -> tuple[bytes, str]:
    """Bangun body multipart/form-data (stdlib saja, tanpa `requests`)."""
    boundary = "----computehub" + uuid.uuid4().hex
    out: list[bytes] = []
    for k, v in fields.items():
        out += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{k}"'.encode(),
            b"",
            str(v).encode("utf-8"),
        ]
    out += [
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="document"; filename="{filename}"'.encode(),
        b"Content-Type: application/octet-stream",
        b"",
        blob,
        f"--{boundary}--".encode(),
        b"",
    ]
    return b"\r\n".join(out), f"multipart/form-data; boundary={boundary}"


def kirim_dokumen(caption: str, path: Path) -> None:
    """Kirim BERKAS (mis. PDF laporan) sebagai dokumen ke chat admin."""
    env = load_env(ENV_FILE)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chats = [c.strip() for c in env.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chats:
        print("Telegram belum dikonfigurasi; lewati.")
        return
    try:
        blob = path.read_bytes()
    except OSError as exc:
        print(f"Gagal baca dokumen {path}: {exc!r}")
        return
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    for chat_id in chats:
        try:
            body, ctype = _multipart(
                {"chat_id": chat_id, "caption": (caption or "")[:1024]}, path.name, blob
            )
            req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
            with urllib.request.urlopen(req, timeout=90):
                pass
            print(f"Dokumen Telegram terkirim ke {chat_id}: {path.name} ({len(blob)//1024} KB).")
        except Exception as exc:  # noqa: BLE001
            print(f"Gagal kirim dokumen ke {chat_id}: {exc!r}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    # Mode dokumen: notify_telegram.py --doc <path> [caption]
    if sys.argv[1] == "--doc":
        if len(sys.argv) < 3:
            print("Pemakaian: notify_telegram.py --doc <path> [caption]")
            return 0
        path = Path(sys.argv[2])
        caption = sys.argv[3] if len(sys.argv) > 3 else path.name
        kirim_dokumen(caption, path)
        return 0
    judul = sys.argv[1]
    isi = sys.argv[2] if len(sys.argv) > 2 else ""
    if isi == "-" or not isi:
        isi = sys.stdin.read() if not sys.stdin.isatty() else ""
    kirim(judul, isi)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
