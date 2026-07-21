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
#   6. Bersihkan container + email hasil (sukses/gagal) ke admin
set -u

BASE="$(cd "$(dirname "$0")/.." && pwd)"
ENC_DIR="${COMPUTEHUB_BACKUP_ENC_DIR:-$HOME/.computehub/backups_enc}"
PASSFILE="$HOME/.computehub/backup.pass"
PY="$BASE/backend/.venv/bin/python"
MAIL="$BASE/scripts/mail_admin.py"
CTR="ch-restore-drill"
IMG="postgres:17.7-alpine"
LOG="$(mktemp)"
TMP="$(mktemp -d)"

cleanup() {
  sudo -n docker rm -f "$CTR" >/dev/null 2>&1
  rm -rf "$TMP" "$LOG"
}
trap cleanup EXIT

say() { echo "$1" | tee -a "$LOG"; }

fail() {
  say "HASIL: GAGAL — $1"
  "$PY" "$MAIL" "[PENTING] Restore drill backup GAGAL" "$LOG"
  exit 0   # best-effort: jangan bikin unit failed berulang
}

say "Restore drill $(date '+%Y-%m-%d %H:%M:%S') di $(hostname)"

# 1) arsip terenkripsi terbaru
LATEST="$(ls -1t "$ENC_DIR"/computehub-*.tar.gz.gpg 2>/dev/null | head -1)"
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
"$PY" "$MAIL" "Restore drill backup SUKSES (${TABLES} tabel, ${USERS} user)" "$LOG"
