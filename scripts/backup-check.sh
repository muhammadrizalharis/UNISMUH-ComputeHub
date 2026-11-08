#!/usr/bin/env bash
# =============================================================================
#  backup-check.sh — PENGECEKAN RETENSI backup ComputeHub (READ-ONLY).
#
#  Menjawab: "apakah backup LAMA di Google Drive benar-benar dihapus & diganti
#  yang baru?" untuk ketiga tingkat:
#    - HARIAN/MINGGUAN/BULANAN : snapshot restic (repo gdrive:ComputeHub-Restic,
#      kebijakan 7 harian / 4 mingguan / 3 bulanan).
#    - ARSIP PENUH mingguan     : gdrive:ComputeHub-Backups (simpan 8 terbaru).
#    - ARSIP INTI (config/DB)   : gdrive:ComputeHub-Backups (hapus > 90 hari).
#
#  Skrip ini TIDAK mengubah apa pun (tidak forget/prune/delete) — hanya membaca
#  dari Drive lalu menilai apakah jumlah/umur masih dalam batas kebijakan.
#  Hasil ditulis ke JSON agar ditampilkan web (kartu "Cadangan & Pemulihan") dan
#  dicetak sebagai laporan PASS/WARN. Keluar 0 selalu (WARN tak menggagalkan
#  pipeline backup yang memanggilnya); verdict ada di JSON + teks.
#
#  Pakai:  scripts/backup-check.sh            # cek + tulis JSON + cetak laporan
#          scripts/backup-check.sh --quiet    # tanpa cetak (untuk dipanggil backup.sh)
# =============================================================================
set -uo pipefail

QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1
say() { [ "$QUIET" = 1 ] || printf '%s\n' "$*"; }

# --- Konfigurasi (default identik dengan backup.sh) --------------------------
RESTIC_BIN="${RESTIC_BIN:-$HOME/bin/restic}"
RCLONE_BIN="${RCLONE_BIN:-$HOME/bin/rclone}"
PASSFILE="${COMPUTEHUB_BACKUP_PASS:-$HOME/.computehub/backup.pass}"
RCLONE_REMOTE="${COMPUTEHUB_RCLONE_REMOTE:-gdrive:ComputeHub-Backups}"
RCLONE_REMOTE_NAME="${RCLONE_REMOTE%%:*}"
RESTIC_REPO="${COMPUTEHUB_RESTIC_REPO:-rclone:${RCLONE_REMOTE_NAME}:ComputeHub-Restic}"
STATUS_JSON="${COMPUTEHUB_RETENTION_JSON:-$HOME/.computehub/backup-retention.json}"

# Kebijakan retensi (samakan dengan backup.sh).
KEEP_DAILY="${COMPUTEHUB_KEEP_DAILY:-7}"
KEEP_WEEKLY="${COMPUTEHUB_KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${COMPUTEHUB_KEEP_MONTHLY:-3}"
DRIVE_TAR_KEEP="${COMPUTEHUB_DRIVE_TAR_KEEP:-8}"
DRIVE_CORE_KEEP_DAYS="${COMPUTEHUB_DRIVE_CORE_KEEP_DAYS:-90}"
# Plafon wajar jumlah snapshot restic = 7+4+3 + kelonggaran (snapshot "hari ini" yang
# belum kena forget, dsb). Di atas ini => dugaan regresi (mis. grouping rusak -> menumpuk).
SNAP_CEILING="${COMPUTEHUB_SNAP_CEILING:-$(( KEEP_DAILY + KEEP_WEEKLY + KEEP_MONTHLY + 6 ))}"

RESTIC_OPTS=()
case "$RESTIC_REPO" in
  rclone:*) RESTIC_OPTS=(-o "rclone.program=$RCLONE_BIN" \
            -o "rclone.args=serve restic --stdio --drive-use-trash=false") ;;
