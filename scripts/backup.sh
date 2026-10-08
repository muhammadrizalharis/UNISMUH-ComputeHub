#!/usr/bin/env bash
# Backup data ComputeHub: workspace persisten /persist (kerja mahasiswa) + konfigurasi
# (.env) + dump DB (opsional, bila pg_dump tersedia). Aman dijalankan kapan saja; dipakai
# oleh systemd --user timer (computehub-backup.timer) secara terjadwal.
#
# Variabel opsional:
#   COMPUTEHUB_ROOT        (default: $HOME/DATA_ICAL/SERVER-KAMPUS)
#   COMPUTEHUB_BACKUP_DIR  (default: $HOME/.computehub/backups)
#   COMPUTEHUB_BACKUP_KEEP (default: 3   — arsip .tar.gz terbaru yang disimpan)
#   COMPUTEHUB_BACKUP_WEEKLY_KEEP / _MONTHLY_KEEP (default: 0 — lapisan lokal mati;
#     riwayat panjang ditangani restic yang menyimpan isi sama hanya sekali)
#   COMPUTEHUB_BACKUP_FORCE_TAR=1  paksa arsip tar penuh hari ini (dipakai tombol
#     "Backup sekarang" di web lewat scripts/ops_agent.py), abaikan jadwal mingguan
#   COMPUTEHUB_BACKUP_LABEL        label manifest (terjadwal | manual-web), plus
#   COMPUTEHUB_BACKUP_REQUESTED_BY / COMPUTEHUB_REQUEST_ID dari agen web
#   Knob SANDBOX (uji skrip tanpa menyentuh produksi; default = produksi):
#   COMPUTEHUB_DATA_DIR, COMPUTEHUB_SKIP_OFFSITE=1, COMPUTEHUB_SKIP_RESTIC=1,
#   COMPUTEHUB_NO_OPS_EVENT=1 (tanpa catatan DB/Telegram), COMPUTEHUB_LOCK_FILE
set -euo pipefail

ROOT="${COMPUTEHUB_ROOT:-$HOME/DATA_ICAL/SERVER-KAMPUS}"
DATA="${COMPUTEHUB_DATA_DIR:-$HOME/.computehub/users}"
DEST="${COMPUTEHUB_BACKUP_DIR:-$HOME/.computehub/backups}"
# KEEP=1 (6 Okt 2026, permintaan Kaprodi "cukup satu backup"): server hanya memegang
# arsip tar TERBARU untuk restore cepat & restore drill; riwayat arsip ada di Drive.
KEEP="${COMPUTEHUB_BACKUP_KEEP:-1}"
# Lapisan mingguan/bulanan LOKAL default MATI: arsip .tar.gz adalah salinan PENUH,
# sehingga satu dataset besar tersalin berulang (pernah membuat 24 GB data menjadi
# 170 GB arsip). Riwayat panjang ditangani restic di bawah (7 harian + 4 mingguan +
# 3 bulanan, dedup + terenkripsi) yang menyimpan isi sama hanya SEKALI.
WEEKLY_KEEP="${COMPUTEHUB_BACKUP_WEEKLY_KEEP:-0}"
MONTHLY_KEEP="${COMPUTEHUB_BACKUP_MONTHLY_KEEP:-0}"
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
# Konfigurasi bersama enkripsi + offsite. WAJIB di LUAR blok tar mingguan di
# bawah: blok restic ikut memakainya, dan skrip ini `set -u` -> kalau variabel
# ini ikut dilewati saat bukan hari tar, restic mati "unbound variable".
# (Pernah terjadi 14-15 Sep 2026: backup gagal total 2 hari.)
# ---------------------------------------------------------------------------
PASSFILE="$HOME/.computehub/backup.pass"
DEST_ENC="${COMPUTEHUB_BACKUP_ENC_DIR:-$HOME/.computehub/backups_enc}"
RCLONE_BIN="${RCLONE_BIN:-$HOME/bin/rclone}"
# Folder tujuan di Drive DIBUAT otomatis oleh rclone (privat secara default).
# Scope drive.file: rclone HANYA bisa melihat/menulis folder buatannya sendiri —
# tak perlu (dan tak bisa) menyimpan link/ID folder manual mana pun.
RCLONE_REMOTE="${COMPUTEHUB_RCLONE_REMOTE:-gdrive:ComputeHub-Backups}"
RCLONE_REMOTE_NAME="${RCLONE_REMOTE%%:*}"
# ANTI-RANSOMWARE: `rclone sync` itu MIRROR -> kalau arsip lokal terenkripsi/terhapus
# malware, salinan bagus di Drive ikut tertimpa/terhapus. Dengan --backup-dir, berkas
# yang akan tertimpa/terhapus dipindah dulu ke folder arsip BERTANGGAL di Drive (bukan
# dihancurkan) -> selalu ada jendela pemulihan meski host terinfeksi. Versi lama di luar
# jendela dibersihkan agar tak tumbuh tanpa batas.
VERSIONS_KEEP_DAYS="${COMPUTEHUB_VERSIONS_KEEP_DAYS:-21}"
# ---------------------------------------------------------------------------
# ARSIP TAR PENUH = MINGGUAN (restic tetap HARIAN di bawah).
# Tar menyalin ULANG seluruh isi tiap kali (21 GB) -> harian berarti ~1 jam
# unggah/hari untuk isi yang nyaris sama, padahal restic sudah memegang riwayat
# harian secara hemat. Dengan KEEP=3, mingguan justru MEMPERPANJANG jangkauan
# mundur tar dari 3 hari menjadi 3 minggu pada disk yang sama.
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
echo "Backup dibuat: $ARCHIVE ($ARCHIVE_SIZE)"

