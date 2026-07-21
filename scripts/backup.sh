#!/usr/bin/env bash
# Backup data ComputeHub: workspace persisten /persist (kerja mahasiswa) + konfigurasi
# (.env) + dump DB (opsional, bila pg_dump tersedia). Aman dijalankan kapan saja; dipakai
# oleh systemd --user timer (computehub-backup.timer) secara terjadwal.
#
# Variabel opsional:
#   COMPUTEHUB_ROOT        (default: $HOME/DATA_ICAL/SERVER-KAMPUS)
#   COMPUTEHUB_BACKUP_DIR  (default: $HOME/.computehub/backups)
#   COMPUTEHUB_BACKUP_KEEP (default: 14  — jumlah arsip terbaru yang disimpan)
set -euo pipefail

ROOT="${COMPUTEHUB_ROOT:-$HOME/DATA_ICAL/SERVER-KAMPUS}"
DATA="$HOME/.computehub/users"
DEST="${COMPUTEHUB_BACKUP_DIR:-$HOME/.computehub/backups}"
KEEP="${COMPUTEHUB_BACKUP_KEEP:-14}"

mkdir -p "$DEST"
chmod 700 "$DEST" 2>/dev/null || true   # backup berisi .env -> batasi akses
TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$DEST/computehub-$TS.tar.gz"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1) Workspace persisten per-user (kerja mahasiswa: file, notebook, paket pip --user).
if [ -d "$DATA" ]; then cp -a "$DATA" "$TMP/users"; else mkdir -p "$TMP/users"; fi

# 2) Konfigurasi (.env) — agar bisa pulih utuh.
[ -f "$ROOT/backend/.env" ] && cp "$ROOT/backend/.env" "$TMP/env.backup" || true

# 3) Dump database (logical). Prioritas: container Postgres lokal (ComputeHub-postgres,
#    punya pg_dump di dalamnya) -> fallback pg_dump di host (mis. DB remote/lain).
CH_PG_CONTAINER="${COMPUTEHUB_PG_CONTAINER:-ComputeHub-postgres}"
DB_DUMPED=0
# (a) DB lokal via container (kasus utama: DB di server kampus).
if sudo -n docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CH_PG_CONTAINER"; then
  # pg_dump di DALAM container pakai POSTGRES_USER/DB milik container (selalu benar).
  if sudo -n docker exec "$CH_PG_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
       > "$TMP/db.sql" 2>"$TMP/db.err"; then
    echo "DB dump OK via container $CH_PG_CONTAINER ($(wc -l < "$TMP/db.sql") baris)."
    DB_DUMPED=1
  else
    echo "(dump via container $CH_PG_CONTAINER gagal — lihat db.err di arsip)"
  fi
fi
# (b) Fallback: pg_dump di host memakai DATABASE_URL (mis. DB remote).
if [ "$DB_DUMPED" = 0 ] && command -v pg_dump >/dev/null 2>&1 && [ -f "$ROOT/backend/.env" ]; then
  URL="$(grep -E '^DATABASE_URL=' "$ROOT/backend/.env" | head -1 | cut -d= -f2- || true)"
  URL="${URL/+asyncpg/}"   # pg_dump butuh skema postgresql:// (bukan +asyncpg)
  if [ -n "${URL:-}" ] && pg_dump "$URL" > "$TMP/db.sql" 2>"$TMP/db.err"; then
    echo "DB dump OK via pg_dump host ($(wc -l < "$TMP/db.sql") baris)."
    DB_DUMPED=1
  fi
fi
[ "$DB_DUMPED" = 0 ] && echo "(DB dump dilewati — tak ada jalur pg_dump yang tersedia)"

tar -czf "$ARCHIVE" -C "$TMP" .
echo "Backup dibuat: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# Rotasi: simpan KEEP arsip terbaru, sisanya dihapus.
mapfile -t OLD < <(ls -1t "$DEST"/computehub-*.tar.gz 2>/dev/null | tail -n +"$((KEEP + 1))")
if [ "${#OLD[@]}" -gt 0 ]; then
  rm -f "${OLD[@]}"
  echo "Hapus ${#OLD[@]} arsip lama (simpan $KEEP terbaru)."
