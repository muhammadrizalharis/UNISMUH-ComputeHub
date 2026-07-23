#!/usr/bin/env python3
"""Bot Telegram kill-switch ComputeHub — daemon TERPISAH dari aplikasi web.

Tujuan: pemilik server bisa MEMATIKAN / MENGHIDUPKAN aplikasi dari Telegram
kapan pun (mis. bila akses super admin aplikasi disalahgunakan), tanpa laptop.

Keamanan (kredensial TIDAK pernah ada di repo ini):
  - Konfigurasi di ~/.computehub/telebot.env (chmod 600, milik user Linux):
        TELEGRAM_BOT_TOKEN=123456:ABC...   (dari @BotFather)
        TELEGRAM_CHAT_ID=123456789         (chat id pemilik; boleh koma: id1,id2)
        TELEBOT_SECRET=kode-rahasia-kamu   (diketik di setiap perintah aksi)
  - DUA lapis: pesan hanya diproses dari chat_id whitelist, DAN aksi
    (matikan/hidupkan/restart) wajib menyertakan kode rahasia.
  - Bot hanya bisa menjalankan aksi TETAP (systemctl --user stop/start/restart
    computehub.service) — tidak ada eksekusi perintah bebas dari chat.
  - Anti-replay: pesan berumur > 120 detik diabaikan; offset update disimpan.
  - Long-poll keluar (HTTPS ke api.telegram.org) — tanpa port publik/webhook.

Jalan sebagai systemd --user unit terpisah (computehub-telebot.service) sehingga
TETAP hidup saat aplikasi dimatikan. Bila env belum diisi, bot menunggu dengan
sabar (cek tiap 60 dtk) — service bisa di-enable sebelum token ada.

Setup Telegram (sekali): chat @BotFather -> /newbot -> salin token; lalu chat
@userinfobot -> salin Id; isi telebot.env; systemctl --user restart
computehub-telebot.service; kirim /status ke bot-mu.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ENV_FILE = Path.home() / ".computehub" / "telebot.env"
STATE_FILE = Path.home() / ".computehub" / "telebot.offset"
LOG_FILE = Path.home() / ".computehub" / "telebot.log"
SERVICE = "computehub.service"
HEALTH_URL = "https://computehub.lab.if.unismuh.ac.id/health"
MAX_MSG_AGE_S = 120  # anti-replay: abaikan pesan lama


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config() -> dict | None:
    """Baca telebot.env; None bila belum lengkap (bot menunggu)."""
    if not ENV_FILE.exists():
        return None
    cfg: dict[str, str] = {}
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        cfg[k.strip()] = v.strip()
    token = cfg.get("TELEGRAM_BOT_TOKEN", "")
    chats = {c.strip() for c in cfg.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()}
    secret = cfg.get("TELEBOT_SECRET", "")
    if not token or not chats or not secret:
        return None
    return {"token": token, "chats": chats, "secret": secret}


def tg(token: str, method: str, timeout: int = 60, **params) -> dict:
    """Panggil API Telegram (stdlib urllib; tanpa dependency)."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def send(token: str, chat_id: str, text: str) -> None:
    try:
        tg(token, "sendMessage", timeout=15, chat_id=chat_id, text=text)
    except Exception as exc:  # noqa: BLE001
        log(f"gagal kirim pesan: {exc}")


def svc(action: str) -> tuple[bool, str]:
    """systemctl --user <action> computehub.service (aksi TETAP, bukan bebas)."""
    assert action in ("stop", "start", "restart", "is-active")
    r = subprocess.run(
        ["systemctl", "--user", action, SERVICE],
        capture_output=True, text=True, timeout=60,
    )
    out = (r.stdout or r.stderr or "").strip()
    return r.returncode == 0, out


def health_code() -> int:
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0  # tak terjangkau


def kernel_count() -> int:
    try:
        r = subprocess.run(
            ["sudo", "-n", "docker", "ps", "-q", "--filter", "name=ch-kernel",
             "--filter", "name=ch-job"],
            capture_output=True, text=True, timeout=15,
        )
        return len([x for x in r.stdout.splitlines() if x.strip()])
    except Exception:  # noqa: BLE001
        return -1


def status_text() -> str:
    _, active = svc("is-active")
    hc = health_code()
    kc = kernel_count()
    ikon = "🟢" if (active == "active" and hc == 200) else "🔴"
    baris = [
        f"{ikon} ComputeHub",
        f"• Service : {active}",
        f"• Health  : {'HTTP ' + str(hc) if hc else 'TIDAK TERJANGKAU'}",
        f"• Kernel/job aktif: {kc if kc >= 0 else '?'}",
    ]
    return "\n".join(baris)