esac
restic_run() { "$RESTIC_BIN" "${RESTIC_OPTS[@]}" "$@"; }

now_epoch="$(date +%s)"
overall="ok"          # ok | warn | unknown
notes=()
downgrade() { [ "$overall" = "warn" ] || overall="$1"; [ "$1" = "warn" ] && overall="warn"; }

# --- 1) Snapshot restic (harian/mingguan/bulanan) ----------------------------
snap_total=-1; snap_days=-1; snap_oldest=""; snap_newest=""; restic_verdict="unknown"
if [ -x "$RESTIC_BIN" ] && [ -f "$PASSFILE" ] \
   && "$RCLONE_BIN" listremotes 2>/dev/null | grep -q "^${RCLONE_REMOTE_NAME}:"; then
  export RESTIC_PASSWORD_FILE="$PASSFILE" RESTIC_REPOSITORY="$RESTIC_REPO"
  snap_json="$(restic_run snapshots --tag computehub --json 2>/dev/null || true)"
  if [ -n "$snap_json" ]; then
    read -r snap_total snap_days snap_oldest snap_newest <<EOF
$(printf '%s' "$snap_json" | python3 -c '
import json,sys
try: s=json.load(sys.stdin)
except Exception: s=[]
days=sorted({x.get("time","")[:10] for x in s if x.get("time")})
print(len(s), len(days), days[0] if days else "", days[-1] if days else "")
' 2>/dev/null)
EOF
    if [ "${snap_total:-0}" -gt "$SNAP_CEILING" ]; then
      restic_verdict="warn"
      notes+=("Snapshot restic $snap_total > plafon wajar $SNAP_CEILING — retensi/forget mungkin tak jalan (cek --group-by host,tags).")
    else
      restic_verdict="ok"
    fi
  else
    restic_verdict="unknown"
    notes+=("Snapshot restic tak terbaca (repo/rclone tak siap saat pengecekan).")
  fi
else
  notes+=("restic/rclone/passfile tak tersedia — lewati pengecekan snapshot.")
fi

# --- 2) Arsip PENUH mingguan di Drive (simpan 8 terbaru) ---------------------
full_count=-1; full_verdict="unknown"
if "$RCLONE_BIN" listremotes 2>/dev/null | grep -q "^${RCLONE_REMOTE_NAME}:"; then
  full_count="$("$RCLONE_BIN" lsf "$RCLONE_REMOTE" --files-only \
    --include 'computehub-[0-9]*.tar.gz.gpg' 2>/dev/null | grep -c . || echo 0)"
  if [ "$full_count" -gt "$DRIVE_TAR_KEEP" ]; then
    full_verdict="warn"
    notes+=("Arsip penuh di Drive $full_count > batas $DRIVE_TAR_KEEP — yang lama belum terhapus.")
  else
    full_verdict="ok"
  fi
else
  notes+=("Drive tak siap — lewati pengecekan arsip penuh.")
fi

# --- 3) Arsip INTI (config/DB) di Drive (hapus > 90 hari) --------------------
core_count=-1; core_oldest_days=-1; core_verdict="unknown"
if "$RCLONE_BIN" listremotes 2>/dev/null | grep -q "^${RCLONE_REMOTE_NAME}:"; then
  core_js="$("$RCLONE_BIN" lsjson "$RCLONE_REMOTE" --files-only \
    --include 'computehub-core-*.tar.gz.gpg' 2>/dev/null || true)"
  if [ -n "$core_js" ]; then
    read -r core_count core_oldest_days <<EOF
$(printf '%s' "$core_js" | python3 -c '
import json,sys,datetime as d
try: a=json.load(sys.stdin)
except Exception: a=[]
now=d.datetime.now(d.timezone.utc)
ages=[]
for x in a:
    t=x.get("ModTime") or ""
    try:
        ts=d.datetime.fromisoformat(t.replace("Z","+00:00"))
        ages.append((now-ts).days)
    except Exception: pass
print(len(a), max(ages) if ages else 0)
' 2>/dev/null)
EOF
    if [ "${core_oldest_days:-0}" -gt "$DRIVE_CORE_KEEP_DAYS" ]; then
      core_verdict="warn"
      notes+=("Arsip inti tertua di Drive ${core_oldest_days} hari > ${DRIVE_CORE_KEEP_DAYS} — retensi inti belum jalan.")
    else
      core_verdict="ok"
    fi
  fi
fi

# --- Verdict keseluruhan -----------------------------------------------------
for v in "$restic_verdict" "$full_verdict" "$core_verdict"; do
  [ "$v" = "warn" ] && overall="warn"
done
if [ "$overall" != "warn" ]; then
  case "$restic_verdict$full_verdict$core_verdict" in
    *unknown*) overall="unknown" ;;
    *) overall="ok" ;;
  esac
