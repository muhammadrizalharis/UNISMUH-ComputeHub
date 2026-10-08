#!/usr/bin/env bash
# Backup data ComputeHub: workspace persisten /persist (kerja mahasiswa) + konfigurasi
# (.env) + dump DB + log eksekusi. Aman dijalankan kapan saja; dipakai oleh systemd
# --user timer (computehub-backup.timer, 02:30 WITA) dan tombol "Backup sekarang" di web.
#
# KEBIJAKAN (9 Okt 2026, pesan dosen): yang BESAR hanya di Google Drive, server hanya
# memegang backup KECIL.
#   harian  : arsip INTI (db.sql + roles + .env + agen + log job; tanpa workspace, puluhan MB)
#             -> server 30 hari + Drive 90 hari;  restic (dedup) LANGSUNG ke repo di Drive.
#   mingguan: arsip PENUH (dengan workspace, puluhan GB) -> Drive (verifikasi md5), salinan
#             server DIHAPUS; Drive simpan 8 arsip penuh terbaru.
#
# Variabel opsional:
#   COMPUTEHUB_ROOT        (default: $HOME/DATA_ICAL/SERVER-KAMPUS)
#   COMPUTEHUB_BACKUP_DIR  (default: $HOME/.computehub/backups   — arsip polos sementara)
#   COMPUTEHUB_BACKUP_ENC_DIR (default: $HOME/.computehub/backups_enc — arsip .gpg)
#   COMPUTEHUB_BACKUP_KEEP (default: 0 — arsip PENUH yang tetap di server setelah
#     terverifikasi di Drive; 0 = hapus semua, yang besar hanya di Drive)
#   COMPUTEHUB_CORE_KEEP_DAYS (30) / COMPUTEHUB_DRIVE_CORE_KEEP_DAYS (90) / COMPUTEHUB_DRIVE_TAR_KEEP (8)
#   COMPUTEHUB_RESTIC_REPO (default: rclone:gdrive:ComputeHub-Restic; path lokal = repo lokal)
#   COMPUTEHUB_BACKUP_FORCE_TAR=1  paksa arsip penuh hari ini (dipakai tombol
#     "Backup sekarang" di web lewat scripts/ops_agent.py), abaikan jadwal mingguan
#   COMPUTEHUB_BACKUP_LABEL        label manifest (terjadwal | manual-web), plus
#   COMPUTEHUB_BACKUP_REQUESTED_BY / COMPUTEHUB_REQUEST_ID dari agen web
#   Knob SANDBOX (uji skrip tanpa menyentuh produksi; default = produksi):
#   COMPUTEHUB_DATA_DIR, COMPUTEHUB_SKIP_OFFSITE=1, COMPUTEHUB_SKIP_RESTIC=1,
#   COMPUTEHUB_RCLONE_REMOTE, COMPUTEHUB_NO_OPS_EVENT=1 (tanpa catatan DB/Telegram),
#   COMPUTEHUB_LOCK_FILE
set -euo pipefail

ROOT="${COMPUTEHUB_ROOT:-$HOME/DATA_ICAL/SERVER-KAMPUS}"
DATA="${COMPUTEHUB_DATA_DIR:-$HOME/.computehub/users}"
DEST="${COMPUTEHUB_BACKUP_DIR:-$HOME/.computehub/backups}"
LABEL="${COMPUTEHUB_BACKUP_LABEL:-terjadwal}"
REQUESTED_BY="${COMPUTEHUB_BACKUP_REQUESTED_BY:-}"
REQUEST_ID="${COMPUTEHUB_REQUEST_ID:-}"

# Satu backup pada satu waktu: tombol web (ops_agent) dan timer 02:30 bisa bertemu.
# Menunggu maks 2 jam; yang datang belakangan tetap berjalan setelah yang pertama usai.
LOCK_FILE="${COMPUTEHUB_LOCK_FILE:-$HOME/.computehub/backup.lock}"
exec 9>"$LOCK_FILE"
if ! flock -w 7200 9; then
  echo "Backup lain masih berjalan >2 jam (kunci $LOCK_FILE) — dibatalkan." >&2
  exit 1
fi

# --- Pemberitahuan Telegram (opsional; diam bila token belum diisi) -----------
# Admin tak perlu membuka server untuk tahu backup semalam berhasil atau tidak.
START_EPOCH="$(date +%s)"
START_ISO="$(date -Iseconds)"
NOTIFY="$ROOT/scripts/notify_telegram.py"
notify() {  # notify <judul> <isi>
  [ "${COMPUTEHUB_NO_OPS_EVENT:-0}" = 1 ] && return 0
  [ -f "$NOTIFY" ] || return 0
  python3 "$NOTIFY" "$1" "$2" >/dev/null 2>&1 || true
}
lama() { local d=$(( $(date +%s) - START_EPOCH )); echo "$((d / 60))m $((d % 60))d"; }

