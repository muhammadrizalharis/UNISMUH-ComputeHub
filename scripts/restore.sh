#!/usr/bin/env bash
# ============================================================================
# RESTORE PRODUKSI ComputeHub — pulihkan DB + workspace /persist dari backup.
#
# OPERASI DESTRUKTIF: menimpa database & file kerja saat ini. Aplikasi DIMATIKAN
# dulu selama restore, lalu dinyalakan kembali + cek kesehatan.
#
# PENGAMAN:
#   1. Wajib konfirmasi: interaktif mengetik frasa, atau non-interaktif (--yes) dengan
#      env COMPUTEHUB_RESTORE_CONFIRM="YA PULIHKAN" (dipakai agen web ops_agent.py).
#   2. Sebelum menimpa apa pun, skrip mengambil SNAPSHOT KONDISI SAAT INI
#      (dump DB + salin users) ke ~/.computehub/pre-restore-<timestamp>/ →
#      restore ini SENDIRI bisa di-rollback (dari CLI maupun web: sumber "Titik rollback").
#   3. Integritas arsip dicocokkan dengan <arsip>.sha256 bila ada.
#   4. Aplikasi dihentikan sebelum menyentuh DB/file, dinyalakan lagi di akhir.
#
# PEMAKAIAN:
#   scripts/restore.sh                               # interaktif, arsip terenkripsi TERBARU
#   scripts/restore.sh /path/arsip.tar.gz[.gpg]      # interaktif, arsip tertentu
#   scripts/restore.sh --yes --archive NAMA|PATH [--scope db,users,env] [--stop-sessions]
#   scripts/restore.sh --yes --snapshot <id-restic>  [--scope ...]      # dari snapshot restic
#   scripts/restore.sh --yes --pre-restore pre-restore-<ts> [--scope ...] # rollback dari titik sebelum restore
#   scripts/restore.sh --yes --offsite NAMA.tar.gz.gpg                   # unduh dari Drive dulu (rclone)
#   Opsi lain: --request-id ID (jejak permintaan web), --no-service (sandbox: jangan stop/start unit)
#   RESTORE_ENV=1 setara --scope ...,env (default: .env TIDAK dipulihkan).
#
# Knob sandbox (uji tanpa menyentuh produksi): COMPUTEHUB_PG_CONTAINER, COMPUTEHUB_DATA_DIR,
#   COMPUTEHUB_RESTORE_SERVICE (kosong = tidak stop/start), COMPUTEHUB_NO_OPS_EVENT=1,
#   COMPUTEHUB_SNAPSHOT_BASE (folder pre-restore-*).
# ============================================================================
set -euo pipefail

ROOT="${COMPUTEHUB_ROOT:-$HOME/DATA_ICAL/SERVER-KAMPUS}"
DATA="${COMPUTEHUB_DATA_DIR:-$HOME/.computehub/users}"
ENC_DIR="${COMPUTEHUB_BACKUP_ENC_DIR:-$HOME/.computehub/backups_enc}"
PLAIN_DIR="${COMPUTEHUB_BACKUP_DIR:-$HOME/.computehub/backups}"
PASSFILE="$HOME/.computehub/backup.pass"
SERVICE="${COMPUTEHUB_RESTORE_SERVICE-computehub.service}"
HEALTH_LOCAL="http://127.0.0.1:8088/health"
PG_CONTAINER="${COMPUTEHUB_PG_CONTAINER:-ComputeHub-postgres}"
SNAP_BASE="${COMPUTEHUB_SNAPSHOT_BASE:-$HOME/.computehub}"
RESTIC_BIN="${RESTIC_BIN:-$HOME/bin/restic}"
RCLONE_BIN="${RCLONE_BIN:-$HOME/bin/rclone}"
RCLONE_REMOTE="${COMPUTEHUB_RCLONE_REMOTE:-gdrive:ComputeHub-Backups}"
# Repo restic utama ada di Drive (backend rclone); path lokal masih diterima (sandbox).
RESTIC_REPO="${COMPUTEHUB_RESTIC_REPO:-rclone:${RCLONE_REMOTE%%:*}:ComputeHub-Restic}"
RESTIC_OPTS=()
case "$RESTIC_REPO" in
  rclone:*) RESTIC_OPTS=(-o "rclone.program=$RCLONE_BIN" -o "rclone.args=serve restic --stdio --drive-use-trash=false") ;;
