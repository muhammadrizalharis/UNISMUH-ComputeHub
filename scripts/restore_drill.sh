#!/usr/bin/env bash
# RESTORE DRILL — uji pulih backup secara otomatis (bulanan).
# "Backup yang tidak pernah diuji pulih = belum tentu backup."
#
# Alur (menguji SELURUH jalur pemulihan, termasuk enkripsi):
#   1. Ambil arsip TERENKRIPSI terbaru (~/.computehub/backups_enc/*.gpg)
#   2. Dekripsi gpg (passphrase ~/.computehub/backup.pass) -> tar.gz
#   3. Ekstrak db.sql
#   4. Restore ke Postgres SEMENTARA (container ch-restore-drill, tanpa port,
#      image postgres:17.7-alpine yang sudah ada) — DB produksi TIDAK disentuh
#   5. Validasi: jumlah tabel & jumlah baris users > 0
#   6. Bersihkan container + laporkan hasil (sukses/gagal/berhenti tak terduga)
#      ke admin lewat email DAN Telegram (mail_admin.py mengirim keduanya)
#
# Pemakaian: restore_drill.sh [--archive NAMA|PATH] [--request-id ID]
#   (tanpa argumen = arsip terenkripsi terbaru; dipanggil timer bulanan dan tombol
#   "Uji pulih" di web lewat scripts/ops_agent.py)
set -u

ARCHIVE_ARG=""; REQUEST_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --archive) ARCHIVE_ARG="$2"; shift ;;
    --request-id) REQUEST_ID="$2"; shift ;;
    *) echo "opsi tidak dikenal: $1" >&2; exit 2 ;;
  esac
  shift
done

BASE="$(cd "$(dirname "$0")/.." && pwd)"
ENC_DIR="${COMPUTEHUB_BACKUP_ENC_DIR:-$HOME/.computehub/backups_enc}"
PASSFILE="$HOME/.computehub/backup.pass"
RCLONE_BIN="${RCLONE_BIN:-$HOME/bin/rclone}"
RCLONE_REMOTE="${COMPUTEHUB_RCLONE_REMOTE:-gdrive:ComputeHub-Backups}"
PY="$BASE/backend/.venv/bin/python"
MAIL="$BASE/scripts/mail_admin.py"
CTR="ch-restore-drill"
IMG="postgres:17.7-alpine"
LOG="$(mktemp)"
TMP="$(mktemp -d)"
DILAPORKAN=0   # penjaga: drill tidak boleh pernah selesai tanpa kabar

# Email+Telegram ke admin; dimatikan oleh COMPUTEHUB_NO_OPS_EVENT=1 (uji sandbox).
kabar() { [ "${COMPUTEHUB_NO_OPS_EVENT:-0}" = 1 ] && return 0; "$PY" "$MAIL" "$1" "$2" >/dev/null 2>&1 || true; }

cleanup() {
  sudo -n docker rm -f "$CTR" >/dev/null 2>&1
  if [ "$DILAPORKAN" -eq 0 ]; then
    echo "HASIL: TIDAK JELAS — skrip berhenti sebelum sempat menyimpulkan." >>"$LOG"
    kabar "[PENTING] Restore drill backup BERHENTI TAK TERDUGA" "$LOG"
  fi
  rm -rf "$TMP" "$LOG"
}
trap cleanup EXIT

say() { echo "$1" | tee -a "$LOG"; }

# Bukti permanen di DB (tampil di Pengaturan > Cadangan & Pemulihan); best-effort.
OPS_EVENT="$BASE/scripts/ops_event.py"
DRILL_START="$(date +%s)"
catat() {  # catat <status> <judul> <json-data>
  [ "${COMPUTEHUB_NO_OPS_EVENT:-0}" = 1 ] && return 0
  [ -f "$OPS_EVENT" ] || return 0
  python3 "$OPS_EVENT" --kind restore_drill --status "$1" --title "$2" --data "$3" \
    --detail-file "$LOG" --duration "$(( $(date +%s) - DRILL_START ))" \
    --source restore_drill.sh >/dev/null 2>&1 || true
}

fail() {
  say "HASIL: GAGAL — $1"
  DILAPORKAN=1
  catat fail "Restore drill GAGAL: $1" "{\"archive\":\"$(basename "${LATEST:-}")\",\"request_id\":\"$REQUEST_ID\"}"
  kabar "[PENTING] Restore drill backup GAGAL" "$LOG"
  exit 0   # best-effort: jangan bikin unit failed berulang
}

say "Restore drill $(date '+%Y-%m-%d %H:%M:%S') di $(hostname)${REQUEST_ID:+ (permintaan web $REQUEST_ID)}"