# --- Heartbeat monitoring eksternal (healthchecks.io / sejenis) ------------
# URL ping di ~/.computehub/healthcheck.url (chmod 600); tanpa file -> dilewati.
# /start di awal: layanan tahu backup SEDANG berjalan, sehingga unggahan tar
# mingguan yang bisa berjam-jam (20 Sep 2026: 5 jam saat Drive lambat) tidak
# dianggap "server mati". /fail saat gagal: peringatan seketika, tanpa menunggu
# tenggang. Ping sukses dikirim di akhir hanya bila SEMUA langkah selesai.
HCFILE="$HOME/.computehub/healthcheck.url"
HCURL=""
if [ -f "$HCFILE" ]; then HCURL="$(head -1 "$HCFILE" | tr -d '[:space:]')"; fi
hc_ping() {  # hc_ping [start|fail]  (tanpa argumen = sukses)
  [ -n "$HCURL" ] || return 0
  [ "${COMPUTEHUB_NO_OPS_EVENT:-0}" = 1 ] && return 0   # sandbox: jangan "lapor sukses" ke monitor
  curl -fsS -m 10 --retry 3 "$HCURL${1:+/$1}" >/dev/null 2>&1
}
# --- Bukti permanen di DB (Pengaturan > Cadangan & Pemulihan); best-effort -----
# Status tiap lapisan dikumpulkan di variabel ini lalu dicatat sekali di akhir,
# supaya jejak backup tidak hanya hidup di email/Telegram yang bisa terhapus.
OPS_EVENT="$ROOT/scripts/ops_event.py"
MANIFEST_PY="$ROOT/scripts/backup_manifest.py"
OFFSITE_TAR="dilewati"; RESTIC_STAT="dilewati"; RESTIC_CHECK="-"; RESTIC_OFFSITE="dilewati"; RESTIC_SNAPSHOT=""
ARCHIVE_SHA256=""; ARCHIVE_BYTES=0; FINAL_ARCHIVE=""
catat_ops() {  # catat_ops <status> <judul> <json-data>
  [ "${COMPUTEHUB_NO_OPS_EVENT:-0}" = 1 ] && return 0
  [ -f "$OPS_EVENT" ] || return 0
  python3 "$OPS_EVENT" --kind backup --status "$1" --title "$2" --data "$3" \
    --duration "$(( $(date +%s) - START_EPOCH ))" --source backup.sh >/dev/null 2>&1 || true
}
# set -e + trap ERR: kegagalan di langkah mana pun langsung dilaporkan ke admin.
trap 'hc_ping fail || true; catat_ops fail "Backup GAGAL: berhenti di baris $LINENO" "{\"line\":$LINENO}"; notify "Backup ComputeHub GAGAL" "Berhenti di baris $LINENO (durasi $(lama)). Cek: journalctl --user -u computehub-backup.service -n 40"' ERR
hc_ping start || echo "(heartbeat /start gagal — lanjut)"

mkdir -p "$DEST"
chmod 700 "$DEST" 2>/dev/null || true   # backup berisi .env -> batasi akses

# Jaring pengaman: pastikan penjaga volume DB hidup (mengunci computehub-pgdata
# dari docker volume prune). Best-effort — kegagalannya TAK boleh menggagalkan backup.
if [ -x "$ROOT/scripts/ensure_pgdata_guard.sh" ]; then
  "$ROOT/scripts/ensure_pgdata_guard.sh" || echo "(penjaga volume DB dilewati)"
fi

TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$DEST/computehub-$TS.tar.gz"
ARCHIVE_SIZE=""                 # terisi bila arsip tar dibuat (kosong = hari non-tar)
ARSIP_BENTUK="polos (enkripsi dilewati/gagal)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1) Workspace persisten per-user (kerja mahasiswa: file, notebook, paket pip --user).
if [ -d "$DATA" ]; then cp -a "$DATA" "$TMP/users"; else mkdir -p "$TMP/users"; fi

# 2) Konfigurasi (.env) — agar bisa pulih utuh.
[ -f "$ROOT/backend/.env" ] && cp "$ROOT/backend/.env" "$TMP/env.backup" || true

# 2b) Agen pemantau lokal (~/.computehub/net-health-*) + unit systemd-nya. Skrip ini
#     berada DI LUAR repo dan berisi kredensial, jadi tanpa langkah ini ia tak akan
#     pernah ikut terpulihkan bila home directory hilang. Arsip sudah dibatasi izinnya
#     (chmod 700) dan disalin ke luar dalam bentuk terenkripsi.
mkdir -p "$TMP/agent"
for f in "$HOME/.computehub/net-health-agent.py" \
         "$HOME/.computehub/net-health-alert.sh" \
         "$HOME/.computehub/net-health.env" \
         "$HOME/.config/systemd/user/net-health-agent.service" \
         "$HOME/.config/systemd/user/net-health-agent-failure.service" \
         "$HOME/.config/systemd/user/computehub.service"; do
  [ -f "$f" ] && cp -p "$f" "$TMP/agent/" || true
done
chmod -R go-rwx "$TMP/agent" 2>/dev/null || true

# 2c) Jejak audit eksekusi: job.log (batch) + session.log (notebook interaktif).
#     HANYA berkas log yang disalin — working_dir job bisa berisi dataset/model
#     besar, sedangkan yang wajib bisa diaudit adalah catatan jalannya program.
JOBS_DIR="$ROOT/backend/_jobs"
LOG_COUNT=0
if [ -d "$JOBS_DIR" ]; then
  mkdir -p "$TMP/joblogs"
  ( cd "$JOBS_DIR" \
    && find . \( -name 'job.log' -o -name 'session.log' \) -type f \
         -exec cp -p --parents {} "$TMP/joblogs/" \; ) 2>/dev/null || true
  # pipefail aktif: find yang gagal sebagian TAK boleh menggagalkan seluruh backup.
  LOG_COUNT="$(find "$TMP/joblogs" -type f 2>/dev/null | wc -l)" || LOG_COUNT=0
fi
echo "Log eksekusi ikut diarsipkan: $LOG_COUNT berkas."

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

