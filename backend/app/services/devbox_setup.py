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

cat > "$DIR/devbox_vscode_platform.py" {_heredoc(_proxy_source("devbox_vscode_platform.py"), "PLATFORM_COMPUTEHUB")}
chmod 700 "$DIR/devbox_vscode_platform.py"

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

# Beritahu VS Code bahwa devbox ini LINUX -> tidak menanyakan platform saat connect
# (dan mengoreksi bila sebelumnya salah pilih). Aman: gagal di sini tidak menggagalkan
# pemasangan; pengguna cukup memilih "Linux" sekali bila VS Code tetap bertanya.
"$PY" "$DIR/devbox_vscode_platform.py" {host_alias} linux || true

echo
echo "SELESAI. Komputer ini sudah terhubung ke devbox ComputeHub."
echo "(konfigurasi: $CONFIG)"
echo
echo "Langkah terakhir: kembali ke halaman Devbox ComputeHub,"
echo "lalu klik tombol   Buka di VS Code Desktop"
"""


def build_windows(user_id: int, host_alias: str, private_key: str, token: str, folder: str) -> str:
    """Pemasang Windows berupa .cmd: cukup DOBEL-KLIK, tanpa hak administrator.

    Dibungkus .cmd, bukan .ps1 langsung, karena Windows membuka .ps1 di Notepad saat
    dobel-klik dan menolaknya lewat ExecutionPolicy. Bagian batch hanya membaca berkas
    ini sendiri lalu menjalankan sisanya sebagai PowerShell, sehingga isi skrip tidak
    perlu di-escape sama sekali.
    """
    isi_ps = _windows_powershell(user_id, host_alias, private_key, token, folder)
    return (
        "@echo off\r\n"
        f"title Pemasang ComputeHub ({host_alias})\r\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -Command "
        "\"$t=[IO.File]::ReadAllText('%~f0'); "
        "Invoke-Expression $t.Substring($t.IndexOf('#PSSTART'))\"\r\n"
        "exit /b\r\n"
        "#PSSTART\r\n"
    ) + isi_ps.replace("\n", "\r\n")


def _windows_powershell(
    user_id: int, host_alias: str, private_key: str, token: str, folder: str
) -> str:
    """Isi PowerShell pemasang Windows (dijalankan oleh pembungkus .cmd)."""
    # Here-string @'...'@ bersifat LITERAL: tanda kutip TIDAK boleh di-escape, kalau
    # di-escape isinya ikut rusak (mis. 'Stop' menjadi ''Stop'').
    kunci_ps = private_key.rstrip("\n")
    proxy_ps = _proxy_source("devbox_ssh_proxy.ps1").rstrip("\n")
    return f"""# Pemasang VS Code Desktop untuk devbox ComputeHub ({host_alias}).
# Dijalankan otomatis oleh pembungkus .cmd; tidak perlu dibuka manual.
$ErrorActionPreference = 'Stop'

# USERPROFILE, BUKAN $HOME: di laptop yang punya home drive (mis. join domain)
# $HOME bisa menunjuk H:\, sedangkan OpenSSH dan VS Code selalu membaca
# %USERPROFILE%\\.ssh\\config -> blok konfigurasi tidak akan pernah terbaca.
$rumah = $env:USERPROFILE
if ([string]::IsNullOrWhiteSpace($rumah)) {{ $rumah = $HOME }}
$dir = Join-Path $rumah '.ssh\\computehub'
$config = Join-Path $rumah '.ssh\\config'
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
# Nama lengkap akun dipakai (bukan $env:USERNAME) supaya benar di laptop yang join domain.
$aku = [Security.Principal.WindowsIdentity]::GetCurrent().Name
cmd /c "icacls `"$dir\\id_ed25519`" /inheritance:r /grant:r `"${{aku}}:(R)`"" | Out-Null