esac
OPS_EVENT="$ROOT/scripts/ops_event.py"
NOTIFY="$ROOT/scripts/notify_telegram.py"
TS="$(date +%Y%m%d-%H%M%S)"
SNAP="$SNAP_BASE/pre-restore-$TS"
START_EPOCH="$(date +%s)"

say() { echo -e "\033[1;36m[restore]\033[0m $*"; }

# --- Argumen ----------------------------------------------------------------
YES=0; ARCHIVE=""; SNAPSHOT=""; PRE_RESTORE=""; OFFSITE=""; SCOPE="db,users"; STOP_SESSIONS=0; REQUEST_ID=""
[ "${RESTORE_ENV:-0}" = 1 ] && SCOPE="db,users,env"
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --archive) ARCHIVE="$2"; shift ;;
    --snapshot) SNAPSHOT="$2"; shift ;;
    --pre-restore) PRE_RESTORE="$2"; shift ;;
    --offsite) OFFSITE="$2"; shift ;;
    --scope) SCOPE="$2"; shift ;;
    --stop-sessions) STOP_SESSIONS=1 ;;
    --request-id) REQUEST_ID="$2"; shift ;;
    --no-service) SERVICE="" ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    --*) echo "opsi tidak dikenal: $1" >&2; exit 2 ;;
    *) ARCHIVE="$1" ;;
  esac
  shift
done
has_scope() { case ",$SCOPE," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
for s in ${SCOPE//,/ }; do
  case "$s" in db|users|env) ;; *) echo "scope tidak dikenal: $s (pilihan: db,users,env)" >&2; exit 2 ;; esac
done

# --- Bukti & pemberitahuan (best-effort) ------------------------------------
SOURCE_LABEL=""
catat() {  # catat <status> <judul> <json-data>
  [ "${COMPUTEHUB_NO_OPS_EVENT:-0}" = 1 ] && return 0
  [ -f "$OPS_EVENT" ] || return 0
  python3 "$OPS_EVENT" --kind restore --status "$1" --title "$2" --data "$3" \
    --duration "$(( $(date +%s) - START_EPOCH ))" --source restore.sh >/dev/null 2>&1 || true
}
notify() {
  [ "${COMPUTEHUB_NO_OPS_EVENT:-0}" = 1 ] && return 0
  [ -f "$NOTIFY" ] && python3 "$NOTIFY" "$1" "$2" >/dev/null 2>&1 || true
}
err() {
  echo -e "\033[1;31m[GAGAL]\033[0m $*" >&2
  catat fail "Restore GAGAL: $*" "$(printf '{"source":"%s","scope":"%s","request_id":"%s","snapshot_dir":"%s"}' "$SOURCE_LABEL" "$SCOPE" "$REQUEST_ID" "$(basename "$SNAP")")"
  notify "Restore ComputeHub GAGAL" "$*"
  exit 1
}

# --- Pilih sumber -----------------------------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SRC_DIR=""   # folder berisi db.sql / users/ setelah ekstraksi

