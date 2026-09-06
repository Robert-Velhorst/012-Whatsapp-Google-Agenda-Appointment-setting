[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$state = Join-Path $Root "data\runtime\ngrok.json"
if (-not (Test-Path -LiteralPath $state)) { Write-Host "No verified Agenda Relay ngrok tunnel is recorded."; return }
$runtime = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($runtime.pid)" -ErrorAction SilentlyContinue
if ($process -and $process.Name -like "ngrok*") { Stop-Process -Id $runtime.pid -Force }
Remove-Item -LiteralPath $state -Force
Write-Host "Agenda Relay ngrok tunnel stopped."