# Rotasi: simpan KEEP arsip terbaru, sisanya dihapus.
mapfile -t OLD < <(ls -1t "$DEST"/computehub-*.tar.gz 2>/dev/null | tail -n +"$((KEEP + 1))")
if [ "${#OLD[@]}" -gt 0 ]; then
  rm -f "${OLD[@]}"
  echo "Hapus ${#OLD[@]} arsip lama (simpan $KEEP terbaru)."
fi
echo "Total arsip: $(ls -1 "$DEST"/computehub-*.tar.gz 2>/dev/null | wc -l)."

# ---------------------------------------------------------------------------
# RETENSI BERJENJANG (GFS ringan) di SERVER (backup utama):
#   harian  : $KEEP arsip (rotasi di atas)
#   mingguan: $DEST/weekly  — 1 arsip/≥7 hari, simpan 8  (≈ 2 bulan)
#   bulanan : $DEST/monthly — 1 arsip/≥28 hari, simpan 6 (≈ 6 bulan)
# Hardlink = 0 byte ekstra (satu inode dipakai bersama); melindungi dari
# kerusakan yang baru ketahuan lama setelah arsip harian terrotasi habis.
# Berbasis UMUR arsip tier terbaru (bukan nama hari) — kebal server mati di
# hari Minggu/tanggal 1.
# ---------------------------------------------------------------------------
tier_link() {  # $1=dir_tier  $2=file_sumber  $3=min_hari  $4=simpan (0 = lapisan mati)
  local dir="$1" src="$2" mindays="$3" keep="$4" newest age=0
  if [ "$keep" -le 0 ] 2>/dev/null; then
    # Lapisan dimatikan: bersihkan sisa lama sekali, lalu berhenti.
    [ -d "$dir" ] && rm -f "$dir"/computehub-* 2>/dev/null || true
    return 0
  fi
  mkdir -p "$dir"
  newest="$(ls -1t "$dir"/computehub-* 2>/dev/null | head -1 || true)"
  if [ -n "$newest" ]; then
    age=$(( ( $(date +%s) - $(stat -c %Y "$newest") ) / 86400 ))
  fi
  if [ -z "$newest" ] || [ "$age" -ge "$mindays" ]; then
    ln "$src" "$dir/$(basename "$src")" 2>/dev/null || cp "$src" "$dir/" || true
    echo "Tier $(basename "$dir"): + $(basename "$src")"
  fi
  mapfile -t OLDT < <(ls -1t "$dir"/computehub-* 2>/dev/null | tail -n +"$((keep + 1))")
  [ "${#OLDT[@]}" -gt 0 ] && rm -f "${OLDT[@]}" || true
}
tier_link "$DEST/weekly"  "$ARCHIVE" 7  "$WEEKLY_KEEP"
tier_link "$DEST/monthly" "$ARCHIVE" 28 "$MONTHLY_KEEP"

