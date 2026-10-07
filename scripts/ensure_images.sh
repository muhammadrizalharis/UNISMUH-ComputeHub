#!/usr/bin/env bash
# Antisipasi `docker image prune -a` / `docker system prune -a` oleh pengguna lain
# di daemon Docker BERSAMA (pernah menghapus ch-compute pada 13 Jul 2026):
#
#  1. JANGKAR  : tiap image ComputeHub dipegang satu container kecil yang BERJALAN
#                (`sleep infinity`, tanpa GPU/jaringan/mount, RAM <1 MB). Container
#                berjalan tak pernah disentuh prune -> image di baliknya ikut aman.
#  2. DETEKSI  : --check keluar 1 bila ada image hilang (dipanggil watchdog tiap 5 mnt).
#  3. PEMULIHAN: image yang hilang dipulihkan dari CADANGAN OFFLINE (`docker save`
#                terkompresi zstd di ~/.computehub/images, ±1-2 menit, tanpa internet)
#                bila ada dan hash-nya cocok; kalau tidak, dibangun ulang dari
#                Dockerfile repo (retry, karena jaringan kampus sering reset). Jangkar
#                dipasang lagi; hasil dicatat ke ops_events + Telegram.
#
# Pemakaian:
#   ensure_images.sh            # pastikan semua image ada (pulihkan/build bila perlu) + jangkar
#   ensure_images.sh --check    # hanya periksa; cetak yang hilang; exit 1 bila ada
#   ensure_images.sh --anchors  # hanya pasang/perbaiki jangkar (tanpa build)
#   ensure_images.sh --save     # perbarui cadangan offline (idempoten: lewati bila ID sama)
#   ensure_images.sh --status   # ringkasan image + jangkar + cadangan
set -uo pipefail

ROOT="${COMPUTEHUB_ROOT:-$HOME/DATA_ICAL/SERVER-KAMPUS}"
BACKEND="$ROOT/backend"
LOG_DIR="$HOME/.computehub/logs"
CACHE_DIR="${COMPUTEHUB_IMAGE_CACHE:-$HOME/.computehub/images}"
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
image_id()  { "${DOCKER[@]}" image inspect -f '{{.Id}}' "$1" 2>/dev/null; }

# --- cadangan offline: <CACHE_DIR>/<nama>.tar.zst + <nama>.json (id image, sha256 arsip)
cache_base()     { echo "$CACHE_DIR/$(echo "$1" | tr ':/' '--')"; }
manifest_field() { sed -n "s/.*\"$2\": *\"\([^\"]*\)\".*/\1/p" "$1" 2>/dev/null | head -1; }

cadangan_status() {  # segar | basi | tidak  (murah: bandingkan ID saja, tanpa hash)
  local base; base="$(cache_base "$1")"
  [ -s "$base.tar.zst" ] && [ -s "$base.json" ] || { echo tidak; return; }
  [ "$(manifest_field "$base.json" id)" = "$(image_id "$1")" ] && echo segar || echo basi
}

simpan_cadangan() {  # simpan_cadangan <image>  (docker save | zstd, prioritas I/O terendah)
  local img="$1" base id ukuran bebas hash bytes
  base="$(cache_base "$img")"; id="$(image_id "$img")"
  [ -n "$id" ] || { echo "!!! $img tidak ada, cadangan dilewati"; return 1; }
  if [ "$(cadangan_status "$img")" = segar ]; then echo "Cadangan $img sudah segar."; return 0; fi
  mkdir -p "$CACHE_DIR" && chmod 700 "$CACHE_DIR"
  # docker save mengalirkan layer tanpa kompresi (~ukuran image); pastikan ruang cukup.
  ukuran="$("${DOCKER[@]}" image inspect -f '{{.Size}}' "$img" 2>/dev/null || echo 0)"
  bebas="$(df --output=avail -B1 "$CACHE_DIR" | tail -1)"
  if [ "$bebas" -lt "$ukuran" ]; then
    echo "!!! Ruang $CACHE_DIR tidak cukup untuk $img (butuh ~$((ukuran/1073741824)) GB)"; return 1
  fi
  echo "Menyimpan cadangan $img ($((ukuran/1073741824)) GB) -> $base.tar.zst"
  rm -f "$base.tar.zst.part"
  if ! "${DOCKER[@]}" save "$img" | nice -n 19 ionice -c3 zstd -q -T0 -3 -o "$base.tar.zst.part"; then
    rm -f "$base.tar.zst.part"; echo "!!! docker save/zstd $img GAGAL"; return 1
  fi
  hash="$(sha256sum "$base.tar.zst.part" | cut -d' ' -f1)"
  bytes="$(stat -c %s "$base.tar.zst.part")"
  printf '{"image": "%s", "id": "%s", "sha256": "%s", "bytes": "%s", "saved_at": "%s"}\n' \
    "$img" "$id" "$hash" "$bytes" "$(date -Iseconds)" > "$base.json.part"
  mv -f "$base.tar.zst.part" "$base.tar.zst" && mv -f "$base.json.part" "$base.json"
  echo "Cadangan $img selesai: $((bytes/1048576)) MB, sha256 ${hash:0:12}..."
}