# 3b) Roles/globals (pg_dumpall --globals-only): kecil, melengkapi dump agar peran DB
#     bisa dibuat ulang di server kosong. Best-effort.
if [ "$DB_DUMPED" = 1 ] && sudo -n docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CH_PG_CONTAINER"; then
  sudo -n docker exec "$CH_PG_CONTAINER" sh -c 'pg_dumpall -U "$POSTGRES_USER" --globals-only' \
    > "$TMP/globals.sql" 2>/dev/null || rm -f "$TMP/globals.sql"
fi

# 3c) Manifest rincian isi arsip (ikut masuk tar) — tampil sebagai "Detail Backup" di web.
if [ -f "$MANIFEST_PY" ]; then
  python3 "$MANIFEST_PY" stage --staging "$TMP" --label "$LABEL" \
    --requested-by "$REQUESTED_BY" --request-id "$REQUEST_ID" --started-at "$START_ISO" \
    || echo "(manifest gagal dibuat — backup tetap jalan)"
fi

# ---------------------------------------------------------------------------
# Konfigurasi bersama enkripsi + Drive + restic. WAJIB di LUAR blok tar mingguan di
# bawah: blok restic ikut memakainya, dan skrip ini `set -u` -> kalau variabel
# ini ikut dilewati saat bukan hari tar, restic mati "unbound variable".
# (Pernah terjadi 14-15 Sep 2026: backup gagal total 2 hari.)
#
# KEBIJAKAN PENYIMPANAN (9 Okt 2026, pesan dosen): yang BESAR hanya di Drive,
# server hanya memegang backup KECIL.
#   - Arsip INTI harian (db.sql + roles + .env + agen + log job; TANPA workspace,
#     puluhan MB): tinggal di server CORE_KEEP_DAYS hari + salinan di Drive
#     DRIVE_CORE_KEEP_DAYS hari. Ini jalur pulih DB tercepat tanpa unduhan.
#   - Arsip PENUH mingguan (dengan workspace, puluhan GB): diunggah ke Drive,
#     DIVERIFIKASI md5 (rclone check), lalu salinan lokal DIHAPUS (TAR_LOCAL_KEEP=0).
#     Drive menyimpan DRIVE_TAR_KEEP arsip penuh terbaru.
#   - Restic harian (dedup, 7 harian/4 mingguan/3 bulanan) LANGSUNG ke repo di Drive
#     (backend rclone) tanpa repo lokal: unggahan harian hanya blok yang berubah.
# ---------------------------------------------------------------------------
PASSFILE="$HOME/.computehub/backup.pass"
DEST_ENC="${COMPUTEHUB_BACKUP_ENC_DIR:-$HOME/.computehub/backups_enc}"
RCLONE_BIN="${RCLONE_BIN:-$HOME/bin/rclone}"
# Folder tujuan di Drive DIBUAT otomatis oleh rclone (privat secara default).
# Scope drive.file: rclone HANYA bisa melihat/menulis folder buatannya sendiri —
# tak perlu (dan tak bisa) menyimpan link/ID folder manual mana pun.
RCLONE_REMOTE="${COMPUTEHUB_RCLONE_REMOTE:-gdrive:ComputeHub-Backups}"
RCLONE_REMOTE_NAME="${RCLONE_REMOTE%%:*}"
# Folder versi warisan `rclone sync --backup-dir` tidak dibuat lagi (unggahan kini
# `copy --immutable`: berkas di Drive tak pernah ditimpa/dihapus oleh sinkronisasi);
# sisa lama dikuras setelah jendelanya lewat.
VERSIONS_KEEP_DAYS="${COMPUTEHUB_VERSIONS_KEEP_DAYS:-21}"
CORE_KEEP_DAYS="${COMPUTEHUB_CORE_KEEP_DAYS:-30}"
DRIVE_CORE_KEEP_DAYS="${COMPUTEHUB_DRIVE_CORE_KEEP_DAYS:-90}"
DRIVE_TAR_KEEP="${COMPUTEHUB_DRIVE_TAR_KEEP:-8}"
TAR_LOCAL_KEEP="${COMPUTEHUB_BACKUP_KEEP:-0}"
CORE_STAT="dilewati"; CORE_OFFSITE="dilewati"; CORE_ARCHIVE=""; CORE_ENC=""; CORE_BYTES=0; CORE_SHA256=""
TAR_LOCAL_DELETED=0; DRIVE_READY=0; DRIVE_FULL_DELETED=0
if [ "${COMPUTEHUB_SKIP_OFFSITE:-0}" != 1 ] && [ -x "$RCLONE_BIN" ] \
   && "$RCLONE_BIN" listremotes 2>/dev/null | grep -q "^${RCLONE_REMOTE_NAME}:"; then
  DRIVE_READY=1