def handle(cfg: dict, chat_id: str, text: str) -> None:
    token, secret = cfg["token"], cfg["secret"]
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0] if parts else ""
    kode = parts[1] if len(parts) > 1 else ""

    if cmd in ("/start", "/help"):
        send(token, chat_id,
             "🤖 Kill-switch ComputeHub\n"
             "/status — kondisi aplikasi\n"
             "/matikan <kode> — hentikan aplikasi\n"
             "/hidupkan <kode> — nyalakan kembali\n"
             "/restart <kode> — mulai ulang\n"
             "Aksi butuh kode rahasia pemilik.")
        return
    if cmd == "/status":
        send(token, chat_id, status_text())
        return
    if cmd in ("/matikan", "/hidupkan", "/restart"):
        if kode != secret:
            log(f"KODE SALAH utk {cmd} dari chat {chat_id}")
            send(token, chat_id, "⛔ Kode salah. Format: " + cmd + " <kode>")
            return
        if cmd == "/matikan":
            ok, out = svc("stop")
            log(f"AKSI stop oleh {chat_id}: ok={ok} {out}")
            time.sleep(2)
            _, active = svc("is-active")
            send(token, chat_id,
                 ("🔴 Aplikasi DIMATIKAN." if active != "active"
                  else "⚠️ Gagal mematikan: " + out) + f"\nService: {active}")
        elif cmd == "/hidupkan":
            ok, out = svc("start")
            log(f"AKSI start oleh {chat_id}: ok={ok} {out}")
            send(token, chat_id, "⏳ Menyalakan… cek kesehatan dalam 8 detik.")
            time.sleep(8)
            hc = health_code()
            send(token, chat_id,
                 ("🟢 Aplikasi HIDUP KEMBALI normal (health 200)." if hc == 200
                  else f"⚠️ Service start tapi health = {hc or 'tak terjangkau'} — cek log server."))
        else:  # /restart
            ok, out = svc("restart")
            log(f"AKSI restart oleh {chat_id}: ok={ok} {out}")
            send(token, chat_id, "⏳ Restart… cek kesehatan dalam 8 detik.")
            time.sleep(8)
            hc = health_code()
            send(token, chat_id,
                 "🟢 Restart selesai, health 200." if hc == 200
                 else f"⚠️ Health = {hc or 'tak terjangkau'} setelah restart.")
        return
    send(token, chat_id, "Perintah tak dikenal. /help untuk daftar.")


def read_offset() -> int:
    try:
        return int(STATE_FILE.read_text().strip())
    except Exception:  # noqa: BLE001
        return 0


def write_offset(v: int) -> None:
    try:
        STATE_FILE.write_text(str(v))
    except OSError:
        pass


def main() -> None:
    log("bot mulai; menunggu konfigurasi bila belum ada…")
    cfg = None
    while cfg is None:
        cfg = load_config()
        if cfg is None:
            time.sleep(60)
    log(f"konfigurasi OK (whitelist {len(cfg['chats'])} chat). Long-poll dimulai.")
    offset = read_offset()
    # Anti-replay saat start: lompati antrean lama (ambil update paling akhir).
    try:
        r = tg(cfg["token"], "getUpdates", timeout=15, offset=-1)
        if r.get("result"):
            offset = r["result"][-1]["update_id"] + 1
            write_offset(offset)
    except Exception as exc:  # noqa: BLE001
        log(f"init offset gagal (lanjut): {exc}")

    while True:
        # Konfigurasi bisa diganti (rotasi kode) tanpa restart.
        cfg = load_config() or cfg
        try:
            r = tg(cfg["token"], "getUpdates", timeout=60, offset=offset, limit=10,
                   allowed_updates='["message"]')
        except Exception as exc:  # noqa: BLE001
            log(f"getUpdates error: {exc}; ulangi 10 dtk")
            time.sleep(10)
            continue
        for upd in r.get("result", []):
            offset = upd["update_id"] + 1
            write_offset(offset)
            msg = upd.get("message") or {}
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            text = msg.get("text") or ""
            ts = msg.get("date", 0)
            if chat_id not in cfg["chats"]:
                log(f"DITOLAK chat asing {chat_id}: {text[:40]!r}")
                continue
            if time.time() - ts > MAX_MSG_AGE_S:
                log(f"pesan kedaluwarsa diabaikan dari {chat_id}")
                continue
            try:
                handle(cfg, chat_id, text)
            except Exception as exc:  # noqa: BLE001
                log(f"handle error: {exc}")


if __name__ == "__main__":
    main()
