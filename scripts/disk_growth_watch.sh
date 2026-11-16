#!/usr/bin/env bash
# Pencatat pertumbuhan disk root (dijalankan timer tiap 10 menit).
#
# Dua lapis:
#  1. TREN (selalu): 1 baris CSV per tick -> waktu, sisa GB, % terpakai, laju GB/jam.
#     File per bulan: ~/.computehub/logs/disk/tren-YYYY-MM.csv (~50 KB/hari).
#  2. LONJAKAN (hanya bila sisa disk turun >= SPIKE_GB dalam ~1 jam): rekam
#     "siapa pelakunya" -> proses penulis terbesar (pidstat -d), log container
#     docker yang besar, container yang baru dibuat -> file
#     ~/.computehub/logs/disk/lonjakan/YYYYmmdd-HHMM.txt, plus kabar Telegram.
#
# Latar: 16 Nov 2026 subuh disk turun ~130 GB/jam karena `docker run` pg_dump
# yang stdout-nya ikut tertulis ke log json docker. Alert lama hanya bilang
# "disk menipis" tanpa pelaku; skrip ini menyimpan buktinya saat kejadian.
# Ringan: tidak memakai `du` ke /home; pelaku dicari dari statistik I/O proses.
# Data hanya disimpan di server (repo publik), dihapus otomatis > 90 hari.

set -u
BASE=/home/muhammadrizalharis/DATA_ICAL/SERVER-KAMPUS
STATE_DIR="$HOME/.computehub"
LOG_DIR="$STATE_DIR/logs/disk"
SPIKE_DIR="$LOG_DIR/lonjakan"
HIST="$STATE_DIR/disk-growth.hist"     # epoch avail_bytes, ~2 jam terakhir
SPIKE_GB="${DISK_SPIKE_GB:-50}"        # ambang lonjakan per ~1 jam
KEEP_DAYS=90
mkdir -p "$SPIKE_DIR"

now=$(date +%s)
read -r avail size < <(df -B1 --output=avail,size / | tail -1)
used_pct=$(( (size - avail) * 100 / size ))
avail_gb=$(awk -v a="$avail" 'BEGIN{printf "%.1f", a/1e9}')

# Riwayat singkat untuk hitung laju; simpan hanya 2 jam terakhir.
echo "$now $avail" >> "$HIST"
awk -v t="$now" '$1 >= t-7200' "$HIST" > "$HIST.tmp" && mv "$HIST.tmp" "$HIST"

# Bandingkan dengan titik tertua dalam jendela 50-70 menit lalu (toleran jitter timer).
ref=$(awk -v t="$now" '$1 <= t-3000 && $1 >= t-4200 {print; exit}' "$HIST")
drop_gb="" rate=""
if [ -n "$ref" ]; then
  read -r ref_t ref_a <<<"$ref"
  drop_gb=$(awk -v a="$ref_a" -v b="$avail" 'BEGIN{printf "%.1f", (a-b)/1e9}')
  rate=$(awk -v d="$drop_gb" -v s="$((now - ref_t))" 'BEGIN{printf "%.1f", d*3600/s}')
fi

TREN="$LOG_DIR/tren-$(date +%Y-%m).csv"
[ -f "$TREN" ] || echo "waktu,sisa_gb,terpakai_pct,turun_gb_per_jam" > "$TREN"
echo "$(date '+%F %T'),$avail_gb,$used_pct,${rate:-}" >> "$TREN"

find "$LOG_DIR" -type f -mtime +"$KEEP_DAYS" -delete 2>/dev/null

[ -n "$drop_gb" ] || exit 0
awk -v d="$drop_gb" -v s="$SPIKE_GB" 'BEGIN{exit !(d >= s)}' || exit 0

# --- Lonjakan: rekam pelaku (maks 1x per 30 menit) ---------------------------
last=$(cat "$STATE_DIR/disk_spike_last" 2>/dev/null || echo 0)
[ $((now - last)) -ge 1800 ] || exit 0
echo "$now" > "$STATE_DIR/disk_spike_last"

OUT="$SPIKE_DIR/$(date +%Y%m%d-%H%M).txt"
{
  echo "LONJAKAN DISK $(hostname) $(date '+%F %T')"
  echo "Sisa disk turun $drop_gb GB dalam ~1 jam (laju $rate GB/jam). Sisa sekarang $avail_gb GB ($used_pct% terpakai)."
  echo
  echo "== Proses penulis terbesar (sampel 10 detik, kB_wr/s) =="
  # Kolom (waktu ISO 1 kolom): Time USER PID kB_rd/s kB_wr/s kB_ccwr/s iodelay Command
  S_TIME_FORMAT=ISO LC_ALL=C sudo -n --preserve-env=S_TIME_FORMAT,LC_ALL pidstat -d -h -U -l 10 1 2>/dev/null \
    | awk '$1 !~ /^(#|Linux)/ && NF >= 8 && $5+0 > 0' | sort -k5 -nr | head -10 \
    | awk '{printf "%-14s pid=%-8s tulis=%8.1f MB/s  ", $2, $3, $5/1024; for(i=8;i<=NF;i++) printf "%s ", $i; print ""}' \
    | cut -c1-220
  echo
  echo "== Log container docker > 1 GB (stdout container ikut tertulis di sini) =="
  sudo -n find /var/lib/docker/containers -name '*-json.log' -size +1G -printf '%s %p\n' 2>/dev/null \
    | sort -nr | head -5 | while read -r sz p; do
        id=$(basename "$(dirname "$p")")
        name=$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null | tr -d /)
        printf "%8.1f GB  %s (%s)\n" "$(awk -v s="$sz" 'BEGIN{print s/1e9}')" "${name:-?}" "${id:0:12}"
      done
  echo
  echo "== Container dibuat < 2 jam terakhir =="
  docker ps -a --format '{{.CreatedAt}}|{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null \
    | while IFS='|' read -r c n i s; do
        ct=$(date -d "${c% +*}" +%s 2>/dev/null || echo 0)
        [ $((now - ct)) -le 7200 ] && echo "$n  image=$i  status=$s  dibuat=${c% +*}"
      done
  echo
  echo "== Service yang sedang berjalan sekali-jalan (kandidat backup/job) =="
  systemctl list-units --type=service --state=activating --no-legend 2>/dev/null | head -10
  systemctl --user list-units --type=service --state=activating --no-legend 2>/dev/null | head -10
} > "$OUT" 2>&1

python3 "$BASE/scripts/ops_event.py" --kind watchdog --status warn \
  --title "Lonjakan disk: turun $drop_gb GB/jam" \
  --data "{\"drop_gb\":$drop_gb,\"avail_gb\":$avail_gb}" --source disk_growth_watch.sh >/dev/null 2>&1 || true
"$BASE/scripts/notify_telegram.py" "⚠️ Lonjakan disk $(hostname)" - < "$OUT" >/dev/null 2>&1 || true
exit 0