fi
# Enkripsi arsip polos -> .gpg yang DIVERIFIKASI (dekripsi ulang + cmp) + sidecar .sha256.
# Polos dihapus bila identik (COMPUTEHUB_KEEP_PLAIN=1 mempertahankan). Gagal -> polos tetap.
encrypt_archive() {  # encrypt_archive <arsip.tar.gz> <tujuan.gpg>
  local src="$1" enc="$2"
  gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file "$PASSFILE" -o "$enc" "$src" 2>/dev/null || return 1
  if gpg --batch --quiet --passphrase-file "$PASSFILE" -d "$enc" 2>/dev/null | cmp -s - "$src"; then
    [ "${COMPUTEHUB_KEEP_PLAIN:-0}" = 1 ] || rm -f "$src"
  else
    echo "!!! Verifikasi .gpg GAGAL untuk $(basename "$enc") — arsip polos DIPERTAHANKAN."
    return 1
  fi
  echo "$(sha256sum "$enc" | cut -d' ' -f1)  $(basename "$enc")" > "$enc.sha256"
  return 0
}
# Unggah berkas-berkas $DEST_ENC yang cocok pola ke Drive lalu VERIFIKASI (rclone check:
# ukuran + md5 Drive). --immutable: berkas yang sudah ada di Drive tak pernah ditimpa.
drive_push() {  # drive_push <pola-include> [pola-include...]
  [ "$DRIVE_READY" = 1 ] || return 1
  local inc=()
  for p in "$@"; do inc+=(--include "$p"); done
  "$RCLONE_BIN" copy "$DEST_ENC" "$RCLONE_REMOTE" "${inc[@]}" --immutable \
    --timeout 10m --retries 2 -q 2>/dev/null || true
  "$RCLONE_BIN" check "$DEST_ENC" "$RCLONE_REMOTE" --one-way "${inc[@]}" -q 2>/dev/null
}

# ---------------------------------------------------------------------------
# ARSIP INTI HARIAN (kecil): db.sql + globals.sql + .env + agen + log job (+manifest),
# TANPA workspace. Inilah backup yang tetap tinggal di SERVER (pulih DB cepat);
# salinannya ikut ke Drive. Workspace besar dibawa restic (Drive) & arsip penuh mingguan.
# ---------------------------------------------------------------------------
if command -v gpg >/dev/null 2>&1 && [ -f "$PASSFILE" ]; then
  CORE_TMP="$(mktemp -d)"
  for item in db.sql globals.sql db.err env.backup agent joblogs; do
    [ -e "$TMP/$item" ] || continue
    cp -al "$TMP/$item" "$CORE_TMP/" 2>/dev/null || cp -a "$TMP/$item" "$CORE_TMP/"
  done
  if [ -f "$MANIFEST_PY" ]; then
    python3 "$MANIFEST_PY" stage --staging "$CORE_TMP" --label "$LABEL" --kind core \
      --requested-by "$REQUESTED_BY" --request-id "$REQUEST_ID" --started-at "$START_ISO" >/dev/null \
      || echo "(manifest arsip inti gagal dibuat — lanjut)"
    [ -f "$CORE_TMP/manifest.json" ] && cp "$CORE_TMP/manifest.json" "$TMP/core-manifest.json" || true
  fi
  mkdir -p "$DEST_ENC" && chmod 700 "$DEST_ENC" 2>/dev/null || true
  CORE_PLAIN="$DEST/computehub-core-$TS.tar.gz"
  CORE_ENC="$DEST_ENC/computehub-core-$TS.tar.gz.gpg"
  if tar -czf "$CORE_PLAIN" -C "$CORE_TMP" . && encrypt_archive "$CORE_PLAIN" "$CORE_ENC"; then
    CORE_ARCHIVE="$(basename "$CORE_ENC")"
    CORE_BYTES="$(stat -c %s "$CORE_ENC")"
    CORE_SHA256="$(cut -d' ' -f1 "$CORE_ENC.sha256")"
    CORE_STAT="ok"
    echo "Arsip inti harian: $CORE_ARCHIVE ($(du -h "$CORE_ENC" | cut -f1); di server $CORE_KEEP_DAYS hari)."
    # Retensi lokal arsip inti berdasar umur (sidecar .sha256/.manifest.json ikut).
    find "$DEST_ENC" -maxdepth 1 -name 'computehub-core-*' -type f -mtime +"$CORE_KEEP_DAYS" -delete 2>/dev/null || true
  else
    echo "!!! Arsip inti harian GAGAL dibuat/dienkripsi."
    CORE_STAT="gagal"; CORE_ENC=""; rm -f "$CORE_PLAIN"
  fi
  rm -rf "$CORE_TMP"
else
  echo "(arsip inti dilewati — gpg atau $PASSFILE tidak tersedia)"
fi
# ---------------------------------------------------------------------------
# ARSIP TAR PENUH = MINGGUAN (arsip inti + restic tetap HARIAN).
# Tar menyalin ULANG seluruh isi tiap kali (puluhan GB) -> harian berarti berjam-jam
# unggah/hari untuk isi yang nyaris sama, padahal restic sudah memegang riwayat
# harian secara hemat di Drive. Arsip penuh = jaring pengaman format universal
# (tar+gpg, bisa dibuka alat standar tanpa restic).
# COMPUTEHUB_TAR_DAY: 1=Senin .. 7=Minggu; kosong = kembali ke harian.
# ---------------------------------------------------------------------------
TAR_DAY="${COMPUTEHUB_TAR_DAY-7}"
if [ "${COMPUTEHUB_BACKUP_FORCE_TAR:-0}" = 1 ]; then
  echo "Arsip tar DIPAKSA hari ini (permintaan $LABEL${REQUESTED_BY:+ oleh $REQUESTED_BY})."
  TAR_DAY=""
fi
if [ -n "$TAR_DAY" ] && [ "$(date +%u)" != "$TAR_DAY" ]; then
  echo "Arsip tar dilewati (jadwal mingguan hari ke-$TAR_DAY); restic tetap jalan."
else

tar -czf "$ARCHIVE" -C "$TMP" .
ARCHIVE_SIZE="$(du -h "$ARCHIVE" | cut -f1)"
FINAL_ARCHIVE="$ARCHIVE"
echo "Arsip penuh dibuat: $ARCHIVE ($ARCHIVE_SIZE)"

