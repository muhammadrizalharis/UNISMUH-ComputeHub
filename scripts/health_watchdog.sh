#!/usr/bin/env bash
# Watchdog ComputeHub (dijalankan timer tiap 5 menit). Tiga pemeriksaan:
#  1. /health backend (3x, jeda 5 dtk)  -> gagal semua = peringatan (cooldown 2 jam)
#  2. Image docker ch-compute:latest    -> hilang (mis. kena docker prune user
#     lain, PERNAH TERJADI) = peringatan (cooldown 6 jam); kernel/job akan gagal.
#  3. Kesegaran backup offsite di Drive -> dicek 1x/hari; file terbaru > 48 jam
#     = peringatan (upload rclone berhenti diam-diam, mis. client_id pensiun).
#
# Semua peringatan dikirim lewat DUA jalur sekaligus (email + Telegram):
# notify_failure.py untuk no.1, mail_admin.py untuk no.2 & 3. Email kampus/Gmail
# terlalu sering tersaring ke spam untuk dijadikan satu-satunya kabar.

BASE=/home/muhammadrizalharis/DATA_ICAL/SERVER-KAMPUS
STATE_DIR="$HOME/.computehub"
mkdir -p "$STATE_DIR"
PY="$BASE/backend/.venv/bin/python"
MAIL="$BASE/scripts/mail_admin.py"
RCLONE="${RCLONE_BIN:-$HOME/bin/rclone}"
now=$(date +%s)

cooldown_ok() { # $1=state-file $2=detik
  local last
  last=$(cat "$STATE_DIR/$1" 2>/dev/null || echo 0)
  [ $((now - last)) -ge "$2" ]
}
mark() { echo "$now" > "$STATE_DIR/$1"; }

# --- 2) image ch-compute (murah, tiap tick) --------------------------------
if ! sudo -n docker image inspect ch-compute:latest >/dev/null 2>&1; then
  if cooldown_ok image_alert_last 21600; then
    mark image_alert_last
    {
      echo "Image docker ch-compute:latest TIDAK DITEMUKAN di $(hostname)."
      echo "Kemungkinan terhapus oleh 'docker prune' user lain (pernah terjadi)."
      echo "Dampak: SEMUA kernel interaktif & job batch baru akan GAGAL start."
      echo
      echo "Perbaikan (± 10 menit build):"
      echo "  cd $BASE/backend && cp requirements-compute.txt docker/ && \\"
      echo "  sudo -n docker build -t ch-compute:latest -f docker/ch-compute.Dockerfile docker"
    } | "$PY" "$MAIL" "[PENTING] Image ch-compute HILANG - kernel/job akan gagal"
  fi
fi

# --- 2a) berkas repo hilang massal (murah, tiap tick) ----------------------
# 2026-09-13: 121 berkas backend/ lenyap dalam hitungan detik; penyebabnya tak
# pernah ditemukan karena tak ada yang memantau. Di sini kita tak mencegah, tapi
# memastikan kejadian serupa KETAHUAN dalam <=5 menit, lengkap dgn jam kejadian.
HILANG=$(cd "$BASE" && git status --porcelain 2>/dev/null | grep -c '^ D ' || true)
if [ "${HILANG:-0}" -ge 20 ]; then
  if cooldown_ok repo_missing_last 3600; then
    mark repo_missing_last
    {
      echo "$HILANG berkas terlacak git HILANG dari $BASE pada $(date '+%F %T')."
      echo "Layanan mungkin MASIH berjalan (kode sudah termuat di memori),"
      echo "tetapi restart berikutnya akan GAGAL."
      echo
      echo "Pulihkan: cd $BASE && git restore ."
      echo "Berkas TAK terlacak git (backend/.env, .venv, _jobs) TIDAK ikut pulih;"
      echo "ambil .env dari arsip: ~/.computehub/backups/ -> entri ./env.backup"
      echo
      echo "Proses yang sedang berjalan saat terdeteksi:"
      ps -eo pid,etimes,cmd --sort=-etimes 2>/dev/null | grep -iE "rm |rsync|git |find " | grep -v grep | head -5
    } | "$PY" "$MAIL" "[DARURAT] $HILANG berkas repo ComputeHub hilang"
  fi
