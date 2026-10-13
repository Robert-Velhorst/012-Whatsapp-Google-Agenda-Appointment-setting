$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'AgendaRelay.Runtime.psm1') -Force

function Assert-Equal {
    param([object]$Actual, [object]$Expected, [string]$Name)
    if ($Actual -ne $Expected) { throw "$Name expected '$Expected', got '$Actual'." }
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$webExecutable = Join-Path $root '.venv\Scripts\waitress-serve.exe'
$workerExecutable = Join-Path $root '.venv\Scripts\python.exe'
$webProcess = [pscustomobject]@{
    ExecutablePath = $webExecutable
    CommandLine = '"C:\app\.venv\Scripts\waitress-serve.exe" --call --listen 127.0.0.1:5000 scheduler.app:create_app'
}
$workerProcess = [pscustomobject]@{
    ExecutablePath = $workerExecutable
    CommandLine = '"C:\app\.venv\Scripts\python.exe" -m scheduler.cli worker --interval 30'
}
$unrelatedProcess = [pscustomobject]@{
    ExecutablePath = 'C:\Python\python.exe'
    CommandLine = 'python.exe C:\app\tools\cleanup.py'
}
$wrongCommandProcess = [pscustomobject]@{
    ExecutablePath = $webExecutable
    CommandLine = '"C:\app\.venv\Scripts\waitress-serve.exe" --call --listen 127.0.0.1:5000 another.app:create_app'
}

Assert-Equal (Test-AgendaRelayProcessIdentity -Process $webProcess -Root $root -Role web) $true 'Own web process'
Assert-Equal (Test-AgendaRelayProcessIdentity -Process $workerProcess -Root $root -Role worker) $true 'Own worker process'
Assert-Equal (Test-AgendaRelayProcessIdentity -Process $unrelatedProcess -Root $root -Role worker) $false 'Unrelated process with repo path in command line'
Assert-Equal (Test-AgendaRelayProcessIdentity -Process $wrongCommandProcess -Root $root -Role web) $false 'Wrong web command on same executable'

Assert-Equal (Get-AgendaRelayRuntimeAction -WebOwned $true -WorkerOwned $false -HealthOk $true) 'restart-worker' 'Missing worker recovery'
Assert-Equal (Get-AgendaRelayRuntimeAction -WebOwned $true -WorkerOwned $true -HealthOk $true) 'already-running' 'Healthy runtime detection'
Assert-Equal (Get-AgendaRelayRuntimeAction -WebOwned $true -WorkerOwned $false -HealthOk $false) 'unhealthy' 'Unhealthy web handling'
Assert-Equal (Get-AgendaRelayRuntimeAction -WebOwned $false -WorkerOwned $true -HealthOk $false) 'start' 'Stale or reused web PID handling'

$ngrokRoot = Join-Path $env:TEMP 'Agenda Relay ngrok identity test'
$ngrokExecutable = Join-Path $ngrokRoot 'tools\ngrok.exe'
$ngrokConfig = Join-Path $ngrokRoot 'private config\ngrok.yml'
$ngrokAgentConfig = Join-Path $ngrokRoot 'data\runtime\ngrok-agent.yml'
$ngrokRuntime = [pscustomobject]@{
    executablePath = $ngrokExecutable
    configPath = $ngrokConfig
    agentConfigPath = $ngrokAgentConfig
    domain = 'agenda.example.ngrok.app'
    port = 5000
}
$ngrokProcess = [pscustomobject]@{
    ExecutablePath = $ngrokExecutable
    CommandLine = '"ngrok.exe" "http" "--config=' + $ngrokConfig + '" "--config=' + $ngrokAgentConfig + '" "--url=agenda.example.ngrok.app" "http://127.0.0.1:5000" "--log=stdout" "--log-format=json"'
}
$wrongNgrokDomain = [pscustomobject]@{
    ExecutablePath = $ngrokExecutable
    CommandLine = '"ngrok.exe" "http" "--config=' + $ngrokConfig + '" "--config=' + $ngrokAgentConfig + '" "--url=another.example.ngrok.app" "http://127.0.0.1:5000"'
}
$unrelatedNgrok = [pscustomobject]@{
    ExecutablePath = 'C:\Other\ngrok.exe'
    CommandLine = '"ngrok.exe" "http" "--url=agenda.example.ngrok.app" "http://127.0.0.1:5000"'
}
Write-Host "Synthetic ngrok config path: $([IO.Path]::GetFullPath($ngrokConfig))"
Write-Host "Synthetic ngrok command line: $($ngrokProcess.CommandLine)"
Assert-Equal (Test-AgendaRelayNgrokProcessIdentity -Process $ngrokProcess -Runtime $ngrokRuntime -Root $ngrokRoot -Verbose) $true 'Owned ngrok process'
Assert-Equal (Test-AgendaRelayNgrokProcessIdentity -Process $wrongNgrokDomain -Runtime $ngrokRuntime -Root $ngrokRoot) $false 'Other ngrok endpoint'
Assert-Equal (Test-AgendaRelayNgrokProcessIdentity -Process $unrelatedNgrok -Runtime $ngrokRuntime -Root $ngrokRoot) $false 'Unrelated ngrok executable'

Write-Host 'Agenda Relay source-launcher and ngrok process identity checks passed.'