# Sisa arsip polos lama (enkripsi gagal di masa lalu) dirapikan: simpan yang terbaru saja.
mapfile -t OLD < <(ls -1t "$DEST"/computehub-*.tar.gz 2>/dev/null | tail -n +2)
if [ "${#OLD[@]}" -gt 0 ]; then
  rm -f "${OLD[@]}"
  echo "Hapus ${#OLD[@]} arsip polos lama."
fi

# ---------------------------------------------------------------------------
# ENKRIPSI arsip penuh (gpg simetris AES256, passphrase ~/.computehub/backup.pass).
# Unggahan ke Drive + penghapusan salinan lokal yang BESAR dilakukan di bagian
# "DRIVE" di bawah, setelah manifest final tersedia (ikut diunggah sebagai sidecar).
# ---------------------------------------------------------------------------
if command -v gpg >/dev/null 2>&1 && [ -f "$PASSFILE" ]; then
  mkdir -p "$DEST_ENC" && chmod 700 "$DEST_ENC" 2>/dev/null || true
  ENC="$DEST_ENC/$(basename "$ARCHIVE").gpg"
  if encrypt_archive "$ARCHIVE" "$ENC"; then
    echo "Terenkripsi: $ENC ($(du -h "$ENC" | cut -f1))"
    ARSIP_BENTUK="terenkripsi (.gpg)"
    FINAL_ARCHIVE="$ENC"
  else
    echo "(enkripsi gagal — arsip polos tetap di server, TIDAK diunggah)"
  fi
else
  echo "(enkripsi dilewati — gpg atau $PASSFILE tidak tersedia)"
fi

# Sidik jari arsip final (.gpg bila ada, kalau tidak tar polos): bukti integritas yang
# dicocokkan restore.sh sebelum memulihkan, dan tampil di rincian backup.
if [ -n "$FINAL_ARCHIVE" ] && [ -f "$FINAL_ARCHIVE" ]; then
  ARCHIVE_BYTES="$(stat -c %s "$FINAL_ARCHIVE")"
  if [ -f "$FINAL_ARCHIVE.sha256" ]; then
    ARCHIVE_SHA256="$(cut -d' ' -f1 "$FINAL_ARCHIVE.sha256")"
  else
    ARCHIVE_SHA256="$(sha256sum "$FINAL_ARCHIVE" | cut -d' ' -f1)" || ARCHIVE_SHA256=""
    [ -n "$ARCHIVE_SHA256" ] && echo "$ARCHIVE_SHA256  $(basename "$FINAL_ARCHIVE")" > "$FINAL_ARCHIVE.sha256"
  fi
  echo "SHA256 arsip: ${ARCHIVE_SHA256:0:16}… ($ARCHIVE_BYTES byte)"
fi

fi  # akhir blok arsip tar mingguan

# ---------------------------------------------------------------------------
# RESTIC (incremental + dedup) LANGSUNG KE DRIVE — lapisan harian untuk workspace
# besar. Repo utama = rclone:gdrive:ComputeHub-Restic (backend rclone; passphrase =
# backup.pass yang sama). Tidak ada repo lokal: yang besar hanya di Drive, dan
# unggahan harian hanya blok yang berubah. BEST-EFFORT: kegagalan restic TIDAK
# menggagalkan arsip inti/penuh di atas.
# Restore contoh:  RESTIC_PASSWORD_FILE=~/.computehub/backup.pass ~/bin/restic \
#   -r rclone:gdrive:ComputeHub-Restic -o rclone.program=$HOME/bin/rclone \
#   restore latest --target /tmp/pulih
# COMPUTEHUB_RESTIC_REPO=<path lokal> mengembalikan repo lokal (dipakai uji sandbox).
# ---------------------------------------------------------------------------
RESTIC_BIN="${RESTIC_BIN:-$HOME/bin/restic}"
RESTIC_REPO="${COMPUTEHUB_RESTIC_REPO:-rclone:${RCLONE_REMOTE_NAME}:ComputeHub-Restic}"
RESTIC_OPTS=()
RESTIC_DI_DRIVE=0
case "$RESTIC_REPO" in
  rclone:*) RESTIC_DI_DRIVE=1
            RESTIC_OPTS=(-o "rclone.program=$RCLONE_BIN" -o "rclone.args=serve restic --stdio --drive-use-trash=false") ;;
esac
restic_run() { "$RESTIC_BIN" "${RESTIC_OPTS[@]}" "$@"; }
if [ "${COMPUTEHUB_SKIP_RESTIC:-0}" = 1 ] || [ ! -x "$RESTIC_BIN" ] || [ ! -f "$PASSFILE" ]; then
  echo "(restic dilewati — binary/passphrase tidak tersedia)"
elif [ "$RESTIC_DI_DRIVE" = 1 ] && [ "$DRIVE_READY" != 1 ]; then
  echo "(restic dilewati — repo di Drive tetapi rclone/remote tidak siap)"
  RESTIC_STAT="gagal"