pulihkan_dari_cadangan() {  # pulihkan_dari_cadangan <image>; exit 1 = tak ada/rusak -> build
  local img="$1" base hash_manifest hash_file
  base="$(cache_base "$img")"
  [ -s "$base.tar.zst" ] && [ -s "$base.json" ] || { echo "Cadangan offline $img tidak ada."; return 1; }
  hash_manifest="$(manifest_field "$base.json" sha256)"
  hash_file="$(sha256sum "$base.tar.zst" | cut -d' ' -f1)"
  # Arsip yang berubah tanpa manifest baru tidak boleh dimuat sebagai image eksekusi.
  if [ -z "$hash_manifest" ] || [ "$hash_manifest" != "$hash_file" ]; then
    echo "!!! Hash cadangan $img TIDAK cocok dengan manifest; cadangan diabaikan."; return 1
  fi
  echo "Memulihkan $img dari cadangan offline ($(manifest_field "$base.json" saved_at))..."
  if zstd -dc "$base.tar.zst" | "${DOCKER[@]}" load >/dev/null && image_ada "$img"; then
    [ "$(image_id "$img")" = "$(manifest_field "$base.json" id)" ] \
      || echo "(peringatan: ID image hasil pulih berbeda dari manifest)"
    echo "Pulih dari cadangan: $img"; return 0
  fi
  echo "!!! docker load $img dari cadangan GAGAL"; return 1
}

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
      printf '%-20s image=%-6s jangkar=%-5s cadangan=%s\n' "$img" \
        "$(image_ada "$img" && echo ada || echo HILANG)" \
        "$(anchor_jalan "$img" && echo jalan || echo tidak)" \
        "$(cadangan_status "$img")"
    done
    exit 0 ;;
  --anchors)
    rc=0
    for entry in "${IMAGES[@]}"; do
      IFS='|' read -r img _ _ _ <<<"$entry"
      image_ada "$img" && { pasang_jangkar "$img" || rc=1; }
    done
    exit $rc ;;
  --save)
    exec 9>"$LOCK"
    if ! flock -n 9; then echo "ensure_images sudah berjalan (lock $LOCK)."; exit 0; fi
    rc=0
    for entry in "${IMAGES[@]}"; do
      IFS='|' read -r img _ _ _ <<<"$entry"
      image_ada "$img" || { echo "!!! $img HILANG — cadangan tidak diperbarui"; rc=1; continue; }
      simpan_cadangan "$img" || rc=1
    done
    du -sh "$CACHE_DIR" 2>/dev/null || true
    exit $rc ;;
esac

# Mode penuh: satu proses saja (build 10-15 mnt/image; watchdog bisa memanggil ulang).
exec 9>"$LOCK"
if ! flock -n 9; then echo "ensure_images sudah berjalan (lock $LOCK)."; exit 0; fi

gagal=(); dibangun=(); dipulihkan=()
if [ "${#hilang[@]}" -gt 0 ]; then
  echo "Image hilang: ${hilang[*]}"
  kabari "Image ComputeHub HILANG" "Terdeteksi hilang: ${hilang[*]}. Pemulihan otomatis dimulai: dari cadangan offline bila ada (±1-2 menit), jika tidak dibangun ulang (±10-15 menit per image). Kernel/job pada versi itu akan gagal sampai selesai."
  for entry in "${IMAGES[@]}"; do
    IFS='|' read -r img df ctx arg <<<"$entry"
    image_ada "$img" && continue
    if pulihkan_dari_cadangan "$img"; then dipulihkan+=("$img"); continue; fi
    siapkan_konteks
    if bangun "$img" "$df" "$ctx" "$arg"; then dibangun+=("$img"); else gagal+=("$img"); fi
  done
fi

for entry in "${IMAGES[@]}"; do
  IFS='|' read -r img _ _ _ <<<"$entry"
  image_ada "$img" && pasang_jangkar "$img"
done

# Image hasil build baru membuat cadangan lamanya basi -> perbarui (best-effort).
for img in "${dibangun[@]}"; do simpan_cadangan "$img" || true; done

if [ "${#dipulihkan[@]}" -gt 0 ] || [ "${#dibangun[@]}" -gt 0 ] || [ "${#gagal[@]}" -gt 0 ]; then
  json="$(printf '{"missing":"%s","restored":"%s","rebuilt":"%s","failed":"%s"}' \
    "${hilang[*]}" "${dipulihkan[*]}" "${dibangun[*]}" "${gagal[*]}")"
  ringkas="dari cadangan offline: ${dipulihkan[*]:-tidak ada}; dibangun ulang: ${dibangun[*]:-tidak ada}"
  if [ "${#gagal[@]}" -eq 0 ]; then
    catat warn "Image Docker dipulihkan otomatis ($ringkas)" "$json"
    kabari "Image ComputeHub PULIH" "Pulih $ringkas. Jangkar dipasang agar prune berikutnya tidak menghapusnya."
  else
    catat fail "Image Docker GAGAL dipulihkan: ${gagal[*]}" "$json"
    kabari "Image ComputeHub GAGAL dipulihkan" "Gagal: ${gagal[*]} (lihat $LOG_DIR). Berhasil $ringkas."
    exit 1
  fi
fi
exit 0