# ---------------------------------------------------------------------------
# SALINAN OFFSITE TERENKRIPSI (jaga-jaga server bermasalah total):
#  1) Enkripsi arsip (gpg simetris AES256, passphrase di ~/.computehub/backup.pass,
#     chmod 600). Hasil .gpg di $DEST_ENC (rotasi sama dengan lokal).
#  2) Upload ke Google Drive via rclone remote "gdrive" (scope drive.file =
#     token HANYA bisa akses file buatan rclone, bukan seluruh Drive).
#     `rclone sync` -> retensi di Drive otomatis mengikuti rotasi lokal.
# Semua BEST-EFFORT: tanpa passphrase/rclone/internet -> backup lokal tetap jalan.
# ---------------------------------------------------------------------------

if [ "${COMPUTEHUB_SKIP_OFFSITE:-0}" != 1 ] && command -v gpg >/dev/null 2>&1 && [ -f "$PASSFILE" ]; then
  mkdir -p "$DEST_ENC" && chmod 700 "$DEST_ENC" 2>/dev/null || true
  ENC="$DEST_ENC/$(basename "$ARCHIVE").gpg"
  if gpg --batch --yes --symmetric --cipher-algo AES256 \
       --passphrase-file "$PASSFILE" -o "$ENC" "$ARCHIVE" 2>/dev/null; then
    echo "Terenkripsi: $ENC ($(du -h "$ENC" | cut -f1))"
    ARSIP_BENTUK="terenkripsi (.gpg)"
    FINAL_ARCHIVE="$ENC"
    # Rotasi arsip terenkripsi (KEEP sama) + manifest/sha256 pendampingnya.
    mapfile -t OLDE < <(ls -1t "$DEST_ENC"/computehub-*.tar.gz.gpg 2>/dev/null | tail -n +"$((KEEP + 1))")
    if [ "${#OLDE[@]}" -gt 0 ]; then
      for old in "${OLDE[@]}"; do rm -f "$old" "$old.manifest.json" "$old.sha256"; done
    fi
    # Salinan POLOS dibuang HANYA bila .gpg terbukti identik byte-per-byte dengan
    # aslinya (dekripsi ulang + cmp). Isi yang sama dulu tersimpan dua kali
    # (66 GB + 66 GB, 20 Sep 2026) padahal restore.sh & restore_drill.sh membaca
    # .gpg dan passphrase-nya ada di $PASSFILE. Verifikasi gagal -> polos tetap.
    # COMPUTEHUB_KEEP_PLAIN=1 mengembalikan perilaku lama (simpan keduanya).
    if [ "${COMPUTEHUB_KEEP_PLAIN:-0}" != "1" ]; then
      if gpg --batch --quiet --passphrase-file "$PASSFILE" -d "$ENC" 2>/dev/null | cmp -s - "$ARCHIVE"; then
        rm -f "$ARCHIVE"
        echo "Arsip polos dihapus: .gpg terverifikasi identik (hemat $ARCHIVE_SIZE)."
      else
        echo "!!! Verifikasi .gpg GAGAL — arsip polos DIPERTAHANKAN."
      fi
    fi
    # Tier mingguan/bulanan utk SALINAN terenkripsi juga (subfolder ikut
    # ter-sync rclone di bawah -> retensi berjenjang tercermin di Drive).
    tier_link "$DEST_ENC/weekly"  "$ENC" 7  "$WEEKLY_KEEP"
    tier_link "$DEST_ENC/monthly" "$ENC" 28 "$MONTHLY_KEEP"
    # Upload bila remote rclone sudah dikonfigurasi (rclone config; sekali saja).
    if [ -x "$RCLONE_BIN" ] && "$RCLONE_BIN" listremotes 2>/dev/null | grep -q "^${RCLONE_REMOTE_NAME}:"; then
      ENC_VERSIONS="${RCLONE_REMOTE_NAME}:ComputeHub-Backups-versions"
      if "$RCLONE_BIN" sync "$DEST_ENC" "$RCLONE_REMOTE" \
           --backup-dir "$ENC_VERSIONS/$TS" \
           --include 'computehub-*.tar.gz.gpg' --timeout 10m --retries 2 -q; then
        echo "Offsite OK: tersinkron ke $RCLONE_REMOTE ($("$RCLONE_BIN" lsf "$RCLONE_REMOTE" 2>/dev/null | wc -l) file)."
        OFFSITE_TAR="ok"
        # Buang versi lama di LUAR jendela pemulihan (bukan backup aktif).
        "$RCLONE_BIN" delete "$ENC_VERSIONS" --min-age "${VERSIONS_KEEP_DAYS}d" -q 2>/dev/null || true
        "$RCLONE_BIN" rmdirs "$ENC_VERSIONS" --leave-root -q 2>/dev/null || true
      else
        echo "(offsite GAGAL — jaringan/kuota? backup lokal tetap aman)"
        OFFSITE_TAR="gagal"
      fi
    else
      echo "(offsite dilewati — rclone remote '${RCLONE_REMOTE_NAME}' belum dikonfigurasi; jalankan: rclone config)"
    fi
  else
    echo "(enkripsi gagal — offsite dilewati; backup lokal tetap aman)"
  fi
