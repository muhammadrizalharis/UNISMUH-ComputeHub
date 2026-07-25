#!/usr/bin/env bash
# ============================================================================
# RESTORE PRODUKSI ComputeHub — pulihkan DB + workspace /persist dari backup.
#
# OPERASI DESTRUKTIF: menimpa database & file kerja saat ini. Aplikasi DIMATIKAN
# dulu (maintenance) selama restore, lalu dinyalakan kembali + cek kesehatan.
#
# PENGAMAN:
#   1. Wajib mengetik frasa konfirmasi.
#   2. Sebelum menimpa apa pun, skrip mengambil SNAPSHOT KONDISI SAAT INI
#      (dump DB + salin users) ke ~/.computehub/pre-restore-<timestamp>/ →
#      sehingga restore ini SENDIRI bisa di-rollback bila hasilnya tak sesuai.
#   3. Aplikasi dihentikan sebelum menyentuh DB/file, dinyalakan lagi di akhir.
#
# PEMAKAIAN:
#   scripts/restore.sh                 # pulihkan dari arsip TERENKRIPSI TERBARU
#   scripts/restore.sh /path/arsip.tar.gz[.gpg]   # dari arsip tertentu
#   RESTORE_ENV=1 scripts/restore.sh   # sekaligus pulihkan backend/.env (default: TIDAK)
#
# Sumber arsip:
#   - default: ~/.computehub/backups_enc/computehub-*.tar.gz.gpg (terbaru)
#   - bisa juga arahkan ke arsip tak-terenkripsi ~/.computehub/backups/*.tar.gz
#   - dari Google Drive: unduh dulu (rclone copy gdrive:ComputeHub-Backups/<file> .)
# ============================================================================
set -euo pipefail

ROOT="${COMPUTEHUB_ROOT:-$HOME/DATA_ICAL/SERVER-KAMPUS}"
DATA="$HOME/.computehub/users"
ENC_DIR="$HOME/.computehub/backups_enc"
PLAIN_DIR="$HOME/.computehub/backups"
PASSFILE="$HOME/.computehub/backup.pass"
SERVICE="computehub.service"
HEALTH_URL="https://computehub.lab.if.unismuh.ac.id/health"
PG_CONTAINER="${COMPUTEHUB_PG_CONTAINER:-ComputeHub-postgres}"
TS="$(date +%Y%m%d-%H%M%S)"
SNAP="$HOME/.computehub/pre-restore-$TS"

say() { echo -e "\033[1;36m[restore]\033[0m $*"; }
err() { echo -e "\033[1;31m[GAGAL]\033[0m $*" >&2; exit 1; }

# --- Pilih arsip ------------------------------------------------------------
ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
  ARCHIVE="$(ls -1t "$ENC_DIR"/computehub-*.tar.gz.gpg 2>/dev/null | head -1 || true)"
  [ -n "$ARCHIVE" ] || err "tak ada arsip terenkripsi di $ENC_DIR (atau berikan path sebagai argumen)"
fi
[ -f "$ARCHIVE" ] || err "arsip tidak ditemukan: $ARCHIVE"

say "Arsip sumber : $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
say "DB container : $PG_CONTAINER"
say "Workspace    : $DATA"
say "Snapshot     : $SNAP (kondisi SEKARANG, untuk rollback)"
[ "${RESTORE_ENV:-0}" = 1 ] && say "backend/.env : AKAN dipulihkan" || say "backend/.env : dilewati (pakai .env sekarang)"
echo

# --- Konfirmasi -------------------------------------------------------------
echo "Tindakan ini akan MENIMPA database & workspace saat ini dengan isi backup,"
echo "dan mematikan aplikasi sementara (maintenance)."
read -r -p 'Ketik persis  YA PULIHKAN  untuk lanjut: ' CONFIRM
[ "$CONFIRM" = "YA PULIHKAN" ] || err "dibatalkan (konfirmasi tidak cocok)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- 0) Dekripsi + ekstrak arsip -------------------------------------------
case "$ARCHIVE" in
  *.gpg)
    [ -f "$PASSFILE" ] || err "passphrase $PASSFILE tidak ada (untuk arsip terenkripsi)"
    say "Mendekripsi arsip…"
    gpg --batch --quiet --passphrase-file "$PASSFILE" -d "$ARCHIVE" > "$TMP/b.tar.gz" 2>/dev/null \
      || err "dekripsi gpg gagal (passphrase salah?)"
    ;;
  *.tar.gz) cp "$ARCHIVE" "$TMP/b.tar.gz" ;;
  *) err "format arsip tak dikenal (butuh .tar.gz atau .tar.gz.gpg)" ;;