# 1) arsip: pilihan dari web (nama di folder terenkripsi, path, atau nama arsip di Drive
#    yang diunduh dulu — arsip penuh kini hanya tersimpan di Drive) atau terenkripsi terbaru
if [ -n "$ARCHIVE_ARG" ]; then
  case "$ARCHIVE_ARG" in */*) LATEST="$ARCHIVE_ARG" ;; *) LATEST="$ENC_DIR/$ARCHIVE_ARG" ;; esac
  if [ ! -f "$LATEST" ] && [[ "$ARCHIVE_ARG" =~ ^computehub(-core)?-[0-9]{8}-[0-9]{6}\.tar\.gz\.gpg$ ]] && [ -x "$RCLONE_BIN" ]; then
    say "Arsip tidak ada di server; mengunduh $ARCHIVE_ARG dari $RCLONE_REMOTE …"
    if "$RCLONE_BIN" copy "$RCLONE_REMOTE" "$TMP/offsite" --include "$ARCHIVE_ARG" --include "$ARCHIVE_ARG.sha256" --timeout 60m --retries 2 -q 2>>"$LOG"; then
      LATEST="$TMP/offsite/$ARCHIVE_ARG"
      if [ -f "$LATEST.sha256" ] && [ "$(cut -d' ' -f1 "$LATEST.sha256")" != "$(sha256sum "$LATEST" | cut -d' ' -f1)" ]; then
        fail "sha256 arsip dari Drive TIDAK cocok dengan sidecar-nya"
      fi
      say "Unduhan selesai, integritas ${LATEST##*/} $( [ -f "$LATEST.sha256" ] && echo 'cocok dengan sha256' || echo '(tanpa sidecar sha256)')"
    fi
  fi
  [ -f "$LATEST" ] || fail "arsip tidak ditemukan: $ARCHIVE_ARG"
else
  LATEST="$(ls -1t "$ENC_DIR"/computehub-*.tar.gz.gpg 2>/dev/null | head -1)"
fi
[ -n "$LATEST" ] || fail "tidak ada arsip terenkripsi di $ENC_DIR"
[ -f "$PASSFILE" ] || fail "passphrase $PASSFILE tidak ada"
say "Arsip: $(basename "$LATEST") ($(du -h "$LATEST" | cut -f1))"

# 2) dekripsi
if ! gpg --batch --quiet --passphrase-file "$PASSFILE" -d "$LATEST" > "$TMP/b.tar.gz" 2>>"$LOG"; then
  fail "dekripsi gpg gagal"
fi
say "Dekripsi OK ($(du -h "$TMP/b.tar.gz" | cut -f1))"

# 3) ekstrak db.sql saja
if ! tar -xzf "$TMP/b.tar.gz" -C "$TMP" ./db.sql 2>>"$LOG"; then
  fail "db.sql tidak ditemukan di arsip"
fi
say "db.sql: $(wc -l < "$TMP/db.sql") baris"

# 4) postgres sementara (tanpa publish port; nama ch-* milik kita)
sudo -n docker rm -f "$CTR" >/dev/null 2>&1
if ! sudo -n docker run -d --name "$CTR" -e POSTGRES_PASSWORD=drill "$IMG" >/dev/null 2>>"$LOG"; then
  fail "gagal start container $CTR"
fi
READY=0
for _ in $(seq 1 30); do
  if sudo -n docker exec "$CTR" pg_isready -U postgres -q 2>/dev/null; then READY=1; break; fi
  sleep 1
done
[ "$READY" = 1 ] || fail "postgres drill tidak siap dalam 30 dtk"

# peran 'computehub' dibuat dulu supaya ALTER ... OWNER di dump tidak berisik
sudo -n docker exec "$CTR" psql -U postgres -q -c "CREATE ROLE computehub;" >/dev/null 2>&1
if ! sudo -n docker exec -i "$CTR" psql -U postgres -q -v ON_ERROR_STOP=0 < "$TMP/db.sql" >>"$LOG" 2>&1; then
  fail "psql restore error fatal"
fi

# 5) validasi isi
TABLES="$(sudo -n docker exec "$CTR" psql -U postgres -tA -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>>"$LOG" | tr -d '[:space:]')"
USERS="$(sudo -n docker exec "$CTR" psql -U postgres -tA -c \
  "SELECT count(*) FROM users;" 2>>"$LOG" | tr -d '[:space:]')"
JOBS="$(sudo -n docker exec "$CTR" psql -U postgres -tA -c \
  "SELECT count(*) FROM jobs;" 2>>"$LOG" | tr -d '[:space:]')"
say "Validasi: tabel=$TABLES users=$USERS jobs=$JOBS"
[ "${TABLES:-0}" -ge 5 ] 2>/dev/null || fail "jumlah tabel janggal ($TABLES)"
[ "${USERS:-0}" -ge 1 ] 2>/dev/null || fail "tabel users kosong"

say "HASIL: SUKSES — backup terbukti BISA DIPULIHKAN (arsip $(basename "$LATEST"); $TABLES tabel, $USERS user, $JOBS job)."
DILAPORKAN=1
catat ok "Restore drill SUKSES: backup terbukti bisa dipulihkan" \
  "{\"archive\":\"$(basename "$LATEST")\",\"tables\":${TABLES:-0},\"users\":${USERS:-0},\"jobs\":${JOBS:-0},\"request_id\":\"$REQUEST_ID\"}"
kabar "Restore drill backup SUKSES (${TABLES} tabel, ${USERS} user)" "$LOG"
