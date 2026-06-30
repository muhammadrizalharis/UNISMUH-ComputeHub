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

# 3) Dump database (OPSIONAL — hanya bila pg_dump ada & DATABASE_URL ada).
if command -v pg_dump >/dev/null 2>&1 && [ -f "$ROOT/backend/.env" ]; then
  URL="$(grep -E '^DATABASE_URL=' "$ROOT/backend/.env" | head -1 | cut -d= -f2- || true)"
  URL="${URL/+asyncpg/}"   # pg_dump butuh skema postgresql:// (bukan +asyncpg)
  if [ -n "${URL:-}" ]; then
    if pg_dump "$URL" > "$TMP/db.sql" 2>"$TMP/db.err"; then
      echo "DB dump OK ($(wc -l < "$TMP/db.sql") baris)."
    else
      echo "(pg_dump gagal — lewati; lihat db.err di arsip)"
    fi
  fi
else
  echo "(pg_dump tidak tersedia — DB di Supabase punya backup terkelola sendiri; lewati dump DB)"
fi

tar -czf "$ARCHIVE" -C "$TMP" .
echo "Backup dibuat: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# Rotasi: simpan KEEP arsip terbaru, sisanya dihapus.
mapfile -t OLD < <(ls -1t "$DEST"/computehub-*.tar.gz 2>/dev/null | tail -n +"$((KEEP + 1))")
if [ "${#OLD[@]}" -gt 0 ]; then
  rm -f "${OLD[@]}"
  echo "Hapus ${#OLD[@]} arsip lama (simpan $KEEP terbaru)."
fi
echo "Total arsip: $(ls -1 "$DEST"/computehub-*.tar.gz 2>/dev/null | wc -l)."
