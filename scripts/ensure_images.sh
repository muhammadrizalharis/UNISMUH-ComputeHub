#!/usr/bin/env bash
# Antisipasi `docker image prune -a` / `docker system prune -a` oleh pengguna lain
# di daemon Docker BERSAMA (pernah menghapus ch-compute pada 13 Jul 2026):
#
#  1. JANGKAR  : tiap image ComputeHub dipegang satu container kecil yang BERJALAN
#                (`sleep infinity`, tanpa GPU/jaringan/mount, RAM <1 MB). Container
#                berjalan tak pernah disentuh prune -> image di baliknya ikut aman.
#  2. DETEKSI  : --check keluar 1 bila ada image hilang (dipanggil watchdog tiap 5 mnt).
#  3. PEMULIHAN: image yang hilang dibangun ulang dari Dockerfile repo (retry, karena
#                jaringan kampus sering reset), lalu jangkarnya dipasang lagi. Hasil
#                dicatat ke ops_events (Pengaturan > Cadangan & Pemulihan) + Telegram.
#
# Pemakaian:
#   ensure_images.sh            # pastikan semua image ada (build bila perlu) + jangkar
#   ensure_images.sh --check    # hanya periksa; cetak yang hilang; exit 1 bila ada
#   ensure_images.sh --anchors  # hanya pasang/perbaiki jangkar (tanpa build)
#   ensure_images.sh --status   # ringkasan image + jangkar
set -uo pipefail

ROOT="${COMPUTEHUB_ROOT:-$HOME/DATA_ICAL/SERVER-KAMPUS}"
BACKEND="$ROOT/backend"
LOG_DIR="$HOME/.computehub/logs"
LOCK="$HOME/.computehub/ensure-images.lock"
OPS_EVENT="$ROOT/scripts/ops_event.py"
NOTIFY="$ROOT/scripts/notify_telegram.py"
RETRIES="${COMPUTEHUB_BUILD_RETRIES:-8}"
mkdir -p "$LOG_DIR"

# docker langsung bila boleh, kalau tidak lewat sudo -n (pola backup.sh).
if docker ps >/dev/null 2>&1; then DOCKER=(docker); else DOCKER=(sudo -n /usr/bin/docker); fi

# image|Dockerfile|context|build-arg (kosong = tidak ada)
IMAGES=(
  "ch-compute:latest|docker/ch-compute.Dockerfile|docker|"
  "ch-compute:py311|docker/ch-compute-py.Dockerfile|docker|PYTHON_VERSION=3.11"
  "ch-compute:py312|docker/ch-compute-py.Dockerfile|docker|PYTHON_VERSION=3.12"
  "ch-compute:py313|docker/ch-compute-py313.Dockerfile|docker|"
  "ch-app:latest|docker/ch-app.Dockerfile|.|"
)

anchor_name() { echo "ch-anchor-$(echo "$1" | tr ':/' '--')"; }

image_ada() { "${DOCKER[@]}" image inspect "$1" >/dev/null 2>&1; }

anchor_jalan() {
  [ "$("${DOCKER[@]}" inspect -f '{{.State.Running}}' "$(anchor_name "$1")" 2>/dev/null)" = "true" ]
}

pasang_jangkar() {  # pasang_jangkar <image>
  local img="$1" nama; nama="$(anchor_name "$img")"
  anchor_jalan "$img" && return 0
  "${DOCKER[@]}" rm -f "$nama" >/dev/null 2>&1 || true
  # Container harus ADA sebagai referensi image; isinya hanya `sleep`. Jalan sebagai
  # nobody, read-only, tanpa jaringan/capability -> tidak bisa dipakai apa pun.
  if "${DOCKER[@]}" run -d --name "$nama" --restart unless-stopped \
       --label computehub.role=image-anchor --label "computehub.image=$img" \
       --network none --read-only --user 65534:65534 --cap-drop ALL \
       --security-opt no-new-privileges --memory 16m --cpus 0.05 --pids-limit 4 \
       --entrypoint sleep "$img" infinity >/dev/null 2>&1; then
    echo "Jangkar dipasang: $nama -> $img"
  else
    echo "!!! Gagal memasang jangkar untuk $img"
    return 1
  fi
}

catat() {  # catat <status> <judul> <json>
  [ -f "$OPS_EVENT" ] && python3 "$OPS_EVENT" --kind watchdog --status "$1" --title "$2" \
    --data "$3" --source ensure_images.sh >/dev/null 2>&1 || true
}
kabari() { [ -f "$NOTIFY" ] && python3 "$NOTIFY" "$1" "$2" >/dev/null 2>&1 || true; }

