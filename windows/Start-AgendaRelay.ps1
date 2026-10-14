[CmdletBinding()]
param([switch]$OpenBrowser)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$runtimeModule = Join-Path $PSScriptRoot 'AgendaRelay.Runtime.psm1'
Import-Module $runtimeModule -Force
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path -LiteralPath ".env")) { throw "Run Install-AgendaRelay.ps1 first; .env is missing." }
if (-not (Test-Path -LiteralPath ".venv\Scripts\waitress-serve.exe")) { throw "The local runtime is missing; run Install-AgendaRelay.ps1." }

Import-AgendaRelayEnvironment -EnvironmentFile (Join-Path $Root '.env') -PythonExecutable (Join-Path $Root '.venv\Scripts\python.exe')
$port = if ($env:PORT) { [int]$env:PORT } else { 5000 }
$interval = if ($env:WORKER_INTERVAL_SECONDS) { [int]$env:WORKER_INTERVAL_SECONDS } else { 30 }
$runtime = Join-Path $Root "data\runtime"
$logs = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $runtime,$logs | Out-Null
$state = Join-Path $runtime "standalone.json"
if (Test-Path -LiteralPath $state) {
    try { $old = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json }
    catch { throw "The standalone runtime state is unreadable at $state. Inspect or move that file before starting; no processes were changed." }
    $oldPort = 0
    if (-not [int]::TryParse([string]$old.port, [ref]$oldPort) -or $oldPort -lt 1 -or $oldPort -gt 65535) {
        throw "The standalone runtime state contains an invalid port. Inspect $state before starting; no processes were changed."
    }
    $oldWebPid = 0
    $oldWorkerPid = 0
    $oldWeb = $null
    $oldWorker = $null
    if ([int]::TryParse([string]$old.webPid, [ref]$oldWebPid) -and $oldWebPid -gt 0) {
        $oldWeb = Get-AgendaRelayProcess -ProcessId $oldWebPid -Root $Root -Role web
    }
    if ([int]::TryParse([string]$old.workerPid, [ref]$oldWorkerPid) -and $oldWorkerPid -gt 0) {
        $oldWorker = Get-AgendaRelayProcess -ProcessId $oldWorkerPid -Root $Root -Role worker
    }
    $oldHealthy = $false
    if ($oldWeb) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$oldPort/api/health" -TimeoutSec 3
            $oldHealthy = [bool]$health.ok
        } catch { $oldHealthy = $false }
    }
    $action = Get-AgendaRelayRuntimeAction -WebOwned ([bool]$oldWeb) -WorkerOwned ([bool]$oldWorker) -HealthOk $oldHealthy
    if ($action -eq 'already-running') {
        Write-Host "Agenda Relay is already running at http://127.0.0.1:$oldPort"
        if ($OpenBrowser) { Start-Process "http://127.0.0.1:$oldPort" }
        return
    }
    if ($action -eq 'unhealthy') {
        throw "The recorded Agenda Relay web process is present but its health check failed on port $oldPort. Review data\logs\web.err.log and stop it with windows\Stop-AgendaRelay.ps1 before retrying. No process was restarted."
    }
    if ($action -eq 'restart-worker') {
        $restartedWorker = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList @('-m','scheduler.cli','worker','--interval',"$interval") -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $logs "worker.out.log") -RedirectStandardError (Join-Path $logs "worker.err.log") -WindowStyle Hidden -PassThru
        Start-Sleep -Milliseconds 500
        if (-not (Get-AgendaRelayProcess -ProcessId $restartedWorker.Id -Root $Root -Role worker)) {
            throw "The existing web server is healthy, but the due-job worker failed to start. Review data\logs\worker.err.log. The web server was left running."
        }
        try {
            @{ webPid=$oldWebPid; workerPid=$restartedWorker.Id; port=$oldPort; startedAt=$old.startedAt } | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding utf8
        } catch {
            if (Get-AgendaRelayProcess -ProcessId $restartedWorker.Id -Root $Root -Role worker) { Stop-Process -Id $restartedWorker.Id -Force -ErrorAction SilentlyContinue }
            throw "The due-job worker was restarted but its runtime state could not be saved. The new worker was stopped; review permissions on data\runtime and try again."
        }
        Write-Host "Agenda Relay was already running; its missing due-job worker has been restarted at http://127.0.0.1:$oldPort"
        if ($OpenBrowser) { Start-Process "http://127.0.0.1:$oldPort" }
        return
    }
    if ($action -eq 'start' -and $oldWorker) {
        Stop-Process -Id $oldWorkerPid -Force
        try { Wait-Process -Id $oldWorkerPid -Timeout 5 -ErrorAction Stop } catch {}
        if (Get-AgendaRelayProcess -ProcessId $oldWorkerPid -Root $Root -Role worker) {
            throw "A stale Agenda Relay worker could not be stopped safely. No replacement process was started."
        }
    }
}
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    throw "Port $port is already in use by process ID(s) $owners. Set another PORT in .env before starting Agenda Relay."
}

$web = $null
$worker = $null
try {
    $web = Start-Process -FilePath ".venv\Scripts\waitress-serve.exe" -ArgumentList @('--call','--listen',"127.0.0.1:$port",'--threads=4','--connection-limit=100','scheduler.app:create_app') -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $logs "web.out.log") -RedirectStandardError (Join-Path $logs "web.err.log") -WindowStyle Hidden -PassThru
    $worker = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList @('-m','scheduler.cli','worker','--interval',"$interval") -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $logs "worker.out.log") -RedirectStandardError (Join-Path $logs "worker.err.log") -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 500
    if (-not (Get-AgendaRelayProcess -ProcessId $web.Id -Root $Root -Role web)) { throw "The web server process exited or did not match the expected Agenda Relay command. Review data\logs\web.err.log." }
    if (-not (Get-AgendaRelayProcess -ProcessId $worker.Id -Root $Root -Role worker)) { throw "The due-job worker exited or did not match the expected Agenda Relay command. Review data\logs\worker.err.log." }
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
    if ($web -and (Get-AgendaRelayProcess -ProcessId $web.Id -Root $Root -Role web)) { Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue }
    if ($worker -and (Get-AgendaRelayProcess -ProcessId $worker.Id -Root $Root -Role worker)) { Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue }
    throw
}
Write-Host "Agenda Relay is running at http://127.0.0.1:$port"
if ($OpenBrowser) { Start-Process "http://127.0.0.1:$port" }