esac
tar -xzf "$TMP/b.tar.gz" -C "$TMP" || err "ekstraksi arsip gagal"
[ -f "$TMP/db.sql" ] || err "db.sql tidak ada di arsip — arsip rusak?"
[ -d "$TMP/users" ] || say "(catatan: folder users/ tak ada di arsip — hanya DB yang dipulihkan)"
say "Ekstrak OK — db.sql $(wc -l < "$TMP/db.sql") baris."

# --- 1) Pastikan DB container hidup ----------------------------------------
sudo -n docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER" \
  || err "container DB '$PG_CONTAINER' tidak berjalan — start dulu sebelum restore"

# --- 2) SNAPSHOT kondisi sekarang (agar restore bisa di-rollback) ----------
say "Mengambil snapshot kondisi SEKARANG ke $SNAP …"
mkdir -p "$SNAP"
sudo -n docker exec "$PG_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "$SNAP/db-before.sql" 2>/dev/null || err "gagal snapshot DB sekarang (batalkan demi keamanan)"
if [ -d "$DATA" ]; then tar -czf "$SNAP/users-before.tar.gz" -C "$(dirname "$DATA")" "$(basename "$DATA")" || true; fi
[ -f "$ROOT/backend/.env" ] && cp "$ROOT/backend/.env" "$SNAP/env-before" || true
say "Snapshot siap ($(du -sh "$SNAP" | cut -f1)). Rollback nanti pakai file di sini."

# --- 3) MAINTENANCE: hentikan aplikasi -------------------------------------
say "Menghentikan aplikasi ($SERVICE)…"
systemctl --user stop "$SERVICE" || err "gagal menghentikan service"
sleep 2

# --- 4) Restore DATABASE (drop → create → muat dump) -----------------------
say "Memulihkan database…"
sudo -n docker exec "$PG_CONTAINER" sh -c '
  set -e
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '\''"'"'"'$POSTGRES_DB'"'"'"'\'' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";"
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"
' >/dev/null 2>&1 || { systemctl --user start "$SERVICE" || true; err "gagal reset database (aplikasi dinyalakan lagi; DB lama masih utuh sebelum drop? cek $SNAP/db-before.sql)"; }

if ! sudo -n docker exec -i "$PG_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -v ON_ERROR_STOP=0' < "$TMP/db.sql" > "$TMP/restore.log" 2>&1; then
  say "psql melaporkan sebagian error — cek $TMP/restore.log (sebagian error non-fatal wajar pada dump plain)."
fi
say "Database dimuat dari backup."

# --- 5) Restore WORKSPACE /persist -----------------------------------------
if [ -d "$TMP/users" ]; then
  say "Memulihkan workspace pengguna…"
  mkdir -p "$DATA"
  # rsync --delete: jadikan persis seperti backup. (Snapshot users-before sudah diambil.)
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$TMP/users/" "$DATA/"
  else
    rm -rf "$DATA"; mkdir -p "$DATA"; cp -a "$TMP/users/." "$DATA/"
  fi
  say "Workspace dipulihkan."
fi

# --- 6) Restore .env (opsional) --------------------------------------------
if [ "${RESTORE_ENV:-0}" = 1 ] && [ -f "$TMP/env.backup" ]; then
  cp "$TMP/env.backup" "$ROOT/backend/.env"
  say "backend/.env dipulihkan dari backup."
fi

# --- 7) Nyalakan kembali + cek kesehatan -----------------------------------
say "Menyalakan aplikasi kembali…"
systemctl --user start "$SERVICE" || err "service gagal start — cek: journalctl --user -u $SERVICE"
sleep 6
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HEALTH_URL" || echo 000)"
echo
if [ "$CODE" = 200 ]; then
  say "SELESAI ✅  Health $CODE — aplikasi pulih & normal."
else
  say "Aplikasi start, tapi health = $CODE. Cek log: journalctl --user -u $SERVICE -n 50"
fi
echo
echo "Snapshot kondisi sebelum restore: $SNAP"
echo "ROLLBACK (bila hasil tak sesuai):"
echo "  systemctl --user stop $SERVICE"
echo "  sudo docker exec $PG_CONTAINER sh -c 'psql -U \"\$POSTGRES_USER\" -d postgres -c \"DROP DATABASE IF EXISTS \\\"\$POSTGRES_DB\\\";\" && psql -U \"\$POSTGRES_USER\" -d postgres -c \"CREATE DATABASE \\\"\$POSTGRES_DB\\\" OWNER \\\"\$POSTGRES_USER\\\";\"'"
echo "  sudo docker exec -i $PG_CONTAINER sh -c 'psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"' < $SNAP/db-before.sql"
echo "  tar -xzf $SNAP/users-before.tar.gz -C $(dirname "$DATA")"
echo "  systemctl --user start $SERVICE"
