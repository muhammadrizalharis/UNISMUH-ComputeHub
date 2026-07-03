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
