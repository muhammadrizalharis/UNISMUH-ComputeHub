# ProxyCommand SSH untuk Windows: salurkan stdin/stdout ke WebSocket ComputeHub.
# Memakai .NET ClientWebSocket yang SUDAH ADA di Windows 10/11 (PowerShell 5.1):
# tidak ada yang perlu diunduh atau dipasang, tidak perlu hak administrator.
#
# Dua arah dijalankan dalam SATU thread memakai Task::WaitAny: PowerShell tidak bisa
# menjalankan ScriptBlock di thread .NET biasa (variabelnya tidak ikut terbawa).
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$Token
)

$ErrorActionPreference = 'Stop'
$uri = [Uri]"${Url}?token=$Token"
$cts = New-Object System.Threading.CancellationTokenSource
$ws = $null
# Coba ulang: dari jaringan luar, jabat tangan TLS/WS ke kampus kadang putus (PMTU),
# dan VS Code membuka beberapa koneksi sekaligus -- satu yang tersendat menggagalkan
# semuanya. 401 = pasti ditolak, jangan diulang.
for ($percobaan = 0; $percobaan -lt 6; $percobaan++) {
    try {
        $ws = New-Object System.Net.WebSockets.ClientWebSocket
        $ws.Options.KeepAliveInterval = [TimeSpan]::FromSeconds(30)
        # $null = ... WAJIB: GetResult() pada Task tanpa nilai mengembalikan objek
        # VoidTaskResult yang akan ikut tercetak ke stdout dan merusak aliran SSH.
        $null = $ws.ConnectAsync($uri, $cts.Token).GetAwaiter().GetResult()
        break
    } catch {
        $pesan = $_.Exception.Message
        if ($ws) { try { $ws.Dispose() } catch { } }
        $ws = $null
        if ($pesan -match '401|403') {
            [Console]::Error.WriteLine('[computehub] akses ditolak. Unduh ulang pemasang dari menu Devbox ComputeHub.')
            exit 1
        }
        if ($percobaan -ge 5) {
            [Console]::Error.WriteLine("[computehub] Gagal menyambung setelah beberapa percobaan: $pesan")
            exit 1
        }
        Start-Sleep -Seconds ([Math]::Min(1 + $percobaan, 4))
    }
}

$stdin = [Console]::OpenStandardInput()
$stdout = [Console]::OpenStandardOutput()
$ukuran = 65536
$masuk = New-Object byte[] $ukuran
$keluar = New-Object byte[] $ukuran
# ::new() dipakai, bukan New-Object: PowerShell membongkar array byte[] jadi argumen
# terpisah sehingga konstruktor ArraySegment gagal.
$segKeluar = [System.ArraySegment[byte]]::new($keluar, 0, $ukuran)

$biner = [System.Net.WebSockets.WebSocketMessageType]::Binary
$tutup = [System.Net.WebSockets.WebSocketMessageType]::Close
$tugasBaca = $stdin.ReadAsync($masuk, 0, $ukuran)
$tugasTerima = $ws.ReceiveAsync($segKeluar, $cts.Token)
try {
    while ($true) {
        $mana = [System.Threading.Tasks.Task]::WaitAny([System.Threading.Tasks.Task[]]@($tugasBaca, $tugasTerima))
        if ($mana -eq 0) {
            $n = $tugasBaca.GetAwaiter().GetResult()
            if ($n -le 0) { break }   # ssh menutup stdin -> sesi selesai
            $segMasuk = [System.ArraySegment[byte]]::new($masuk, 0, $n)
            $null = $ws.SendAsync($segMasuk, $biner, $true, $cts.Token).GetAwaiter().GetResult()
            $tugasBaca = $stdin.ReadAsync($masuk, 0, $ukuran)
        } else {
            $hasil = $tugasTerima.GetAwaiter().GetResult()
            if ($hasil.MessageType -eq $tutup) { break }
            if ($hasil.Count -gt 0) {
                $stdout.Write($keluar, 0, $hasil.Count)
                $stdout.Flush()
            }
            $tugasTerima = $ws.ReceiveAsync($segKeluar, $cts.Token)
        }
    }
} catch {
} finally {
    try { $cts.Cancel() } catch { }
    try { $ws.Dispose() } catch { }
}
exit 0
