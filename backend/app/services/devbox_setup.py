"""Pemasang sekali-klik VS Code Desktop (Remote-SSH) untuk devbox.

Tujuan: pengguna TIDAK PERNAH membuat kunci, menyunting ~/.ssh/config, atau memasang
alat apa pun. Satu berkas diunduh dari menu Devbox, dijalankan sekali per laptop, lalu
selamanya cukup: VS Code -> Remote-SSH: Connect to Host -> computehub-<uid>.

Isi berkas pemasang (dibuat di memori, tidak pernah disimpan di server):
  1. kunci privat SSH milik user      -> ~/.ssh/computehub/id_ed25519 (izin 600)
  2. skrip ProxyCommand WebSocket     -> ~/.ssh/computehub/devbox_ssh_proxy.(py|ps1)
  3. blok Host di ~/.ssh/config       -> ditulis di antara penanda, aman ditulis ulang

Kunci privat ikut di dalamnya, jadi endpoint pengunduh WAJIB milik pemiliknya sendiri
dan hasilnya tidak boleh di-cache (lihat routers/devbox.py).
"""

from __future__ import annotations

from app.core.config import BACKEND_DIR, settings

_MARK_START = "# >>> ComputeHub devbox (jangan disunting manual) >>>"
_MARK_END = "# <<< ComputeHub devbox <<<"


def _proxy_source(nama: str) -> str:
    return (BACKEND_DIR.parent / "scripts" / nama).read_text(encoding="utf-8")


def _ws_url(user_id: int) -> str:
    """URL WebSocket publik proxy SSH (wss bila domain publik sudah HTTPS)."""
    dasar = (settings.public_base_url or "").rstrip("/")
    skema = "wss" if dasar.startswith("https://") else "ws"
    tanpa_skema = dasar.split("://", 1)[-1]
    prefix = "/" + (settings.DEVBOX_SSH_PATH or "/devbox-ssh").strip("/")
    return f"{skema}://{tanpa_skema}{prefix}/{int(user_id)}"


def _heredoc(teks: str, penanda: str) -> str:
    """Sisipkan teks apa adanya ke skrip shell (penanda dikutip = tanpa ekspansi)."""
    return f"<< '{penanda}'\n{teks.rstrip()}\n{penanda}"


def build_unix(user_id: int, host_alias: str, private_key: str, token: str, folder: str) -> str:
    """Pemasang macOS/Linux (bash). Idempoten: aman dijalankan berulang."""
    return f"""#!/usr/bin/env bash
# Pemasang VS Code Desktop untuk devbox ComputeHub ({host_alias}).
# Jalankan SEKALI per laptop:  bash {host_alias}-setup.sh
set -euo pipefail

DIR="$HOME/.ssh/computehub"
CONFIG="$HOME/.ssh/config"
mkdir -p "$DIR"
chmod 700 "$HOME/.ssh" "$DIR"

command -v ssh >/dev/null || {{ echo "ssh tidak ditemukan. Pasang OpenSSH lalu ulangi."; exit 1; }}
PY="$(command -v python3 || true)"
[ -n "$PY" ] || {{ echo "python3 tidak ditemukan. Pasang python3 lalu ulangi."; exit 1; }}

cat > "$DIR/id_ed25519" {_heredoc(private_key, "KUNCI_COMPUTEHUB")}
chmod 600 "$DIR/id_ed25519"

cat > "$DIR/devbox_ssh_proxy.py" {_heredoc(_proxy_source("devbox_ssh_proxy.py"), "PROXY_COMPUTEHUB")}
chmod 700 "$DIR/devbox_ssh_proxy.py"

printf '%s' '{token}' > "$DIR/token"
chmod 600 "$DIR/token"

touch "$CONFIG"; chmod 600 "$CONFIG"
# Buang blok lama (kalau ada) lalu tulis yang baru -> aman dijalankan berulang.
awk 'BEGIN{{s=0}} /^{_MARK_START}$/{{s=1}} s==0{{print}} /^{_MARK_END}$/{{s=0}}' \\
    "$CONFIG" > "$CONFIG.computehub.tmp" && mv "$CONFIG.computehub.tmp" "$CONFIG"
cat >> "$CONFIG" <<CONFIG_COMPUTEHUB
{_MARK_START}
Host {host_alias}
    HostName devbox
    User dev
    IdentityFile "$DIR/id_ed25519"
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    UserKnownHostsFile "$DIR/known_hosts"
    ServerAliveInterval 30
    ServerAliveCountMax 4
    ProxyCommand "$PY" "$DIR/devbox_ssh_proxy.py" {_ws_url(user_id)} {token}
{_MARK_END}
CONFIG_COMPUTEHUB

echo
echo "Selesai. Sekarang di VS Code:"
echo "  1. Pasang extension 'Remote - SSH' (sekali saja)."
echo "  2. F1 -> Remote-SSH: Connect to Host -> {host_alias}"
echo "  3. File > Open Folder -> /{folder}"
"""


