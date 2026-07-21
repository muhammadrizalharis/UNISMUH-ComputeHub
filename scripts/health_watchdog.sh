#!/usr/bin/env bash
# Watchdog ComputeHub (dijalankan timer tiap 5 menit). Tiga pemeriksaan:
#  1. /health backend (3x, jeda 5 dtk)  -> gagal semua = email (cooldown 2 jam)
#  2. Image docker ch-compute:latest    -> hilang (mis. kena docker prune user
#     lain, PERNAH TERJADI) = email (cooldown 6 jam); kernel/job akan gagal.
#  3. Kesegaran backup offsite di Drive -> dicek 1x/hari; file terbaru > 48 jam
#     = email (upload rclone berhenti diam-diam, mis. client_id pensiun).

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
