[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$state = Join-Path $Root "data\runtime\standalone.json"
if (-not (Test-Path -LiteralPath $state)) { Write-Host "Agenda Relay is not running."; return }
$runtime = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
foreach ($id in @($runtime.webPid,$runtime.workerPid)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -like "*$Root*") { Stop-Process -Id $id -Force }
}
Remove-Item -LiteralPath $state -Force
Write-Host "Agenda Relay stopped."