if [ -n "$PRE_RESTORE" ]; then
  # Titik rollback: folder pre-restore-<ts> (db-before.sql + users-before.tar.gz + env-before)
  case "$PRE_RESTORE" in */*) PRE_DIR="$PRE_RESTORE" ;; *) PRE_DIR="$SNAP_BASE/$PRE_RESTORE" ;; esac
  [ -d "$PRE_DIR" ] || err "titik rollback tidak ditemukan: $PRE_DIR"
  SOURCE_LABEL="$(basename "$PRE_DIR")"
  say "Sumber       : titik rollback $SOURCE_LABEL"
elif [ -n "$SNAPSHOT" ]; then
  [[ "$SNAPSHOT" =~ ^[0-9a-f]{8,64}$ ]] || err "id snapshot restic tidak valid: $SNAPSHOT"
  [ -x "$RESTIC_BIN" ] && [ -f "$PASSFILE" ] || err "restic/passphrase tidak tersedia"
  SOURCE_LABEL="restic:$SNAPSHOT"
  say "Sumber       : snapshot restic $SNAPSHOT"
else
  if [ -n "$OFFSITE" ]; then
    [[ "$OFFSITE" =~ ^computehub(-core)?-[0-9]{8}-[0-9]{6}\.tar\.gz\.gpg$ ]] || err "nama arsip Drive tidak valid: $OFFSITE"
    [ -x "$RCLONE_BIN" ] || err "rclone tidak tersedia"
    say "Mengunduh $OFFSITE (+ sidecar sha256) dari $RCLONE_REMOTE …"
    "$RCLONE_BIN" copy "$RCLONE_REMOTE" "$TMP/offsite" --include "$OFFSITE" --include "$OFFSITE.sha256" --timeout 30m --retries 2 -q || err "unduh dari Drive gagal"
    ARCHIVE="$TMP/offsite/$OFFSITE"
  fi
  if [ -z "$ARCHIVE" ]; then
    ARCHIVE="$(ls -1t "$ENC_DIR"/computehub-*.tar.gz.gpg 2>/dev/null | head -1 || true)"
    [ -n "$ARCHIVE" ] || err "tak ada arsip terenkripsi di $ENC_DIR (atau berikan --archive)"
  fi
  # Nama saja (dari web) -> cari di folder arsip terenkripsi lalu polos.
  case "$ARCHIVE" in
    */*) ;;
    *) if [ -f "$ENC_DIR/$ARCHIVE" ]; then ARCHIVE="$ENC_DIR/$ARCHIVE"
       elif [ -f "$PLAIN_DIR/$ARCHIVE" ]; then ARCHIVE="$PLAIN_DIR/$ARCHIVE"; fi ;;
  esac
  [ -f "$ARCHIVE" ] || err "arsip tidak ditemukan: $ARCHIVE"
  SOURCE_LABEL="$(basename "$ARCHIVE")"
  say "Arsip sumber : $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
fi
say "DB container : $PG_CONTAINER"
say "Workspace    : $DATA"
say "Cakupan      : $SCOPE"
say "Snapshot     : $SNAP (kondisi SEKARANG, untuk rollback)"
[ -n "$SERVICE" ] && say "Unit         : $SERVICE (dihentikan selama restore)" || say "Unit         : (tidak disentuh — mode sandbox)"
echo

# --- Konfirmasi -------------------------------------------------------------
if [ "$YES" = 1 ]; then
  [ "${COMPUTEHUB_RESTORE_CONFIRM:-}" = "YA PULIHKAN" ] || err "mode --yes butuh COMPUTEHUB_RESTORE_CONFIRM=\"YA PULIHKAN\""
else
  echo "Tindakan ini akan MENIMPA database & workspace saat ini dengan isi backup,"
  echo "dan mematikan aplikasi sementara."
  read -r -p 'Ketik persis  YA PULIHKAN  untuk lanjut: ' CONFIRM
  [ "$CONFIRM" = "YA PULIHKAN" ] || err "dibatalkan (konfirmasi tidak cocok)"
fi

# --- 0) Siapkan isi sumber --------------------------------------------------
if [ -n "$PRE_RESTORE" ]; then
  SRC_DIR="$TMP/src"; mkdir -p "$SRC_DIR"
  [ -f "$PRE_DIR/db-before.sql" ] && cp "$PRE_DIR/db-before.sql" "$SRC_DIR/db.sql"
  if [ -f "$PRE_DIR/users-before.tar.gz" ]; then
    say "Mengekstrak workspace dari titik rollback…"
    tar -xzf "$PRE_DIR/users-before.tar.gz" -C "$SRC_DIR" || err "ekstraksi users-before gagal"
    # users-before.tar.gz menyimpan folder dengan nama asli DATA (biasanya 'users').
    if [ "$(basename "$DATA")" != users ] && [ -d "$SRC_DIR/$(basename "$DATA")" ]; then
      mv "$SRC_DIR/$(basename "$DATA")" "$SRC_DIR/users"
    fi
  fi
  [ -f "$PRE_DIR/env-before" ] && cp "$PRE_DIR/env-before" "$SRC_DIR/env.backup"