fi
echo "Total arsip: $(ls -1 "$DEST"/computehub-*.tar.gz 2>/dev/null | wc -l)."

# ---------------------------------------------------------------------------
# SALINAN OFFSITE TERENKRIPSI (jaga-jaga server bermasalah total):
#  1) Enkripsi arsip (gpg simetris AES256, passphrase di ~/.computehub/backup.pass,
#     chmod 600). Hasil .gpg di $DEST_ENC (rotasi sama dengan lokal).
#  2) Upload ke Google Drive via rclone remote "gdrive" (scope drive.file =
#     token HANYA bisa akses file buatan rclone, bukan seluruh Drive).
#     `rclone sync` -> retensi di Drive otomatis mengikuti rotasi lokal.
# Semua BEST-EFFORT: tanpa passphrase/rclone/internet -> backup lokal tetap jalan.
# ---------------------------------------------------------------------------
PASSFILE="$HOME/.computehub/backup.pass"
DEST_ENC="${COMPUTEHUB_BACKUP_ENC_DIR:-$HOME/.computehub/backups_enc}"
RCLONE_BIN="${RCLONE_BIN:-$HOME/bin/rclone}"
# Folder tujuan di Drive DIBUAT otomatis oleh rclone (privat secara default).
# Scope drive.file: rclone HANYA bisa melihat/menulis folder buatannya sendiri —
# tak perlu (dan tak bisa) menyimpan link/ID folder manual mana pun.
RCLONE_REMOTE="${COMPUTEHUB_RCLONE_REMOTE:-gdrive:ComputeHub-Backups}"

if command -v gpg >/dev/null 2>&1 && [ -f "$PASSFILE" ]; then
  mkdir -p "$DEST_ENC" && chmod 700 "$DEST_ENC" 2>/dev/null || true
  ENC="$DEST_ENC/$(basename "$ARCHIVE").gpg"
  if gpg --batch --yes --symmetric --cipher-algo AES256 \
       --passphrase-file "$PASSFILE" -o "$ENC" "$ARCHIVE" 2>/dev/null; then
    echo "Terenkripsi: $ENC ($(du -h "$ENC" | cut -f1))"
    # Rotasi arsip terenkripsi (KEEP sama).
    mapfile -t OLDE < <(ls -1t "$DEST_ENC"/computehub-*.tar.gz.gpg 2>/dev/null | tail -n +"$((KEEP + 1))")
    [ "${#OLDE[@]}" -gt 0 ] && rm -f "${OLDE[@]}"
    # Upload bila remote rclone sudah dikonfigurasi (rclone config; sekali saja).
    if [ -x "$RCLONE_BIN" ] && "$RCLONE_BIN" listremotes 2>/dev/null | grep -q "^${RCLONE_REMOTE%%:*}:"; then
      if "$RCLONE_BIN" sync "$DEST_ENC" "$RCLONE_REMOTE" \
           --include 'computehub-*.tar.gz.gpg' --timeout 10m --retries 2 -q; then
        echo "Offsite OK: tersinkron ke $RCLONE_REMOTE ($("$RCLONE_BIN" lsf "$RCLONE_REMOTE" 2>/dev/null | wc -l) file)."
      else
        echo "(offsite GAGAL — jaringan/kuota? backup lokal tetap aman)"
      fi
    else
      echo "(offsite dilewati — rclone remote '${RCLONE_REMOTE%%:*}' belum dikonfigurasi; jalankan: rclone config)"
    fi
  else
    echo "(enkripsi gagal — offsite dilewati; backup lokal tetap aman)"
  fi
else
  echo "(enkripsi/offsite dilewati — gpg atau $PASSFILE tidak tersedia)"
fi
