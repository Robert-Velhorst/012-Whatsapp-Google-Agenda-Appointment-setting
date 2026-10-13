[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$runtimeModule = Join-Path $PSScriptRoot 'AgendaRelay.Runtime.psm1'
Import-Module $runtimeModule -Force
$Root = Split-Path -Parent $PSScriptRoot
$state = Join-Path $Root "data\runtime\ngrok.json"
if (-not (Test-Path -LiteralPath $state)) { Write-Host "No verified Agenda Relay ngrok tunnel is recorded."; return }
$runtime = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
$id = 0
if (-not [int]::TryParse([string]$runtime.pid, [ref]$id) -or $id -lt 1) {
    throw "The recorded ngrok process ID is invalid. No process was stopped; inspect $state."
}
$processInfo = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
if ($processInfo) {
    if (-not (Test-AgendaRelayNgrokProcessIdentity -Process $processInfo -Runtime $runtime -Root $Root)) {
        Write-Warning "Process ID $id no longer matches the recorded Agenda Relay ngrok executable and command. It was left untouched; runtime state was retained for inspection."
        return
    }
    $process = Get-Process -Id $id -ErrorAction SilentlyContinue
    if (-not $process -or -not $process.Path -or -not [string]::Equals([IO.Path]::GetFullPath([string]$process.Path), [IO.Path]::GetFullPath([string]$runtime.executablePath), [StringComparison]::OrdinalIgnoreCase)) {
        Write-Warning "The ngrok process handle could not be verified against the recorded executable. It was left untouched; runtime state was retained for inspection."
        return
    }
    try {
        $process.Kill()
        if (-not $process.WaitForExit(5000)) { throw "Timed out waiting for the ngrok process to exit." }
    } catch {
        throw "The Agenda Relay ngrok process could not be stopped safely. Runtime state was retained: $($_.Exception.Message)"
    }
    $stillRunning = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
    if ($stillRunning -and (Test-AgendaRelayNgrokProcessIdentity -Process $stillRunning -Runtime $runtime -Root $Root)) {
        throw "The Agenda Relay ngrok process $id is still running. Runtime state was retained so it can be checked again."
    }
}
Remove-Item -LiteralPath $state -Force
Write-Host "Agenda Relay ngrok tunnel stopped."
