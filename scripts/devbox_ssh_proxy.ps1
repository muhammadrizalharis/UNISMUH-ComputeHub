# ProxyCommand SSH untuk Windows: salurkan stdin/stdout ke WebSocket ComputeHub.
# Memakai .NET ClientWebSocket yang SUDAH ADA di Windows 10/11 (PowerShell 5.1) —
# tidak ada yang perlu diunduh atau dipasang, tidak perlu hak administrator.
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$Token
)

$ErrorActionPreference = 'Stop'
try {
    $ws = New-Object System.Net.WebSockets.ClientWebSocket
    $cts = New-Object System.Threading.CancellationTokenSource
    $uri = [Uri]"${Url}?token=$Token"
    $ws.Options.KeepAliveInterval = [TimeSpan]::FromSeconds(30)
    $ws.ConnectAsync($uri, $cts.Token).GetAwaiter().GetResult()
} catch {
    [Console]::Error.WriteLine("[computehub] Gagal menyambung: $($_.Exception.Message)")
    [Console]::Error.WriteLine("[computehub] Pastikan sudah login di ComputeHub; bila perlu unduh ulang pemasang dari menu Devbox.")
    exit 1
}

$stdin = [Console]::OpenStandardInput()
$stdout = [Console]::OpenStandardOutput()
$ukuran = 65536

# stdin (ssh) -> WebSocket, di thread terpisah supaya arah sebaliknya tak tertahan.
$pengirim = [System.Threading.Tasks.Task]::Run({
    $penyangga = New-Object byte[] $ukuran
    try {
        while ($true) {
            $n = $stdin.Read($penyangga, 0, $ukuran)
            if ($n -le 0) { break }
            $segmen = New-Object System.ArraySegment[byte] -ArgumentList @(,$penyangga), 0, $n
            $ws.SendAsync($segmen, [System.Net.WebSockets.WebSocketMessageType]::Binary, $true, $cts.Token).GetAwaiter().GetResult()
        }
    } catch { }
    finally { $cts.Cancel() }
})

# WebSocket -> stdout (ssh)
$penyangga = New-Object byte[] $ukuran
$segmen = New-Object System.ArraySegment[byte] -ArgumentList @(,$penyangga), 0, $ukuran
try {
    while ($ws.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        $hasil = $ws.ReceiveAsync($segmen, $cts.Token).GetAwaiter().GetResult()
        if ($hasil.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) { break }
        if ($hasil.Count -gt 0) {
            $stdout.Write($penyangga, 0, $hasil.Count)
            $stdout.Flush()
        }
    }
} catch { }
finally {
    try { $cts.Cancel() } catch { }
    try { $ws.Dispose() } catch { }
}