else
  export RESTIC_PASSWORD_FILE="$PASSFILE" RESTIC_REPOSITORY="$RESTIC_REPO"
  # Kunci basi (proses sebelumnya mati di tengah jalan) dibersihkan; kunci hidup dibiarkan.
  restic_run unlock -q >/dev/null 2>&1 || true
  restic_run cat config >/dev/null 2>&1 || restic_run init >/dev/null 2>&1 || true
  if restic_run backup "$TMP" --tag computehub -q >/dev/null 2>&1; then
    RESTIC_SNAPSHOT="$(restic_run snapshots --json --tag computehub --latest 1 2>/dev/null \
      | python3 -c 'import json,sys; s=json.load(sys.stdin); print(s[-1]["short_id"] if s else "")' 2>/dev/null || true)"
    # Retensi 7 harian / 4 mingguan / 3 bulanan. --group-by host,tags WAJIB: path staging
    # mktemp berbeda tiap hari, sehingga pengelompokan bawaan (host+paths) membuat tiap
    # snapshot grup sendiri dan kebijakan "keep" tidak pernah menghapus apa pun
    # (82 snapshot menumpuk Jul-Okt 2026). Prune (tulis-ulang pack) hanya hari Minggu
    # agar lalu lintas Drive harian tetap kecil.
    PRUNE_ARG=()
    [ "$(date +%u)" = "7" ] && PRUNE_ARG=(--prune)
    restic_run forget --tag computehub --group-by host,tags --keep-daily 7 --keep-weekly 4 \
      --keep-monthly 3 "${PRUNE_ARG[@]}" -q >/dev/null 2>&1 || true
    if [ "$RESTIC_DI_DRIVE" = 1 ]; then
      echo "Restic: snapshot ${RESTIC_SNAPSHOT:-?} OK — repo utama di ${RESTIC_REPO#rclone:}."
      RESTIC_OFFSITE="ok"
    else
      echo "Restic: snapshot OK (repo lokal $(du -sh "$RESTIC_REPO" 2>/dev/null | cut -f1))."
      RESTIC_OFFSITE="n/a (repo lokal)"
    fi
    RESTIC_STAT="ok"
    # Integritas repo: kerusakan senyap hanya ketahuan saat butuh kalau tak pernah
    # diperiksa. Minggu (hari ke-7) = struktur + baca ulang 5% data sungguhan (dari Drive).
    if [ "$(date +%u)" = "7" ]; then
      if restic_run check --read-data-subset=5% -q >/dev/null 2>&1; then
        echo "Restic: integritas OK (struktur + 5% data dibaca ulang)."
        RESTIC_CHECK="ok"
      else
        echo "!!! Restic: PERIKSA INTEGRITAS GAGAL — repo mungkin rusak."
        RESTIC_CHECK="gagal"
        echo "    Jalankan: RESTIC_PASSWORD_FILE=$PASSFILE $RESTIC_BIN -r $RESTIC_REPO ${RESTIC_OPTS[*]} check --read-data"
      fi
    fi
  else
    echo "(restic gagal — arsip inti/penuh tetap aman)"
    RESTIC_STAT="gagal"
  fi
fi

# ---------------------------------------------------------------------------
# DRIVE (1/3): unggah arsip inti (harian) + arsip penuh (bila ada, termasuk sisa yang
# belum sempat terunggah) dengan VERIFIKASI md5. Berkas di Drive tidak pernah ditimpa.
# ---------------------------------------------------------------------------
VERIFIED_FULL=()
if [ "$DRIVE_READY" = 1 ]; then
  if [ "$CORE_STAT" = ok ]; then
    if drive_push "$CORE_ARCHIVE" "$CORE_ARCHIVE.sha256"; then
      CORE_OFFSITE="ok"; echo "Drive: arsip inti terunggah & terverifikasi ($RCLONE_REMOTE)."
    else
      CORE_OFFSITE="gagal"; echo "(Drive: unggah arsip inti GAGAL — salinan di server tetap ada)"
    fi
  fi
  for enc in $(ls -1t "$DEST_ENC"/computehub-[0-9]*.tar.gz.gpg 2>/dev/null || true); do
    name="$(basename "$enc")"
    if drive_push "$name" "$name.sha256"; then
      VERIFIED_FULL+=("$enc")
      [ "$enc" = "${FINAL_ARCHIVE:-}" ] && OFFSITE_TAR="ok"
      echo "Drive: $name terverifikasi (ukuran + md5) di $RCLONE_REMOTE."
    else
      [ "$enc" = "${FINAL_ARCHIVE:-}" ] && OFFSITE_TAR="gagal"
      echo "(Drive: $name BELUM terverifikasi — salinan di server dipertahankan, dicoba lagi besok)"
    fi
  done
else
  echo "(Drive dilewati — rclone/remote '${RCLONE_REMOTE_NAME}' tidak siap; semua arsip tetap di server)"
fi

# Status akhir: 'ok' bila semua lapisan beres; 'warn' bila ada lapisan yang gagal
# walau backup inti selesai (dihitung di sini karena ikut ditulis ke manifest).
OPS_STATUS="ok"
for s in "$OFFSITE_TAR" "$RESTIC_STAT" "$RESTIC_CHECK" "$RESTIC_OFFSITE" "$CORE_STAT" "$CORE_OFFSITE"; do
  [ "$s" = "gagal" ] && OPS_STATUS="warn"
done
[ "$DB_DUMPED" = 1 ] || OPS_STATUS="warn"