siapkan_konteks() {
  # Dockerfile compute mem-COPY salinan requirements dari backend/docker (gitignored).
  for f in requirements-compute.txt requirements-compute-extra.txt requirements-compute-extra2.txt; do
    [ -f "$BACKEND/$f" ] && cp -u "$BACKEND/$f" "$BACKEND/docker/$f"
  done
}

bangun() {  # bangun <image> <dockerfile> <context> <build-arg>
  local img="$1" df="$2" ctx="$3" arg="$4" log n
  log="$LOG_DIR/build-$(echo "$img" | tr ':/' '--')-$(date +%Y%m%d-%H%M%S).log"
  local argv=("${DOCKER[@]}" build -t "$img" -f "$BACKEND/$df")
  [ -n "$arg" ] && argv+=(--build-arg "$arg")
  argv+=("$BACKEND/$ctx")
  for n in $(seq 1 "$RETRIES"); do
    echo "Build $img percobaan $n/$RETRIES (log: $log)"
    if "${argv[@]}" >>"$log" 2>&1; then
      echo "Build $img SELESAI."
      return 0
    fi
    sleep $((n * 20))
  done
  echo "!!! Build $img GAGAL setelah $RETRIES percobaan (log: $log)"
  return 1
}

hilang=()
for entry in "${IMAGES[@]}"; do
  IFS='|' read -r img _ _ _ <<<"$entry"
  image_ada "$img" || hilang+=("$img")
done

case "${1:-}" in
  --check)
    if [ "${#hilang[@]}" -gt 0 ]; then printf '%s\n' "${hilang[@]}"; exit 1; fi
    exit 0 ;;
  --status)
    for entry in "${IMAGES[@]}"; do
      IFS='|' read -r img _ _ _ <<<"$entry"
      printf '%-20s image=%-5s jangkar=%s\n' "$img" \
        "$(image_ada "$img" && echo ada || echo HILANG)" \
        "$(anchor_jalan "$img" && echo jalan || echo tidak)"
    done
    exit 0 ;;
  --anchors)
    rc=0
    for entry in "${IMAGES[@]}"; do
      IFS='|' read -r img _ _ _ <<<"$entry"
      image_ada "$img" && { pasang_jangkar "$img" || rc=1; }
    done
    exit $rc ;;
esac

# Mode penuh: satu proses saja (build 10-15 mnt/image; watchdog bisa memanggil ulang).
exec 9>"$LOCK"
if ! flock -n 9; then echo "ensure_images sudah berjalan (lock $LOCK)."; exit 0; fi

gagal=(); dibangun=()
if [ "${#hilang[@]}" -gt 0 ]; then
  echo "Image hilang: ${hilang[*]}"
  kabari "Image ComputeHub HILANG" "Terdeteksi hilang: ${hilang[*]}. Pembangunan ulang otomatis dimulai (±10-15 menit per image). Kernel/job pada versi itu akan gagal sampai selesai."
  siapkan_konteks
  for entry in "${IMAGES[@]}"; do
    IFS='|' read -r img df ctx arg <<<"$entry"
    image_ada "$img" && continue
    if bangun "$img" "$df" "$ctx" "$arg"; then dibangun+=("$img"); else gagal+=("$img"); fi
  done
fi

for entry in "${IMAGES[@]}"; do
  IFS='|' read -r img _ _ _ <<<"$entry"
  image_ada "$img" && pasang_jangkar "$img"
done

if [ "${#dibangun[@]}" -gt 0 ] || [ "${#gagal[@]}" -gt 0 ]; then
  json="$(printf '{"missing":"%s","rebuilt":"%s","failed":"%s"}' "${hilang[*]}" "${dibangun[*]}" "${gagal[*]}")"
  if [ "${#gagal[@]}" -eq 0 ]; then
    catat warn "Image Docker dibangun ulang otomatis: ${dibangun[*]}" "$json"
    kabari "Image ComputeHub PULIH" "Dibangun ulang: ${dibangun[*]}. Jangkar dipasang agar prune berikutnya tidak menghapusnya."
  else
    catat fail "Image Docker GAGAL dibangun ulang: ${gagal[*]}" "$json"
    kabari "Image ComputeHub GAGAL dipulihkan" "Gagal: ${gagal[*]} (lihat $LOG_DIR). Berhasil: ${dibangun[*]:-tidak ada}."
    exit 1
  fi
fi
exit 0