else
  echo "(enkripsi/offsite dilewati — gpg atau $PASSFILE tidak tersedia)"
fi

# Sidik jari arsip final (.gpg bila ada, kalau tidak tar polos): bukti integritas yang
# dicocokkan restore.sh sebelum memulihkan, dan tampil di rincian backup.
if [ -n "$FINAL_ARCHIVE" ] && [ -f "$FINAL_ARCHIVE" ]; then
  ARCHIVE_BYTES="$(stat -c %s "$FINAL_ARCHIVE")"
  ARCHIVE_SHA256="$(sha256sum "$FINAL_ARCHIVE" | cut -d' ' -f1)" || ARCHIVE_SHA256=""
  [ -n "$ARCHIVE_SHA256" ] && echo "$ARCHIVE_SHA256  $(basename "$FINAL_ARCHIVE")" > "$FINAL_ARCHIVE.sha256"
  echo "SHA256 arsip: ${ARCHIVE_SHA256:0:16}… ($ARCHIVE_BYTES byte)"
fi

fi  # akhir blok arsip tar mingguan

# ---------------------------------------------------------------------------
# RESTIC (incremental + dedup) DI SERVER — lapisan masa depan utk /persist besar:
# repo ~/.computehub/restic-repo, passphrase = backup.pass yang sama. Menyimpan
# snapshot ISI backup (users + .env + db.sql) dgn dedup blok -> saat data
# membengkak, riwayat panjang tetap hemat disk & restore per-file per-tanggal.
# BEST-EFFORT: kegagalan restic TIDAK menggagalkan backup tar utama.
# Restore contoh:  RESTIC_PASSWORD_FILE=~/.computehub/backup.pass \
#   ~/bin/restic -r ~/.computehub/restic-repo restore latest --target /tmp/pulih
# ---------------------------------------------------------------------------
RESTIC_BIN="${RESTIC_BIN:-$HOME/bin/restic}"
RESTIC_REPO="${COMPUTEHUB_RESTIC_REPO:-$HOME/.computehub/restic-repo}"
if [ "${COMPUTEHUB_SKIP_RESTIC:-0}" != 1 ] && [ -x "$RESTIC_BIN" ] && [ -f "$PASSFILE" ]; then
  export RESTIC_PASSWORD_FILE="$PASSFILE" RESTIC_REPOSITORY="$RESTIC_REPO"
  "$RESTIC_BIN" cat config >/dev/null 2>&1 || "$RESTIC_BIN" init >/dev/null 2>&1 || true
  if "$RESTIC_BIN" backup "$TMP" --tag computehub -q >/dev/null 2>&1; then
    RESTIC_SNAPSHOT="$("$RESTIC_BIN" snapshots --json --tag computehub --latest 1 2>/dev/null \
      | python3 -c 'import json,sys; s=json.load(sys.stdin); print(s[-1]["short_id"] if s else "")' 2>/dev/null || true)"
    # Retensi 7 harian / 4 mingguan / 3 bulanan (6 Okt 2026): riwayat lebih panjang
    # ada di salinan Drive; repo lokal dijaga ramping.
    # --group-by host,tags WAJIB: path staging mktemp berbeda tiap hari, sehingga
    # pengelompokan bawaan (host+paths) membuat tiap snapshot grup sendiri dan
    # kebijakan "keep" tidak pernah menghapus apa pun (82 snapshot menumpuk Jul-Okt 2026).
    "$RESTIC_BIN" forget --tag computehub --group-by host,tags --keep-daily 7 --keep-weekly 4 \
      --keep-monthly 3 --prune -q >/dev/null 2>&1 || true
    echo "Restic: snapshot OK (repo $(du -sh "$RESTIC_REPO" 2>/dev/null | cut -f1))."
    RESTIC_STAT="ok"
    # Integritas repo: kerusakan senyap hanya ketahuan saat butuh kalau tak pernah
    # diperiksa. Minggu (hari ke-7) = struktur + baca ulang 5% data sungguhan.
    if [ "$(date +%u)" = "7" ]; then
      if "$RESTIC_BIN" check --read-data-subset=5% -q >/dev/null 2>&1; then
        echo "Restic: integritas OK (struktur + 5% data dibaca ulang)."
        RESTIC_CHECK="ok"
      else
        echo "!!! Restic: PERIKSA INTEGRITAS GAGAL — repo mungkin rusak."
        RESTIC_CHECK="gagal"
        echo "    Jalankan: RESTIC_PASSWORD_FILE=$PASSFILE $RESTIC_BIN -r $RESTIC_REPO check --read-data"
      fi
    fi
    # Salinan repo restic ke Drive (repo terenkripsi native AES oleh restic;
    # pack file immutable -> rclone hanya transfer file baru, hemat bandwidth).
    if [ -x "$RCLONE_BIN" ] && "$RCLONE_BIN" listremotes 2>/dev/null | grep -q "^${RCLONE_REMOTE_NAME}:"; then
      RESTIC_VERSIONS="${RCLONE_REMOTE_NAME}:ComputeHub-Restic-versions"
      if "$RCLONE_BIN" sync "$RESTIC_REPO" "${RCLONE_REMOTE_NAME}:ComputeHub-Restic" \
           --backup-dir "$RESTIC_VERSIONS/$TS" \
           --timeout 15m --retries 2 -q; then
        echo "Restic offsite OK: repo tersinkron ke ${RCLONE_REMOTE_NAME}:ComputeHub-Restic."
        RESTIC_OFFSITE="ok"
        "$RCLONE_BIN" delete "$RESTIC_VERSIONS" --min-age "${VERSIONS_KEEP_DAYS}d" -q 2>/dev/null || true
        "$RCLONE_BIN" rmdirs "$RESTIC_VERSIONS" --leave-root -q 2>/dev/null || true
      else
        echo "(restic offsite GAGAL — repo lokal tetap aman)"
        RESTIC_OFFSITE="gagal"
      fi
    fi
  else
    echo "(restic gagal — backup tar utama tetap aman)"
    RESTIC_STAT="gagal"
  fi
