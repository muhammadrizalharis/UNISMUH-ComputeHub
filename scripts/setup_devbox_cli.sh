#!/usr/bin/env bash
# Pasang/perbarui CLI VS Code untuk fitur Devbox (ngoding di VS Code, resource server).
#
# CLI ini di-mount READ-ONLY ke setiap container devbox lalu menjalankan
# `code tunnel`. Jalankan sekali saat setup, dan lagi bila ingin memperbarui versi.
#
#   bash scripts/setup_devbox_cli.sh
#
# Env opsional:
#   COMPUTEHUB_DEVBOX_CLI_DIR  folder tujuan (default ~/.computehub/devbox/cli)
set -euo pipefail

CLI_DIR="${COMPUTEHUB_DEVBOX_CLI_DIR:-$HOME/.computehub/devbox/cli}"
# Varian glibc x86_64 — cocok dengan image ch-compute (Ubuntu 22.04).
URL="https://update.code.visualstudio.com/latest/cli-linux-x64/stable"

mkdir -p "$CLI_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Mengunduh CLI VS Code..."
curl -fsSL "$URL" -o "$TMP/cli.tar.gz"
tar -xzf "$TMP/cli.tar.gz" -C "$TMP"
[ -x "$TMP/code" ] || { echo "GAGAL: biner 'code' tidak ditemukan dalam arsip." >&2; exit 1; }

install -m 0755 "$TMP/code" "$CLI_DIR/code"
echo "Terpasang di $CLI_DIR/code"
"$CLI_DIR/code" --version

# HOME per-user dibuat otomatis oleh backend saat devbox dinyalakan.
mkdir -p "${HOME}/.computehub/devbox/homes"
chmod 700 "${HOME}/.computehub/devbox/homes"
echo "Selesai. Aktifkan fitur dengan DEVBOX_ENABLED=true di backend/.env lalu restart."
