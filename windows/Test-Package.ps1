[CmdletBinding()]
param([int]$Port = 5190)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Executable = Join-Path $Root "dist\AgendaRelay\AgendaRelay.exe"
if (-not (Test-Path -LiteralPath $Executable)) { throw "Build the Windows package before testing it." }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Test port $Port is already in use." }
$env:PORT = "$Port"
$env:BIND_HOST = "127.0.0.1"
$logs = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$process = Start-Process -FilePath $Executable -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $logs "package-test.out.log") -RedirectStandardError (Join-Path $logs "package-test.err.log") -WindowStyle Hidden -PassThru
try {
    $health = $null
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
            if ($health.ok) { break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $health -or -not $health.ok) { throw "Packaged executable did not become healthy. Review data\logs\package-test.err.log." }
    $login = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/login" -TimeoutSec 5
    $running = Get-Process -Id $process.Id
    [pscustomobject]@{
        health = $health.ok
        mode = $health.mode
        loginStatus = $login.StatusCode
        loginContainsBrand = $login.Content.Contains("Agenda Relay")
        workingSetMiB = [Math]::Round($running.WorkingSet64 / 1MB, 1)
    } | ConvertTo-Json
} finally {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