def build_windows(user_id: int, host_alias: str, private_key: str, token: str, folder: str) -> str:
    """Pemasang Windows (PowerShell). Tidak butuh hak administrator."""
    kunci_ps = private_key.rstrip("\n").replace("'", "''")
    proxy_ps = _proxy_source("devbox_ssh_proxy.ps1").rstrip("\n").replace("'", "''")
    return f"""# Pemasang VS Code Desktop untuk devbox ComputeHub ({host_alias}).
# Jalankan SEKALI per laptop: klik kanan berkas ini -> Run with PowerShell.
# (Bila diblokir kebijakan: buka PowerShell lalu jalankan
#  powershell -ExecutionPolicy Bypass -File .\\{host_alias}-setup.ps1 )
$ErrorActionPreference = 'Stop'

$dir = Join-Path $HOME '.ssh\\computehub'
$config = Join-Path $HOME '.ssh\\config'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {{
    Write-Host 'OpenSSH belum aktif. Buka Settings > Apps > Optional features > OpenSSH Client, lalu ulangi.'
    exit 1
}}

$kunci = @'
{kunci_ps}
'@
# ASCII tanpa BOM: OpenSSH menolak berkas kunci ber-BOM atau berakhiran CRLF.
[IO.File]::WriteAllText("$dir\\id_ed25519", ($kunci -replace "`r`n", "`n").TrimEnd() + "`n", (New-Object Text.ASCIIEncoding))
# Hanya pemilik yang boleh membaca kunci (ssh menolak kunci yang terlalu terbuka).
icacls "$dir\\id_ed25519" /inheritance:r /grant:r "$($env:USERNAME):(R)" | Out-Null

$proxy = @'
{proxy_ps}
'@
[IO.File]::WriteAllText("$dir\\devbox_ssh_proxy.ps1", $proxy, (New-Object Text.UTF8Encoding $false))
[IO.File]::WriteAllText("$dir\\token", '{token}', (New-Object Text.ASCIIEncoding))

if (-not (Test-Path $config)) {{ New-Item -ItemType File -Force -Path $config | Out-Null }}
$isi = Get-Content $config -Raw -ErrorAction SilentlyContinue
if ($null -eq $isi) {{ $isi = '' }}
# Buang blok lama -> pemasang aman dijalankan berulang (mis. setelah kunci diganti).
$pola = '(?ms)^{_MARK_START}.*?^{_MARK_END}\\r?\\n?'
$isi = [Regex]::Replace($isi, $pola, '')
$blok = @"
{_MARK_START}
Host {host_alias}
    HostName devbox
    User dev
    IdentityFile "$dir\\id_ed25519"
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    UserKnownHostsFile "$dir\\known_hosts"
    ServerAliveInterval 30
    ServerAliveCountMax 4
    ProxyCommand powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\\devbox_ssh_proxy.ps1" -Url {_ws_url(user_id)} -Token {token}
{_MARK_END}
"@
[IO.File]::WriteAllText($config, ($isi.TrimEnd() + "`r`n`r`n" + $blok + "`r`n"))

Write-Host ''
Write-Host 'Selesai. Sekarang di VS Code:'
Write-Host "  1. Pasang extension 'Remote - SSH' (sekali saja)."
Write-Host '  2. F1 -> Remote-SSH: Connect to Host -> {host_alias}'
Write-Host '  3. File > Open Folder -> /{folder}'
Write-Host ''
Read-Host 'Tekan Enter untuk menutup'
"""