# ---------------------------------------------------------------------------
# MANIFEST FINAL (<arsip>.manifest.json di samping arsip + ikut data ops_events):
# arsip penuh (bila ada) dan arsip inti; sidecar-nya menyusul ke Drive (2/3).
# ---------------------------------------------------------------------------
MANIFEST_JSON="{}"; CORE_MANIFEST_JSON="{}"
finalize_manifest() {  # finalize_manifest <stage.json> <arsip> <bytes> <sha256> <bentuk> <offsite> <tulis-ke>
  python3 "$MANIFEST_PY" finalize --manifest "$1" \
    --archive-name "$(basename "$2")" --archive-bytes "${3:-0}" --archive-sha256 "$4" --archive-form "$5" \
    --offsite "$6" --offsite-remote "${RCLONE_REMOTE:-}" \
    --restic "$RESTIC_STAT" --restic-snapshot "$RESTIC_SNAPSHOT" --restic-check "$RESTIC_CHECK" --restic-offsite "$RESTIC_OFFSITE" \
    --duration "$(( $(date +%s) - START_EPOCH ))" --status "$OPS_STATUS" --write "$7" 2>/dev/null || echo '{}'
}
if [ -f "$MANIFEST_PY" ]; then
  if [ -f "$TMP/manifest.json" ] && [ -n "$FINAL_ARCHIVE" ] && [ -f "$FINAL_ARCHIVE" ]; then
    MANIFEST_JSON="$(finalize_manifest "$TMP/manifest.json" "$FINAL_ARCHIVE" "${ARCHIVE_BYTES:-0}" "$ARCHIVE_SHA256" "$ARSIP_BENTUK" "$OFFSITE_TAR" "$FINAL_ARCHIVE.manifest.json")"
  fi
  if [ -f "$TMP/core-manifest.json" ] && [ "$CORE_STAT" = ok ] && [ -n "$CORE_ENC" ]; then
    CORE_MANIFEST_JSON="$(finalize_manifest "$TMP/core-manifest.json" "$CORE_ENC" "${CORE_BYTES:-0}" "$CORE_SHA256" "terenkripsi (.gpg) — inti harian tanpa workspace" "$CORE_OFFSITE" "$CORE_ENC.manifest.json")"
  fi
fi
[ -n "$MANIFEST_JSON" ] || MANIFEST_JSON="{}"
[ -n "$CORE_MANIFEST_JSON" ] || CORE_MANIFEST_JSON="{}"

# ---------------------------------------------------------------------------
# DRIVE (2/3): sidecar manifest menyusul (best-effort), lalu (3/3) arsip penuh lokal
# yang TERBUKTI ada di Drive dihapus (yang besar hanya di Drive; simpan TAR_LOCAL_KEEP
# terbaru bila > 0) dan retensi Drive diterapkan.
# ---------------------------------------------------------------------------
if [ "$DRIVE_READY" = 1 ]; then
  [ "$CORE_OFFSITE" = ok ] && { drive_push "$CORE_ARCHIVE.manifest.json" || echo "(manifest arsip inti belum terunggah)"; }
  idx=0
  for enc in "${VERIFIED_FULL[@]}"; do
    name="$(basename "$enc")"
    [ -f "$enc.manifest.json" ] && { drive_push "$name.manifest.json" || echo "(manifest $name belum terunggah)"; }
    if [ "$idx" -ge "$TAR_LOCAL_KEEP" ]; then
      rm -f "$enc" "$enc.sha256" "$enc.manifest.json"
      DRIVE_FULL_DELETED=$((DRIVE_FULL_DELETED + 1))
      [ "$enc" = "${FINAL_ARCHIVE:-}" ] && TAR_LOCAL_DELETED=1
      echo "Server: $name dihapus — salinan terverifikasi ada di Drive."
    else
      echo "Server: $name dipertahankan (TAR_LOCAL_KEEP=$TAR_LOCAL_KEEP)."
    fi
    idx=$((idx + 1))
  done
  # Retensi di Drive: arsip penuh simpan DRIVE_TAR_KEEP terbaru; arsip inti DRIVE_CORE_KEEP_DAYS hari.
  mapfile -t DRIVE_OLD < <("$RCLONE_BIN" lsf "$RCLONE_REMOTE" --files-only --include 'computehub-[0-9]*.tar.gz.gpg' 2>/dev/null | sort -r | tail -n +"$((DRIVE_TAR_KEEP + 1))" || true)
  for old in "${DRIVE_OLD[@]}"; do
    [ -n "$old" ] || continue
    "$RCLONE_BIN" delete "$RCLONE_REMOTE" --include "$old*" -q 2>/dev/null || true
    echo "Drive: arsip penuh lama dihapus (simpan $DRIVE_TAR_KEEP terbaru): $old"
  done
  "$RCLONE_BIN" delete "$RCLONE_REMOTE" --include 'computehub-core-*' --min-age "${DRIVE_CORE_KEEP_DAYS}d" -q 2>/dev/null || true
  # Folder versi warisan `rclone sync` (tidak dibuat lagi) dikuras setelah jendelanya lewat.
  # Nama diturunkan dari remote aktif, sehingga uji sandbox tidak menyentuh folder produksi.
  VERS_LIST=("${RCLONE_REMOTE}-versions")
  [ "$RESTIC_DI_DRIVE" = 1 ] && VERS_LIST+=("${RESTIC_REPO#rclone:}-versions")
  for vers in "${VERS_LIST[@]}"; do
    "$RCLONE_BIN" delete "$vers" --min-age "${VERSIONS_KEEP_DAYS}d" -q 2>/dev/null || true
    "$RCLONE_BIN" rmdirs "$vers" --leave-root -q 2>/dev/null || true
  done
fi

# ---------------------------------------------------------------------------
# HEARTBEAT sukses (URL & fungsi didefinisikan di awal skrip). Dikirim HANYA
# bila seluruh backup di atas selesai (set -e: gagal di tengah = trap ERR
# mengirim /fail) -> layanan eksternal mengirim EMAIL bila ping tidak datang.
# ---------------------------------------------------------------------------
if [ -n "$HCURL" ]; then
  if hc_ping; then
    echo "Heartbeat: ping monitoring OK."
  else
    echo "(heartbeat gagal — backup tetap sukses)"
  fi