elif [ -n "$SNAPSHOT" ]; then
  say "Memulihkan snapshot restic ke area kerja (repo ${RESTIC_REPO#rclone:})…"
  RESTIC_PASSWORD_FILE="$PASSFILE" RESTIC_REPOSITORY="$RESTIC_REPO" \
    "$RESTIC_BIN" "${RESTIC_OPTS[@]}" restore "$SNAPSHOT" --target "$TMP/snap" -q || err "restic restore gagal"
  SRC_DIR="$(find "$TMP/snap" -maxdepth 4 -name db.sql -printf '%h\n' | head -1 || true)"
  [ -n "$SRC_DIR" ] || err "db.sql tidak ditemukan di snapshot $SNAPSHOT"
else
  if [ -f "$ARCHIVE.sha256" ]; then
    say "Memeriksa integritas arsip (sha256)…"
    EXPECT="$(cut -d' ' -f1 "$ARCHIVE.sha256")"
    ACTUAL="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
    [ "$EXPECT" = "$ACTUAL" ] || err "sha256 arsip TIDAK cocok dengan $ARCHIVE.sha256 — arsip berubah/rusak"
    say "Integritas OK."
  fi
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
  SRC_DIR="$TMP/src"; mkdir -p "$SRC_DIR"
  say "Mengekstrak arsip…"
  tar -xzf "$TMP/b.tar.gz" -C "$SRC_DIR" || err "ekstraksi arsip gagal"
  rm -f "$TMP/b.tar.gz"
fi
if has_scope db; then
  [ -f "$SRC_DIR/db.sql" ] || err "db.sql tidak ada di sumber — tidak bisa memulihkan database"
  say "db.sql: $(wc -l < "$SRC_DIR/db.sql") baris."
fi
if has_scope users && [ ! -d "$SRC_DIR/users" ]; then
  say "(catatan: folder users/ tak ada di sumber — workspace dilewati)"
fi

# --- 1) Pastikan DB container hidup ----------------------------------------
sudo -n docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER" \
  || err "container DB '$PG_CONTAINER' tidak berjalan — start dulu sebelum restore"

# --- 2) SNAPSHOT kondisi sekarang (agar restore bisa di-rollback) ----------
say "Mengambil snapshot kondisi SEKARANG ke $SNAP …"
mkdir -p "$SNAP" && chmod 700 "$SNAP"
sudo -n docker exec "$PG_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "$SNAP/db-before.sql" 2>/dev/null || err "gagal snapshot DB sekarang (batalkan demi keamanan)"
if has_scope users && [ -d "$DATA" ]; then
  tar -czf "$SNAP/users-before.tar.gz" -C "$(dirname "$DATA")" "$(basename "$DATA")" || true
fi
[ -f "$ROOT/backend/.env" ] && cp "$ROOT/backend/.env" "$SNAP/env-before" || true
printf '{"created_at":"%s","source":"%s","scope":"%s","request_id":"%s","data_dir":"%s"}\n' \
  "$(date -Iseconds)" "$SOURCE_LABEL" "$SCOPE" "$REQUEST_ID" "$DATA" > "$SNAP/meta.json"
say "Snapshot siap ($(du -sh "$SNAP" | cut -f1)). Rollback nanti pakai titik ini."

# --- 3) Hentikan aplikasi (dan sesi pengguna bila diminta) ------------------
if [ -n "$SERVICE" ]; then
  say "Menghentikan aplikasi ($SERVICE)…"
  systemctl --user stop "$SERVICE" || err "gagal menghentikan service"
  sleep 2
fi
STOPPED_SESSIONS=0
if [ "$STOP_SESSIONS" = 1 ]; then
  # Kontainer kernel/job/devbox menulis ke workspace yang akan ditimpa -> hentikan dulu.
  mapfile -t RUNNING < <(sudo -n docker ps --format '{{.Names}}' | grep -E '^ch-(kernel|job|devbox)-' || true)
  if [ "${#RUNNING[@]}" -gt 0 ]; then
    say "Menghentikan ${#RUNNING[@]} kontainer sesi pengguna: ${RUNNING[*]}"
    sudo -n docker stop -t 10 "${RUNNING[@]}" >/dev/null 2>&1 || true
    STOPPED_SESSIONS="${#RUNNING[@]}"
  fi
fi

start_service() { if [ -n "$SERVICE" ]; then systemctl --user start "$SERVICE" || true; fi; }

