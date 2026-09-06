[CmdletBinding()]
param([switch]$OpenBrowser)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path -LiteralPath ".env")) { throw "Run Install-AgendaRelay.ps1 first; .env is missing." }
if (-not (Test-Path -LiteralPath ".venv\Scripts\waitress-serve.exe")) { throw "The local runtime is missing; run Install-AgendaRelay.ps1." }

Get-Content -LiteralPath ".env" | ForEach-Object {
    if ($_ -match '^\s*([^#][A-Za-z0-9_]*)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process") }
}
$port = if ($env:PORT) { [int]$env:PORT } else { 5000 }
$interval = if ($env:WORKER_INTERVAL_SECONDS) { [int]$env:WORKER_INTERVAL_SECONDS } else { 30 }
$runtime = Join-Path $Root "data\runtime"
$logs = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $runtime,$logs | Out-Null
$state = Join-Path $runtime "standalone.json"
if (Test-Path -LiteralPath $state) {
    $old = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
    if (Get-Process -Id $old.webPid -ErrorAction SilentlyContinue) { Write-Host "Agenda Relay is already running at http://127.0.0.1:$port"; return }
}
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    throw "Port $port is already in use by process ID(s) $owners. Set another PORT in .env before starting Agenda Relay."
}

$web = Start-Process -FilePath ".venv\Scripts\waitress-serve.exe" -ArgumentList @('--call','--listen',"127.0.0.1:$port",'--threads=4','--connection-limit=100','scheduler.app:create_app') -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $logs "web.out.log") -RedirectStandardError (Join-Path $logs "web.err.log") -WindowStyle Hidden -PassThru
$worker = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList @('-m','scheduler.cli','worker','--interval',"$interval") -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $logs "worker.out.log") -RedirectStandardError (Join-Path $logs "worker.err.log") -WindowStyle Hidden -PassThru
try {
    $healthy = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 2
            if ($response.ok) { $healthy = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $healthy) { throw "The local health check did not pass. Review data\logs\web.err.log." }
    @{ webPid=$web.Id; workerPid=$worker.Id; port=$port; startedAt=(Get-Date).ToUniversalTime().ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding utf8
} catch {
    Stop-Process -Id $web.Id,$worker.Id -Force -ErrorAction SilentlyContinue
    throw
}
Write-Host "Agenda Relay is running at http://127.0.0.1:$port"
if ($OpenBrowser) { Start-Process "http://127.0.0.1:$port" }
