#!/usr/bin/env python3
"""PEMANTAU AKSES PUBLIK — pantau pintu masuk publik ComputeHub (gateway kampus).

Backend bisa sehat sempurna di server, tapi tetap "tak terjangkau" dari luar bila
gateway kampus (reverse-proxy TLS) macet. Skrip ini mengetuk URL PUBLIK secara
berkala dan mengabari lewat Telegram saat akses PADAM dan saat PULIH, lengkap
dengan lama padamnya — supaya tahu persis kapan gateway sudah diperbaiki tanpa
cek manual.

Anti-flapping: butuh beberapa kali gagal/berhasil beruntun sebelum mengubah
status, supaya gangguan sekejap tidak bikin ribut. Status disimpan di berkas
sehingga restart tidak mengirim ulang pesan yang sama.

Pemakaian:
    public_access_monitor.py              jalan terus (loop) — untuk systemd service
    public_access_monitor.py --once       satu ketukan saja — untuk cron
    public_access_monitor.py --status      tampilkan status tersimpan, tidak mengetuk
    public_access_monitor.py --test        kirim pesan uji ke Telegram, pastikan token benar

Konfigurasi opsional lewat variabel lingkungan:
    PUBLIC_URL        default https://computehub.lab.if.unismuh.ac.id/health
    INTERVAL_S        default 60   (jeda antar ketukan pada mode loop)
    TIMEOUT_S         default 10   (batas tunggu tiap ketukan)
    AMBANG_PADAM      default 3    (gagal beruntun sebelum dinyatakan PADAM)
    AMBANG_PULIH      default 2    (berhasil beruntun sebelum dinyatakan PULIH)

Kredensial Telegram dipakai ulang dari notify_telegram.py
(~/.computehub/net-health.env). Skrip ini tidak pernah menampilkan token.
Selalu keluar dengan status 0: pemantau tidak boleh jadi sumber masalah baru.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import notify_telegram  # noqa: E402  (dipakai ulang untuk kirim Telegram)

PUBLIC_URL = os.environ.get(
    "PUBLIC_URL", "https://computehub.lab.if.unismuh.ac.id/health"
)
INTERVAL_S = int(os.environ.get("INTERVAL_S", "60"))
TIMEOUT_S = int(os.environ.get("TIMEOUT_S", "10"))
AMBANG_PADAM = int(os.environ.get("AMBANG_PADAM", "3"))
AMBANG_PULIH = int(os.environ.get("AMBANG_PULIH", "2"))

STATE_DIR = Path.home() / ".computehub"
STATE_FILE = STATE_DIR / "public-access-monitor.state.json"
LOG_FILE = STATE_DIR / "public-access-monitor.log"


def sekarang() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(pesan: str) -> None:
    baris = f"[{sekarang()}] {pesan}"
    print(baris, flush=True)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(baris + "\n")
    except OSError:
        pass


def muat_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def simpan_state(state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        log(f"Gagal simpan state: {exc!r}")


def ketuk() -> tuple[bool, str]:
    """Return (sehat, keterangan). Sehat hanya bila HTTP 200."""
    req = urllib.request.Request(
        PUBLIC_URL, headers={"User-Agent": "ComputeHub-PublicMonitor/1.0"}
    )
    mulai = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            kode = resp.getcode()
            ms = int((time.monotonic() - mulai) * 1000)
            if kode == 200:
                return True, f"HTTP 200 ({ms} ms)"
            return False, f"HTTP {kode} ({ms} ms)"
    except urllib.error.HTTPError as exc:  # 5xx dari gateway, mis. 504
        ms = int((time.monotonic() - mulai) * 1000)
        return False, f"HTTP {exc.code} ({ms} ms)"
    except Exception as exc:  # timeout / koneksi gagal
        ms = int((time.monotonic() - mulai) * 1000)
        return False, f"{type(exc).__name__}: {exc} ({ms} ms)"


def fmt_durasi(detik: float) -> str:
    detik = int(detik)
    j, sisa = divmod(detik, 3600)
    m, d = divmod(sisa, 60)
    bagian = []
    if j:
        bagian.append(f"{j} jam")
    if m:
        bagian.append(f"{m} menit")
    if d or not bagian:
        bagian.append(f"{d} detik")
    return " ".join(bagian)


def proses(state: dict) -> dict:
    """Satu ketukan + perbarui state + kirim notifikasi bila status berubah."""
    sehat, ket = ketuk()
    now = time.time()

    status = state.get("status", "unknown")  # up | down | unknown
    streak_ok = state.get("streak_ok", 0)
    streak_gagal = state.get("streak_gagal", 0)

    if sehat:
        streak_ok += 1
        streak_gagal = 0
    else:
        streak_gagal += 1
        streak_ok = 0

    log(f"probe {PUBLIC_URL} -> {'OK' if sehat else 'GAGAL'}: {ket} "
        f"(ok×{streak_ok}, gagal×{streak_gagal}, status={status})")

    # Transisi ke PADAM
    if status != "down" and streak_gagal >= AMBANG_PADAM:
        state["down_sejak"] = now
        state["status"] = "down"
        if status == "up":  # hanya kabari bila sebelumnya memang normal
            notify_telegram.kirim(
                "🔴 ComputeHub — AKSES PUBLIK PADAM",
                f"URL: {PUBLIC_URL}\n"
                f"Gagal {streak_gagal}× beruntun ({ket}).\n"
                f"Backend server kemungkinan masih sehat; cek gateway kampus.\n"
                f"Waktu: {sekarang()}",
            )
        else:
            log("Status awal terdeteksi PADAM; tidak mengirim (belum pernah normal).")

    # Transisi ke PULIH
    elif status != "up" and streak_ok >= AMBANG_PULIH:
        pesan_durasi = ""
        if state.get("down_sejak"):
            pesan_durasi = f"\nLama padam: {fmt_durasi(now - state['down_sejak'])}."
        sebelumnya = status
        state["status"] = "up"
        state["up_sejak"] = now
        state.pop("down_sejak", None)
        if sebelumnya == "down":  # kabar baik hanya setelah benar-benar padam
            notify_telegram.kirim(
                "✅ ComputeHub — AKSES PUBLIK PULIH",
                f"URL: {PUBLIC_URL}\n"
                f"Normal kembali ({ket}).{pesan_durasi}\n"
                f"Waktu: {sekarang()}",
            )
        else:
            log("Status awal terdeteksi NORMAL; tidak mengirim.")

    state["streak_ok"] = streak_ok
    state["streak_gagal"] = streak_gagal
    state["terakhir_cek"] = sekarang()
    state["terakhir_hasil"] = ket
    simpan_state(state)
    return state


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg == "--test":
        notify_telegram.kirim(
            "🔔 Uji Pemantau Akses Publik ComputeHub",
            f"Pesan percobaan. Pemantau akan mengetuk {PUBLIC_URL} "
            f"tiap {INTERVAL_S} detik.\nWaktu: {sekarang()}",
        )
        return 0

    if arg == "--status":
        state = muat_state()
        if not state:
            print("Belum ada status tersimpan.")
        else:
            print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0

    if arg == "--once":
        proses(muat_state())
        return 0

    # Mode loop (default) — untuk systemd service
    log(f"Pemantau mulai. URL={PUBLIC_URL} interval={INTERVAL_S}s "
        f"timeout={TIMEOUT_S}s padam×{AMBANG_PADAM} pulih×{AMBANG_PULIH}")
    state = muat_state()
    while True:
        try:
            state = proses(state)
        except Exception as exc:  # noqa: BLE001  pemantau tak boleh mati
            log(f"Kesalahan tak terduga: {exc!r}")
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    raise SystemExit(main())