# --- 4) Restore DATABASE (drop → create → muat dump) -----------------------
if has_scope db; then
  say "Memulihkan database…"
  sudo -n docker exec "$PG_CONTAINER" sh -c '
    set -e
    psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
      -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '\''"'"'"'$POSTGRES_DB'"'"'"'\'' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true
    psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";"
    psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"
  ' >/dev/null 2>&1 || { start_service; err "gagal reset database (aplikasi dinyalakan lagi; cek $SNAP/db-before.sql)"; }

  if ! sudo -n docker exec -i "$PG_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -v ON_ERROR_STOP=0' < "$SRC_DIR/db.sql" > "$TMP/restore.log" 2>&1; then
    say "psql melaporkan sebagian error — $(grep -c ERROR "$TMP/restore.log" || true) baris ERROR (sebagian non-fatal wajar pada dump plain)."
  fi
  say "Database dimuat dari backup."
fi

# --- 5) Restore WORKSPACE /persist -----------------------------------------
if has_scope users && [ -d "$SRC_DIR/users" ]; then
  say "Memulihkan workspace pengguna…"
  mkdir -p "$DATA"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$SRC_DIR/users/" "$DATA/"
  else
    rm -rf "$DATA"; mkdir -p "$DATA"; cp -a "$SRC_DIR/users/." "$DATA/"
  fi
  say "Workspace dipulihkan."
fi

# --- 6) Restore .env (opsional) --------------------------------------------
if has_scope env && [ -f "$SRC_DIR/env.backup" ]; then
  cp "$SRC_DIR/env.backup" "$ROOT/backend/.env"
  say "backend/.env dipulihkan dari backup."
fi

# --- 7) Verifikasi isi DB + nyalakan kembali --------------------------------
hitung() { sudo -n docker exec "$PG_CONTAINER" sh -c "psql -tA -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"$1\"" 2>/dev/null | tr -d '[:space:]' || echo 0; }
TABLES="$(hitung "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
USERS="$(hitung "SELECT count(*) FROM users;")"
JOBS="$(hitung "SELECT count(*) FROM jobs;")"
CODE="-"
if [ -n "$SERVICE" ]; then
  say "Menyalakan aplikasi kembali…"
  systemctl --user start "$SERVICE" || err "service gagal start — cek: journalctl --user -u $SERVICE"
  for _ in $(seq 1 30); do
    sleep 2
    CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_LOCAL" || echo 000)"
    [ "$CODE" = 200 ] && break
  done
fi
echo
HASIL="Sumber $SOURCE_LABEL · cakupan $SCOPE · $TABLES tabel, $USERS user, $JOBS job · health $CODE · sesi dihentikan $STOPPED_SESSIONS"
DATA_JSON="$(printf '{"source":"%s","scope":"%s","tables":%s,"users":%s,"jobs":%s,"health":"%s","sessions_stopped":%s,"snapshot_dir":"%s","request_id":"%s"}' \
  "$SOURCE_LABEL" "$SCOPE" "${TABLES:-0}" "${USERS:-0}" "${JOBS:-0}" "$CODE" "$STOPPED_SESSIONS" "$(basename "$SNAP")" "$REQUEST_ID")"
if [ -z "$SERVICE" ] || [ "$CODE" = 200 ]; then
  say "SELESAI ✅  $HASIL"
  catat ok "Restore SELESAI dari $SOURCE_LABEL" "$DATA_JSON"
  notify "Restore ComputeHub SELESAI" "$HASIL
Titik rollback: $(basename "$SNAP")"
else
  say "Aplikasi start, tapi health = $CODE. Cek log: journalctl --user -u $SERVICE -n 50"
  catat warn "Restore selesai, health $CODE (periksa aplikasi)" "$DATA_JSON"
  notify "Restore ComputeHub selesai, health $CODE" "$HASIL"
fi
echo
echo "Snapshot kondisi sebelum restore: $SNAP"
echo "ROLLBACK (bila hasil tak sesuai) — dari web: Cadangan & Pemulihan > Titik rollback, atau CLI:"
echo "  COMPUTEHUB_RESTORE_CONFIRM='YA PULIHKAN' $0 --yes --pre-restore $(basename "$SNAP") --scope $SCOPE"
