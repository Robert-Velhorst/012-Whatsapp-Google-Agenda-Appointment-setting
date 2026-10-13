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
    } else {
        Write-Warning "Process ID $id is no longer the recorded Agenda Relay $role process; it was left untouched."
    }
}
Remove-Item -LiteralPath $state -Force
Write-Host "Agenda Relay stopped."