fi

# --- Laporan ringkas ke Telegram (sukses) ------------------------------------
trap - ERR
# pipefail: `ls`/`du` yang gagal (mis. arsip tar sengaja dilewati) TAK boleh
# menggagalkan backup yang sudah sukses. Pernah terjadi 15 Sep 2026.
JML_INTI="$(ls -1 "$DEST_ENC"/computehub-core-*.tar.gz.gpg 2>/dev/null | wc -l)" || JML_INTI=0
JML_PENUH="$( { ls -1 "$DEST_ENC"/computehub-[0-9]*.tar.gz.gpg "$DEST"/computehub-[0-9]*.tar.gz 2>/dev/null || true; } \
  | sed 's/\.gpg$//' | xargs -rn1 basename | sort -u | wc -l)" || JML_PENUH=0
JML_ARSIP=$((JML_INTI + JML_PENUH))
UKURAN_SERVER="$(du -sh "$DEST_ENC" 2>/dev/null | cut -f1)" || UKURAN_SERVER="?"
if [ "$CORE_STAT" = ok ]; then
  INTI_TXT="$CORE_ARCHIVE ($(numfmt --to=iec "$CORE_BYTES" 2>/dev/null || echo "$CORE_BYTES B"); server $CORE_KEEP_DAYS hari, Drive: $CORE_OFFSITE)"
else
  INTI_TXT="GAGAL"
fi
if [ -n "$ARCHIVE_SIZE" ]; then
  if [ "$TAR_LOCAL_DELETED" = 1 ]; then PENUH_TXT="$(basename "$ARCHIVE") ($ARCHIVE_SIZE, $ARSIP_BENTUK) → Drive terverifikasi, salinan server dihapus"
  else PENUH_TXT="$(basename "$ARCHIVE") ($ARCHIVE_SIZE, $ARSIP_BENTUK) → Drive: $OFFSITE_TAR (salinan server masih ada)"; fi
else
  PENUH_TXT="dilewati (jadwal Minggu)"
fi
if [ "$RESTIC_STAT" = ok ]; then RESTIC_TXT="snapshot ${RESTIC_SNAPSHOT:-?} → ${RESTIC_REPO#rclone:}"; else RESTIC_TXT="$RESTIC_STAT"; fi
SISA_DISK="$(df -h "$DEST" | awk 'NR==2 {print $4" bebas dari "$2}')"
if [ "$DB_DUMPED" = 1 ]; then DB_TXT="disertakan"; else DB_TXT="DILEWATI"; fi
notify "Backup ComputeHub selesai" "Arsip inti : $INTI_TXT
Arsip penuh: $PENUH_TXT
Restic     : $RESTIC_TXT
Dump DB    : $DB_TXT
Durasi     : $(lama)
Server     : $JML_INTI arsip inti + $JML_PENUH arsip penuh ($UKURAN_SERVER)
Disk       : $SISA_DISK"

if [ -n "$ARCHIVE_SIZE" ]; then
  OPS_ARSIP="$(basename "$ARCHIVE")"; OPS_JUDUL="Backup mingguan selesai: arsip penuh → Drive + arsip inti + restic (Drive)"
  [ "$LABEL" = terjadwal ] || OPS_JUDUL="Backup manual (web${REQUESTED_BY:+, $REQUESTED_BY}) selesai: arsip penuh → Drive + arsip inti + restic (Drive)"
  OPS_MANIFEST="$MANIFEST_JSON"
else
  OPS_ARSIP=""; OPS_JUDUL="Backup harian selesai: arsip inti di server + Drive, restic ke Drive"
  OPS_MANIFEST="$CORE_MANIFEST_JSON"
fi
[ "$OPS_STATUS" = "ok" ] || OPS_JUDUL="$OPS_JUDUL — ada lapisan yang gagal"
catat_ops "$OPS_STATUS" "$OPS_JUDUL" "$(printf '{"archive":"%s","archive_size":"%s","archive_form":"%s","db_dump":%s,"offsite_tar":"%s","tar_local_deleted":%s,"core_archive":"%s","core_bytes":%s,"core_sha256":"%s","core_offsite":"%s","restic":"%s","restic_repo":"%s","restic_check":"%s","restic_offsite":"%s","restic_snapshot":"%s","archives_on_server":%s,"core_archives_on_server":%s,"server_backup_size":"%s","disk_free":"%s","trigger":"%s","requested_by":"%s","request_id":"%s","archive_sha256":"%s","manifest":%s}' \
  "$OPS_ARSIP" "${ARCHIVE_SIZE:-}" "$( [ -n "$ARCHIVE_SIZE" ] && echo "$ARSIP_BENTUK" )" "$([ "$DB_DUMPED" = 1 ] && echo true || echo false)" \
  "$OFFSITE_TAR" "$([ "$TAR_LOCAL_DELETED" = 1 ] && echo true || echo false)" "$CORE_ARCHIVE" "${CORE_BYTES:-0}" "$CORE_SHA256" "$CORE_OFFSITE" \
  "$RESTIC_STAT" "$RESTIC_REPO" "$RESTIC_CHECK" "$RESTIC_OFFSITE" "$RESTIC_SNAPSHOT" "${JML_PENUH:-0}" "${JML_INTI:-0}" "$UKURAN_SERVER" "$SISA_DISK" \
  "$([ "$LABEL" = terjadwal ] && echo timer || echo web)" "$REQUESTED_BY" "$REQUEST_ID" "$ARCHIVE_SHA256" "$OPS_MANIFEST")"
