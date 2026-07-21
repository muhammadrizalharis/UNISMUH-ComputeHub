#!/usr/bin/env bash
# Watchdog kesehatan ComputeHub: cek /health 3x (jeda 5 dtk). Semua gagal ->
# email peringatan ke admin (cooldown 2 jam agar tidak spam saat down lama).
# Dijalankan oleh computehub-watchdog.timer tiap 5 menit.

BASE=/home/muhammadrizalharis/DATA_ICAL/SERVER-KAMPUS
STATE="$HOME/.computehub/health_alert_last"
mkdir -p "$(dirname "$STATE")"

for _ in 1 2 3; do
  if curl -sf -m 8 http://127.0.0.1:8088/health >/dev/null 2>&1; then
    exit 0
  fi
  sleep 5
done

now=$(date +%s)
last=$(cat "$STATE" 2>/dev/null || echo 0)
if [ $((now - last)) -lt 7200 ]; then
  exit 0
fi
echo "$now" > "$STATE"
exec "$BASE/backend/.venv/bin/python" "$BASE/scripts/notify_failure.py" computehub.service unhealthy
