#!/usr/bin/env bash
# Pastikan semua mount NFS ComputeHub (data termigrasi di VM) siap sebelum
# container backend start. Mencegah bind-mount docker menangkap folder kosong
# bila VM/NFS belum siap setelah pemadaman listrik / reboot.
set -u

VM_IP="10.33.33.105"
MOUNTS=(
  "/home/muhammadrizalharis/.computehub/users"
  "/home/muhammadrizalharis/.computehub/images"
  "/home/muhammadrizalharis/.computehub/shared_models"
  "/home/muhammadrizalharis/.computehub/devbox"
)
MAX_WAIT=120   # detik total
INTERVAL=3

log(){ echo "[ensure-nfs] $*"; }

deadline=$(( $(date +%s) + MAX_WAIT ))
while :; do
  # 1) tunggu VM bisa diraih
  if ! ping -c1 -W2 "$VM_IP" >/dev/null 2>&1; then
    log "VM $VM_IP belum bisa diraih, menunggu..."
  else
    # 2) coba mount semua yang belum ter-mount
    for mp in "${MOUNTS[@]}"; do
      if ! mountpoint -q "$mp"; then
        sudo -n mount "$mp" >/dev/null 2>&1 || true
      fi
    done
  fi

  # 3) cek apakah semua sudah ter-mount
  all_ok=1
  for mp in "${MOUNTS[@]}"; do
    mountpoint -q "$mp" || all_ok=0
  done
  if [ "$all_ok" -eq 1 ]; then
    log "Semua NFS ter-mount. OK."
    exit 0
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    log "TIMEOUT ${MAX_WAIT}s: sebagian NFS belum ter-mount:"
    for mp in "${MOUNTS[@]}"; do
      mountpoint -q "$mp" && log "  OK   $mp" || log "  GAGAL $mp"
    done
    # Jangan blokir start selamanya; keluar non-zero agar systemd retry (Restart=always)
    exit 1
  fi
  sleep "$INTERVAL"
done
