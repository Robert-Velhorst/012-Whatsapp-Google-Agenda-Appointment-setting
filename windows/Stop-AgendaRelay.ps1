[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$runtimeModule = Join-Path $PSScriptRoot 'AgendaRelay.Runtime.psm1'
Import-Module $runtimeModule -Force
$Root = Split-Path -Parent $PSScriptRoot
$state = Join-Path $Root "data\runtime\standalone.json"
if (-not (Test-Path -LiteralPath $state)) { Write-Host "Agenda Relay is not running."; return }
$runtime = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
$stillRunning = $false
foreach ($role in @('web','worker')) {
    $id = 0
    $property = if ($role -eq 'web') { 'webPid' } else { 'workerPid' }
    if (-not [int]::TryParse([string]$runtime.$property, [ref]$id) -or $id -lt 1) {
        Write-Warning "Standalone state has an invalid $role process ID; no process was stopped for that role."
        continue
    }
    $process = Get-AgendaRelayProcess -ProcessId $id -Root $Root -Role $role
    if ($process) {
        Stop-Process -Id $id -Force
        try { Wait-Process -Id $id -Timeout 5 -ErrorAction Stop } catch {}
        if (Get-AgendaRelayProcess -ProcessId $id -Root $Root -Role $role) {
            Write-Warning "Agenda Relay $role process $id is still running; runtime state will be retained so it can be checked again."
            $stillRunning = $true
        }
    } else {
        Write-Warning "Process ID $id is no longer the recorded Agenda Relay $role process; it was left untouched."
    }
}
if ($stillRunning) { throw "Agenda Relay did not stop completely. Review the warnings above and retry after resolving the remaining process." }
Remove-Item -LiteralPath $state -Force
Write-Host "Agenda Relay processes stopped; standalone runtime state removed."
