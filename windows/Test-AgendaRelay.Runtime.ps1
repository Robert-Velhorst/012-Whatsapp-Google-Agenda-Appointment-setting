$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'AgendaRelay.Runtime.psm1') -Force

function Assert-Equal {
    param([object]$Actual, [object]$Expected, [string]$Name)
    if ($Actual -ne $Expected) { throw "$Name expected '$Expected', got '$Actual'." }
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dotenvRoot = Join-Path $env:TEMP ("AgendaRelay-dotenv-test-" + [guid]::NewGuid().ToString('N'))
$dotenvFile = Join-Path $dotenvRoot '.env'
$pythonExecutable = Join-Path $root '.venv\Scripts\python.exe'
$dotenvNames = @('APP_ENV', 'PUBLIC_BASE_URL', 'GOOGLE_CLIENT_SECRETS_FILE', 'ADMIN_API_TOKEN')
$previousDotenv = @{}
foreach ($name in $dotenvNames) { $previousDotenv[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
New-Item -ItemType Directory -Path $dotenvRoot | Out-Null
try {
    $dotenvContent = [string][char]0xFEFF + "APP_ENV=`"production`"`nPUBLIC_BASE_URL=`"https://agenda.example.com`"`nGOOGLE_CLIENT_SECRETS_FILE=`"C:\Secure Folder\Client #1.json`"`nADMIN_API_TOKEN=`"synthetic=token`"`n"
    [IO.File]::WriteAllText($dotenvFile, $dotenvContent, (New-Object System.Text.UTF8Encoding($false)))
    Import-AgendaRelayEnvironment -EnvironmentFile $dotenvFile -PythonExecutable $pythonExecutable
    Assert-Equal $env:APP_ENV 'production' 'UTF-8 BOM dotenv key'
    Assert-Equal $env:PUBLIC_BASE_URL 'https://agenda.example.com' 'Quoted dotenv URL'
    Assert-Equal $env:GOOGLE_CLIENT_SECRETS_FILE 'C:\Secure Folder\Client #1.json' 'Quoted dotenv path with spaces and comment character'
    Assert-Equal $env:ADMIN_API_TOKEN 'synthetic=token' 'Quoted dotenv value containing equals'
} finally {
    foreach ($name in $dotenvNames) { [Environment]::SetEnvironmentVariable($name, $previousDotenv[$name], 'Process') }
    if (Test-Path -LiteralPath $dotenvRoot) { Remove-Item -LiteralPath $dotenvRoot -Recurse -Force }
}

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

Write-Host 'Agenda Relay source-launcher identity and recovery checks passed.'
