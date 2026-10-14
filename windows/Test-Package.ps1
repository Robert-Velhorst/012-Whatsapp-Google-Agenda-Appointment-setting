[CmdletBinding()]
param(
    [int]$Port = 5190,
    [string]$PackagePath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$PackageDirectory = if ($PackagePath) { [IO.Path]::GetFullPath($PackagePath) } else { Join-Path $Root "dist\AgendaRelay" }
$Executable = Join-Path $PackageDirectory "AgendaRelay.exe"
if (-not (Test-Path -LiteralPath $Executable)) { throw "Build the Windows package before testing it." }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Test port $Port is already in use." }
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ("AgendaRelay-package-test-" + [guid]::NewGuid().ToString("N"))
$RunDirectory = Join-Path $TestRoot "run"
$DataDirectory = Join-Path $TestRoot "data"
$LogDirectory = Join-Path $TestRoot "logs"
New-Item -ItemType Directory -Force -Path $RunDirectory, $DataDirectory, $LogDirectory | Out-Null
$TestEnvironment = @{
    APP_ENV = "development"
    PORT = "$Port"
    BIND_HOST = "127.0.0.1"
    DATABASE_PATH = Join-Path $DataDirectory "package-test.sqlite3"
    GOOGLE_TOKEN_FILE = Join-Path $DataDirectory "google-token.json"
    GOOGLE_CLIENT_SECRETS_FILE = ""
    WHATSAPP_VERIFY_TOKEN = ""
    WHATSAPP_APP_SECRET = ""
    WHATSAPP_ACCESS_TOKEN = ""
    WHATSAPP_PHONE_NUMBER_ID = ""
    WHATSAPP_REMINDER_TEMPLATE = ""
    AUTO_SEND_SUGGESTIONS = "false"
    AUTO_BOOK_CONFIRMED = "false"
    AUTOMATION_PAUSED = "true"
    HAI_CONNECTOR_ENABLED = "false"
    FLASK_SECRET_KEY = "package-test-only-session-secret-0123456789"
    ADMIN_API_TOKEN = "package-test-only-api-token-0123456789"
    ADMIN_PASSWORD_HASH = ""
    DATA_ENCRYPTION_KEY = ""
}
$PreviousEnvironment = @{}
$process = $null
try {
    foreach ($name in $TestEnvironment.Keys) {
        $PreviousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $TestEnvironment[$name], "Process")
    }
    $process = Start-Process -FilePath $Executable -WorkingDirectory $RunDirectory -RedirectStandardOutput (Join-Path $LogDirectory "package-test.out.log") -RedirectStandardError (Join-Path $LogDirectory "package-test.err.log") -WindowStyle Hidden -PassThru
} finally {
    foreach ($name in $TestEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $PreviousEnvironment[$name], "Process")
    }
}
try {
    $health = $null
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
            if ($health.ok) { break }
        } catch {}
        if ($process.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $health -or -not $health.ok) {
        $stderrPath = Join-Path $LogDirectory "package-test.err.log"
        if (Test-Path -LiteralPath $stderrPath) {
            $stderr = (@(Get-Content -LiteralPath $stderrPath | Select-Object -Last 100) -join "`n")
            foreach ($secret in @($TestEnvironment.FLASK_SECRET_KEY, $TestEnvironment.ADMIN_API_TOKEN)) {
                if ($secret) { $stderr = $stderr.Replace($secret, "[REDACTED]") }
            }
            if ($stderr) { Write-Host "Packaged executable stderr (last 100 lines):`n$stderr" }
        }
        throw "Packaged executable did not become healthy. Review $stderrPath."
    }
    $login = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/login" -TimeoutSec 5
    $running = Get-Process -Id $process.Id
    [pscustomobject]@{
        health = $health.ok
        mode = $health.mode
        loginStatus = $login.StatusCode
        loginContainsBrand = $login.Content.Contains("Agenda Relay")
        workingSetMiB = [Math]::Round($running.WorkingSet64 / 1MB, 1)
        logs = $LogDirectory
    } | ConvertTo-Json
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $process.WaitForExit()
    }
}
