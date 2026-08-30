#!/usr/bin/env bash
# Pastikan container PENJAGA volume database tetap ada.
#
# Penjaga "mengunci" volume computehub-pgdata dengan me-mount-nya (read-only) di
# sebuah container idle. Selama container ini ada, `docker volume prune` dan
# `docker system prune --volumes` SELALU melewati volume DB -- bahkan bila
# container ComputeHub-postgres sedang di-stop atau terlanjur di-hapus. Ini
# menutup satu-satunya celah di mana prune yang tak sengaja bisa menghapus DB.
#
# Idempoten & best-effort: aman dijalankan berkali-kali (dipanggil harian dari
# scripts/backup.sh). Read-only mount -> tak mungkin menyentuh isi DB.
set -euo pipefail

DOCKER="${COMPUTEHUB_DOCKER_CMD:-sudo -n docker}"
GUARD="${COMPUTEHUB_PGDATA_GUARD:-computehub-pgdata-guard}"
VOLUME="${COMPUTEHUB_PG_VOLUME:-computehub-pgdata}"
IMAGE="${COMPUTEHUB_GUARD_IMAGE:-alpine:latest}"

# Volume DB belum ada (mis. sebelum setup pertama) -> tak ada yang perlu dijaga.
if ! $DOCKER volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "ensure_pgdata_guard: volume $VOLUME belum ada -> dilewati."
  exit 0
fi

# Sudah berjalan -> tidak melakukan apa-apa.
running="$($DOCKER inspect -f '{{.State.Running}}' "$GUARD" 2>/dev/null || true)"
if [ "$running" = "true" ]; then
  echo "ensure_pgdata_guard: $GUARD sudah aktif."
  exit 0
fi

# Ada tapi mati (mis. dihentikan manual / sisa dari image lama) -> buat ulang bersih.
$DOCKER rm -f "$GUARD" >/dev/null 2>&1 || true

$DOCKER run -d --name "$GUARD" --restart always \
  --label purpose="Mengunci volume $VOLUME agar tak terhapus docker volume prune" \
  -v "$VOLUME":/protected:ro "$IMAGE" tail -f /dev/null >/dev/null
echo "ensure_pgdata_guard: $GUARD dibuat (mengunci volume $VOLUME)."