fi

# --- 2b) CLI VS Code untuk Devbox (1x per minggu) --------------------------
# VS Code di laptop pengguna auto-update; bila CLI di server tertinggal jauh,
# koneksi tunnel bisa gagal. Perbarui berkala & selalu VERIFIKASI biner baru
# sebelum menimpa (unduh gagal TIDAK boleh merusak CLI yang sudah jalan).
CLI_DIR="${COMPUTEHUB_DEVBOX_CLI_DIR:-$HOME/.computehub/devbox/cli}"
if [ -x "$CLI_DIR/code" ] && cooldown_ok devbox_cli_last 604800; then
  mark devbox_cli_last
  TMPD=$(mktemp -d)
  if curl -fsSL --max-time 120 \
      "https://update.code.visualstudio.com/latest/cli-linux-x64/stable" \
      -o "$TMPD/cli.tar.gz" \
     && tar -xzf "$TMPD/cli.tar.gz" -C "$TMPD" 2>/dev/null \
     && [ -x "$TMPD/code" ] \
     && baru=$("$TMPD/code" --version 2>/dev/null | head -1) \
     && [ -n "$baru" ]; then
    lama=$("$CLI_DIR/code" --version 2>/dev/null | head -1)
    if [ "$baru" != "$lama" ]; then
      # Devbox yang sedang menyala tetap memakai biner lama sampai dinyalakan ulang.
      install -m 0755 "$TMPD/code" "$CLI_DIR/code" \
        && echo "$(date -Is) CLI devbox: $lama -> $baru" >> "$STATE_DIR/devbox_cli.log"
    fi
  fi
  rm -rf "$TMPD"
fi

# --- 3) kesegaran backup offsite (1x per hari) ------------------------------
if [ -x "$RCLONE" ] && cooldown_ok offsite_check_last 86400; then
  mark offsite_check_last
  newest=$("$RCLONE" lsjson --files-only gdrive:ComputeHub-Backups 2>/dev/null \
    | "$PY" -c "
import sys, json, datetime as dt
try:
    items = json.load(sys.stdin)
    ts = max(dt.datetime.fromisoformat(i['ModTime'].replace('Z','+00:00')) for i in items)
    print(int((dt.datetime.now(dt.timezone.utc) - ts).total_seconds()))
except Exception:
    print(-1)")
  if [ "${newest:--1}" -lt 0 ] || [ "$newest" -gt 172800 ]; then
    if cooldown_ok offsite_alert_last 86400; then
      mark offsite_alert_last
      {
        echo "Backup offsite di Google Drive TIDAK SEGAR (atau tidak terbaca)."
        if [ "${newest:--1}" -ge 0 ]; then
          echo "File terbaru berumur $((newest / 3600)) jam (ambang 48 jam)."
        else
          echo "rclone gagal membaca folder gdrive:ComputeHub-Backups."
        fi
        echo
        echo "Kemungkinan: token OAuth kedaluwarsa / client_id bersama rclone"
        echo "pensiun / kuota Drive penuh. Cek manual:"
        echo "  $RCLONE lsl gdrive:ComputeHub-Backups"
        echo "  journalctl --user -u computehub-backup.service -n 30"
      } | "$PY" "$MAIL" "[PENTING] Backup offsite Drive tidak segar"
    fi
  fi
fi

# --- 1) health backend (terakhir, karena bisa exec email juga) --------------
for _ in 1 2 3; do
  if curl -sf -m 8 http://127.0.0.1:8088/health >/dev/null 2>&1; then
    exit 0
  fi
  sleep 5
done

if cooldown_ok health_alert_last 7200; then
  mark health_alert_last
  exec "$PY" "$BASE/scripts/notify_failure.py" computehub.service unhealthy
fi
exit 0