else
  echo "(restic dilewati — binary/passphrase tidak tersedia)"
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
# Arsip yang dihitung = .gpg (tar polos dibuang setelah terverifikasi) + polos
# yang masih tersisa (enkripsi gagal / KEEP_PLAIN) tanpa dobel hitung.
JML_ARSIP="$( { ls -1 "$DEST_ENC"/computehub-*.tar.gz.gpg "$DEST"/computehub-*.tar.gz 2>/dev/null || true; } \
  | sed 's/\.gpg$//' | xargs -rn1 basename | sort -u | wc -l)" || JML_ARSIP=0
if [ -n "$ARCHIVE_SIZE" ]; then
  ARSIP_TXT="$(basename "$ARCHIVE") ($ARCHIVE_SIZE, $ARSIP_BENTUK)"
else
  ARSIP_TXT="dilewati (jadwal mingguan) — restic tetap jalan"
fi
SISA_DISK="$(df -h "$DEST" | awk 'NR==2 {print $4" bebas dari "$2}')"
if [ "$DB_DUMPED" = 1 ]; then DB_TXT="disertakan"; else DB_TXT="DILEWATI"; fi
notify "Backup ComputeHub selesai" "Arsip   : $ARSIP_TXT
Dump DB : $DB_TXT
Durasi  : $(lama)
Retensi : $JML_ARSIP arsip tar di server (terenkripsi)
Disk    : $SISA_DISK"

