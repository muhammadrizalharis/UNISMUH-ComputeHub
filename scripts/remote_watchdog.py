#!/usr/bin/env python3
"""PENJAGA LUAR — dijalankan di LAPTOP, bukan di server.

Semua pemberi kabar yang lain (watchdog, agen pemantau, pengirim email) hidup di
dalam server yang sama dengan aplikasinya. Kalau servernya sendiri yang mati —
listrik padam, kernel panic, jaringan lab putus — mereka ikut mati dan hasilnya
hening total. Skrip ini adalah saksi dari luar: ia mengetuk /health dari jaringan
lain, jadi ia tetap bisa bicara justru saat server tidak bisa.

Cara kerja: satu ketukan per panggilan (dijadwalkan cron / Task Scheduler tiap
10 menit). Peringatan baru dikirim setelah GAGAL BERTURUT-TURUT sekian kali,
supaya gangguan sekejap tidak bikin ribut. Saat pulih, dikirim kabar baiknya
sekalian dengan lama padamnya.

Pemakaian:
    remote_watchdog.py           sekali ketuk (untuk cron / Task Scheduler)
    remote_watchdog.py --uji     kirim pesan percobaan, pastikan token benar
    remote_watchdog.py --status  tampilkan keadaan tersimpan, tidak mengirim apa pun

Konfigurasi di ~/.computehub-watch.env (boleh dipindah lewat variabel
lingkungan COMPUTEHUB_WATCH_ENV):
    TELEGRAM_BOT_TOKEN=...        wajib
    TELEGRAM_CHAT_ID=...          wajib (boleh dipisah koma)
    HEALTH_URL=...                opsional
    AMBANG_GAGAL=3                opsional, berapa kali gagal beruntun
    TIMEOUT_S=15                  opsional

Stdlib saja (tidak perlu pip install) supaya bisa jalan di laptop mana pun.
Selalu keluar dengan status 0: penjaga tidak boleh jadi sumber masalah baru.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ENV_FILE = Path(os.environ.get("COMPUTEHUB_WATCH_ENV", "")) if os.environ.get(
    "COMPUTEHUB_WATCH_ENV") else Path.home() / ".computehub-watch.env"
STATE_FILE = Path(str(ENV_FILE) + ".state.json")
LOG_FILE = Path(str(ENV_FILE) + ".log")

HEALTH_URL_BAWAAN = "https://computehub.lab.if.unismuh.ac.id/health"
PROBE_INTERNET = "https://api.telegram.org"  # dipakai juga untuk mengirim pesan
AMBANG_BAWAAN = 3
TIMEOUT_BAWAAN = 15


def log(pesan: str) -> None:
    baris = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {pesan}"
    print(baris)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(baris + "\n")
    except OSError:
        pass


def baca_env() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for baris in ENV_FILE.read_text(encoding="utf-8").splitlines():
            baris = baris.strip()
            if not baris or baris.startswith("#") or "=" not in baris:
                continue
            k, _, v = baris.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def baca_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tulis_state(st: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(st), encoding="utf-8")
    except OSError as exc:
        log(f"gagal menyimpan keadaan: {exc}")


def kirim_telegram(env: dict[str, str], teks: str) -> bool:
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chats = [c.strip() for c in env.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chats:
        log("Telegram belum dikonfigurasi; pesan tidak dikirim.")
        return False
    url = f"{PROBE_INTERNET}/bot{token}/sendMessage"
    terkirim = False
    for chat_id in chats:
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": teks[:3900]}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20):
                pass
            terkirim = True
            log(f"pesan terkirim ke {chat_id}")
        except Exception as exc:  # noqa: BLE001
            log(f"gagal kirim ke {chat_id}: {exc!r}")
    return terkirim


def ketuk(url: str, timeout: int) -> tuple[bool, str]:
    """(sehat, keterangan). Sehat hanya bila HTTP 200."""
    try:
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "computehub-remote-watchdog"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__ + f": {exc}"


def laptop_online(timeout: int) -> bool:
    """Beda 'server mati' dengan 'laptop saya yang sedang offline'.

    Tanpa pembeda ini, wifi laptop putus sebentar akan dilaporkan sebagai server
    tumbang. Yang diketuk adalah api.telegram.org — kalau itu pun tak terjangkau,
    peringatan tidak akan sampai juga, jadi memang tidak ada gunanya menghitung.
    """
    try:
        req = urllib.request.Request(PROBE_INTERNET, method="GET",
                                     headers={"User-Agent": "computehub-remote-watchdog"})
        urllib.request.urlopen(req, timeout=timeout).close()
        return True
    except urllib.error.HTTPError:
        return True  # dijawab (404/401 dsb) berarti internet jalan
    except Exception:  # noqa: BLE001
        return False


def lama(detik: float) -> str:
    d = max(0, int(detik))
    if d < 3600:
        return f"{d // 60} menit"
    if d < 86400:
        jam, menit = d // 3600, d % 3600 // 60
        return f"{jam} jam {menit} menit" if menit else f"{jam} jam"
    return f"{d // 86400} hari"


def main() -> int:
    env = baca_env()
    if not ENV_FILE.exists():
        log(f"Berkas konfigurasi {ENV_FILE} belum ada. Lihat keterangan di atas berkas ini.")
        return 0

    url = env.get("HEALTH_URL", "") or HEALTH_URL_BAWAAN
    try:
        ambang = max(1, int(env.get("AMBANG_GAGAL", "") or AMBANG_BAWAAN))
    except ValueError:
        ambang = AMBANG_BAWAAN
    try:
        timeout = max(3, int(env.get("TIMEOUT_S", "") or TIMEOUT_BAWAAN))
    except ValueError:
        timeout = TIMEOUT_BAWAAN

    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    st = baca_state()

    if arg == "--status":
        sehat, ket = ketuk(url, timeout)
        print(f"Sasaran        : {url}")
        print(f"Ketukan sekarang: {'SEHAT' if sehat else 'GAGAL'} ({ket})")
        print(f"Gagal beruntun : {st.get('gagal', 0)} dari ambang {ambang}")
        print(f"Sudah dilaporkan: {'ya' if st.get('lapor_down') else 'belum'}")
        terakhir = st.get("terakhir_ok")
        print(f"Terakhir sehat : {datetime.fromtimestamp(terakhir):%Y-%m-%d %H:%M:%S}"
              if terakhir else "Terakhir sehat : belum pernah tercatat")
        return 0

    if arg == "--uji":
        sehat, ket = ketuk(url, timeout)
        ok = kirim_telegram(env, "\U0001f9ea Uji penjaga luar (dari laptop)\n\n"
                                 f"Sasaran: {url}\nHasil ketukan: {ket}\n"
                                 f"Peringatan dikirim setelah {ambang}x gagal beruntun.\n\n"
                                 "Kalau pesan ini sampai, penjaga luar siap bertugas.")
        log("uji selesai; " + ("pesan sampai." if ok else "pesan TIDAK sampai."))
        return 0

    sehat, ket = ketuk(url, timeout)
    sekarang = time.time()

    if sehat:
        if st.get("lapor_down"):
            sejak = st.get("mulai_gagal", sekarang)
            kirim_telegram(env, "\u2705 ComputeHub PULIH (dipantau dari luar)\n\n"
                                f"Server menjawab lagi setelah {lama(sekarang - sejak)} hening.\n"
                                f"Sasaran: {url}")
        st.update({"gagal": 0, "lapor_down": False, "terakhir_ok": sekarang})
        st.pop("mulai_gagal", None)
        tulis_state(st)
        log(f"sehat ({ket})")
        return 0

    if not laptop_online(timeout):
        log(f"gagal ({ket}) TAPI laptop sedang offline — tidak dihitung.")
        return 0

    gagal = int(st.get("gagal", 0)) + 1
    st["gagal"] = gagal
    st.setdefault("mulai_gagal", sekarang)
    log(f"gagal ke-{gagal} ({ket})")

    if gagal >= ambang and not st.get("lapor_down"):
        terakhir = st.get("terakhir_ok")
        kirim_telegram(
            env,
            "\U0001f6a8 ComputeHub TIDAK MENJAWAB dari luar\n\n"
            f"Gagal {gagal}x beruntun. Keterangan terakhir: {ket}\n"
            f"Sasaran: {url}\n"
            + (f"Terakhir sehat: {datetime.fromtimestamp(terakhir):%Y-%m-%d %H:%M:%S}\n"
               if terakhir else "")
            + "\nKarena kabar ini datang dari LUAR server, kemungkinan besar yang mati\n"
              "bukan cuma aplikasinya: bisa listrik, jaringan lab, atau mesinnya sendiri.\n"
              "Peringatan dari dalam server (email/Telegram) mungkin tidak akan datang.",
        )
        st["lapor_down"] = True

    tulis_state(st)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — penjaga tidak boleh ikut tumbang
        log(f"galat tak terduga: {exc!r}")
        raise SystemExit(0)