$proxy = @'
{proxy_ps}
'@
[IO.File]::WriteAllText("$dir\\devbox_ssh_proxy.ps1", $proxy, (New-Object Text.UTF8Encoding $false))
[IO.File]::WriteAllText("$dir\\token", '{token}', (New-Object Text.ASCIIEncoding))

if (-not (Test-Path $config)) {{ New-Item -ItemType File -Force -Path $config | Out-Null }}
$isi = Get-Content $config -Raw -ErrorAction SilentlyContinue
if ($null -eq $isi) {{ $isi = '' }}
# Buang blok lama -> pemasang aman dijalankan berulang (mis. setelah kunci diganti).
# Penanda di-escape: teksnya memuat tanda kurung yang akan dibaca sebagai grup regex.
$awal = [Regex]::Escape('{_MARK_START}')
$akhir = [Regex]::Escape('{_MARK_END}')
$isi = [Regex]::Replace($isi, "(?ms)^$awal.*?^$akhir\\r?\\n?", '')
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

# VS Code menanyakan "platform remote host" saat pertama connect; devbox ini LINUX.
# Setel remote.SSH.remotePlatform lebih dulu supaya TIDAK ditanya (dan koreksi bila
# sebelumnya salah pilih Windows/macOS). Aman: hanya menulis bila settings.json bisa
# diparse; bila memuat komentar, dibiarkan dan pengguna cukup memilih Linux sekali.
foreach ($edisi in @('Code', 'Code - Insiders', 'VSCodium')) {{
    $sp = Join-Path $env:APPDATA (Join-Path $edisi 'User\settings.json')
    if (-not (Test-Path (Split-Path (Split-Path $sp)))) {{ continue }}
    try {{
        if (Test-Path $sp) {{
            $mentah = Get-Content $sp -Raw
            if ([string]::IsNullOrWhiteSpace($mentah)) {{ $obj = [PSCustomObject]@{{}} }}
            else {{ $obj = $mentah | ConvertFrom-Json -ErrorAction Stop }}
        }} else {{
            New-Item -ItemType Directory -Force -Path (Split-Path $sp) | Out-Null
            $obj = [PSCustomObject]@{{}}
        }}
        $rpKey = 'remote.SSH.remotePlatform'
        if ($null -eq $obj.$rpKey) {{
            $obj | Add-Member -NotePropertyName $rpKey -NotePropertyValue ([PSCustomObject]@{{}}) -Force
        }}
        $obj.$rpKey | Add-Member -NotePropertyName '{host_alias}' -NotePropertyValue 'linux' -Force
        if (Test-Path $sp) {{ Copy-Item $sp "$sp.bak" -Force -ErrorAction SilentlyContinue }}
        ($obj | ConvertTo-Json -Depth 30) | Set-Content -Path $sp -Encoding UTF8
    }} catch {{ }}
}}

# Pastikan hasilnya benar-benar terbaca ssh; kalau tidak, beri tahu sekarang juga
# daripada pengguna bingung karena nama devbox tak muncul di VS Code.
$cek = (& ssh -F "$config" -G {host_alias} 2>&1 | Select-String -SimpleMatch 'proxycommand')
if (-not $cek) {{
    Write-Host ''
    Write-Host "GAGAL: blok konfigurasi tidak terbaca ssh. Berkasnya: $config"
    Read-Host 'Tekan Enter untuk menutup'
    exit 1
}}

Write-Host ''
Write-Host 'SELESAI. Laptop ini sudah terhubung ke devbox ComputeHub.'
Write-Host "(konfigurasi: $config)"
Write-Host ''
Write-Host 'Langkah terakhir: kembali ke halaman Devbox ComputeHub,'
Write-Host 'lalu klik tombol   Buka di VS Code Desktop'
Write-Host ''
Write-Host 'Belum punya extension Remote - SSH? VS Code akan menawarkan memasangnya.'
Write-Host ''
Read-Host 'Tekan Enter untuk menutup'
"""