# Bukti ke DB: 'ok' bila semua lapisan beres; 'warn' bila ada lapisan sekunder
# (restic/offsite/dump) yang gagal walau backup utama selesai.
OPS_STATUS="ok"
for s in "$OFFSITE_TAR" "$RESTIC_STAT" "$RESTIC_CHECK" "$RESTIC_OFFSITE"; do
  [ "$s" = "gagal" ] && OPS_STATUS="warn"
done
[ "$DB_DUMPED" = 1 ] || OPS_STATUS="warn"
if [ -n "$ARCHIVE_SIZE" ]; then
  OPS_ARSIP="$(basename "$ARCHIVE")"; OPS_JUDUL="Backup selesai: arsip tar + restic"
  [ "$LABEL" = terjadwal ] || OPS_JUDUL="Backup manual (web${REQUESTED_BY:+, $REQUESTED_BY}) selesai: arsip tar + restic"
else
  OPS_ARSIP=""; OPS_JUDUL="Backup selesai: restic harian (arsip tar dilewati, jadwal mingguan)"
fi
[ "$OPS_STATUS" = "ok" ] || OPS_JUDUL="$OPS_JUDUL — ada lapisan yang gagal"
# Manifest final: ditulis di samping arsip (<arsip>.manifest.json) + ikut kolom data ops_events,
# sehingga rincian tetap bisa dibuka di web walau arsipnya sudah dirotasi.
MANIFEST_JSON="{}"
if [ -f "$MANIFEST_PY" ] && [ -f "$TMP/manifest.json" ]; then
  MANIFEST_OUT=""
  [ -n "$FINAL_ARCHIVE" ] && MANIFEST_OUT="$FINAL_ARCHIVE.manifest.json"
  MANIFEST_JSON="$(python3 "$MANIFEST_PY" finalize --manifest "$TMP/manifest.json" \
    --archive-name "$( [ -n "$FINAL_ARCHIVE" ] && basename "$FINAL_ARCHIVE" )" --archive-bytes "${ARCHIVE_BYTES:-0}" \
    --archive-sha256 "$ARCHIVE_SHA256" --archive-form "$ARSIP_BENTUK" \
    --offsite "$OFFSITE_TAR" --offsite-remote "${RCLONE_REMOTE:-}" \
    --restic "$RESTIC_STAT" --restic-snapshot "$RESTIC_SNAPSHOT" --restic-check "$RESTIC_CHECK" --restic-offsite "$RESTIC_OFFSITE" \
    --duration "$(( $(date +%s) - START_EPOCH ))" --status "$OPS_STATUS" ${MANIFEST_OUT:+--write "$MANIFEST_OUT"} 2>/dev/null || echo '{}')"
  [ -n "$MANIFEST_JSON" ] || MANIFEST_JSON="{}"
fi
catat_ops "$OPS_STATUS" "$OPS_JUDUL" "$(printf '{"archive":"%s","archive_size":"%s","archive_form":"%s","db_dump":%s,"offsite_tar":"%s","restic":"%s","restic_check":"%s","restic_offsite":"%s","restic_snapshot":"%s","archives_on_server":%s,"disk_free":"%s","trigger":"%s","requested_by":"%s","request_id":"%s","archive_sha256":"%s","manifest":%s}' \
  "$OPS_ARSIP" "${ARCHIVE_SIZE:-}" "$ARSIP_BENTUK" "$([ "$DB_DUMPED" = 1 ] && echo true || echo false)" \
  "$OFFSITE_TAR" "$RESTIC_STAT" "$RESTIC_CHECK" "$RESTIC_OFFSITE" "$RESTIC_SNAPSHOT" "${JML_ARSIP:-0}" "$SISA_DISK" \
  "$([ "$LABEL" = terjadwal ] && echo timer || echo web)" "$REQUESTED_BY" "$REQUEST_ID" "$ARCHIVE_SHA256" "$MANIFEST_JSON")"