fi

# --- Tulis JSON status (dibaca backend untuk kartu web) ----------------------
notes_json="$(printf '%s\n' "${notes[@]:-}" | python3 -c 'import json,sys; print(json.dumps([l for l in sys.stdin.read().splitlines() if l.strip()]))')"
mkdir -p "$(dirname "$STATUS_JSON")"
cat > "$STATUS_JSON" <<EOF
{
  "generated_at": $(python3 -c 'import datetime; print("\""+datetime.datetime.now(datetime.timezone.utc).isoformat()+"\"")'),
  "generated_epoch": $now_epoch,
  "overall": "$overall",
  "restic": {
    "verdict": "$restic_verdict",
    "snapshots": $snap_total,
    "unique_days": $snap_days,
    "oldest": "${snap_oldest}",
    "newest": "${snap_newest}",
    "ceiling": $SNAP_CEILING,
    "keep_daily": $KEEP_DAILY, "keep_weekly": $KEEP_WEEKLY, "keep_monthly": $KEEP_MONTHLY
  },
  "full_archive": {
    "verdict": "$full_verdict",
    "count": $full_count,
    "keep": $DRIVE_TAR_KEEP
  },
  "core_archive": {
    "verdict": "$core_verdict",
    "count": $core_count,
    "oldest_days": $core_oldest_days,
    "keep_days": $DRIVE_CORE_KEEP_DAYS
  },
  "notes": $notes_json
}
EOF
chmod 600 "$STATUS_JSON" 2>/dev/null || true

# --- Laporan manusia ---------------------------------------------------------
badge() { case "$1" in ok) echo "✅ OK";; warn) echo "⚠️  PERLU DICEK";; *) echo "❔ tak diketahui";; esac; }
say "== Pengecekan retensi backup ComputeHub =="
say "Snapshot restic (harian/mingguan/bulanan): $(badge "$restic_verdict")"
say "  total $snap_total snapshot (${snap_days} hari unik; $snap_oldest → $snap_newest); plafon wajar $SNAP_CEILING"
say "  kebijakan: simpan $KEEP_DAILY harian / $KEEP_WEEKLY mingguan / $KEEP_MONTHLY bulanan — sisanya dihapus."
say "Arsip penuh mingguan di Drive: $(badge "$full_verdict")"
say "  $full_count arsip (batas $DRIVE_TAR_KEEP terbaru; yang lebih lama dihapus)."
say "Arsip inti (config/DB) di Drive: $(badge "$core_verdict")"
say "  $core_count arsip; tertua ${core_oldest_days} hari (batas ${DRIVE_CORE_KEEP_DAYS} hari)."
say "Verdict keseluruhan: $(badge "$overall")"
if [ "${#notes[@]}" -gt 0 ] && [ -n "${notes[0]:-}" ]; then
  say "Catatan:"; for n in "${notes[@]}"; do [ -n "$n" ] && say "  - $n"; done
fi
say "Status ditulis: $STATUS_JSON"
exit 0
