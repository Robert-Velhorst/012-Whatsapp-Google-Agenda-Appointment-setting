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
    DATA_ENCRYPTION_KEY = "package-test-old-encryption-key-01234567890123456789012345678901"
    NEW_DATA_ENCRYPTION_KEY = "package-test-new-encryption-key-01234567890123456789012345678901"
}
$PreviousEnvironment = @{}
$process = $null
try {
    foreach ($name in $TestEnvironment.Keys) {
        $PreviousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $TestEnvironment[$name], "Process")
    }

    # Exercise the packaged command router and the exact offline rotation path.
    & $Executable migrate
    if ($LASTEXITCODE -ne 0) { throw "Packaged migrate command failed before key-rotation smoke test." }
    $passwordArgument = "SyntheticOnly-NoSecret-123!"
    $passwordRejectionOutput = @(& $Executable hash-password $passwordArgument 2>&1 | ForEach-Object { $_.ToString() })
    $passwordRejectionExitCode = $LASTEXITCODE
    if ($passwordRejectionExitCode -ne 2) { throw "Packaged hash-password accepted a command-line password or returned an unexpected exit code: $passwordRejectionExitCode." }
    if (($passwordRejectionOutput -join "`n") -notmatch "does not accept password arguments") { throw "Packaged hash-password did not report its secure-prompt requirement." }
    if (($passwordRejectionOutput -join "`n").Contains($passwordArgument)) { throw "Packaged hash-password echoed a command-line password argument." }
    $seedSmokeData = @'
from scheduler.config import Settings
from scheduler.crypto import CryptoBox
from scheduler.store import Store

settings = Settings.from_env()
store = Store(settings.database_path, CryptoBox(settings.data_encryption_key))
try:
    store.ensure_workspace(settings.workspace_id, "Package smoke test", settings.timezone)
    contact_id = store.upsert_contact(settings.workspace_id, "31600000000", settings.timezone, display_name="Synthetic package contact")
    ingest_status = store.accept_inbound_message(
        settings.workspace_id, "wamid.package-smoke", "31600000000", "Synthetic encrypted message",
        "2030-01-07T09:00:00+00:00", max_per_sender=10, max_total=60,
    )
    if ingest_status != "accepted":
        raise RuntimeError(f"Could not store synthetic package-smoke message: {ingest_status}.")
    request_id = store.create_request(
        settings.workspace_id, contact_id, "wamid.package-smoke", "Synthetic package smoke", 30,
        settings.timezone, "2030-01-07T10:00:00+01:00", 0.95,
    )
    store.create_proposal(settings.workspace_id, request_id, "Synthetic encrypted reply", ["2030-01-07T10:00:00+01:00"])
    with store.connect() as db:
        encrypted_count = db.execute("SELECT (SELECT COUNT(*) FROM inbound_messages WHERE body_ciphertext IS NOT NULL) + (SELECT COUNT(*) FROM proposals WHERE reply_ciphertext IS NOT NULL) + (SELECT COUNT(*) FROM proposals WHERE booking_token_ciphertext IS NOT NULL)").fetchone()[0]
    if encrypted_count != 3:
        raise RuntimeError(f"Expected three encrypted smoke-test values, found {encrypted_count}.")
    print(f"Seeded {encrypted_count} encrypted package-smoke values.")
finally:
    store.close()
'@
    $seedSmokeData | & .\.venv\Scripts\python.exe -
    if ($LASTEXITCODE -ne 0) { throw "Could not seed encrypted package smoke-test data." }
    $RotatedDirectory = Join-Path $DataDirectory "rotated"
    $rotationOutput = & $Executable rotate-encryption-key --output-dir $RotatedDirectory
    if ($LASTEXITCODE -ne 0) { throw "Packaged encryption-key rotation failed: $($rotationOutput -join ' ')" }
    $rotation = ($rotationOutput -join [Environment]::NewLine) | ConvertFrom-Json
    if ($rotation.encrypted_database_values_rotated -ne 3) { throw "Expected the package to rotate three encrypted smoke-test values; it rotated $($rotation.encrypted_database_values_rotated)." }
    if (-not (Test-Path -LiteralPath (Join-Path $RotatedDirectory "scheduler.sqlite3"))) { throw "Rotation did not publish its validated database." }
    $TestEnvironment["DATABASE_PATH"] = Join-Path $RotatedDirectory "scheduler.sqlite3"
    $TestEnvironment["GOOGLE_TOKEN_FILE"] = Join-Path $RotatedDirectory "google-token.json"
    $TestEnvironment["DATA_ENCRYPTION_KEY"] = $TestEnvironment["NEW_DATA_ENCRYPTION_KEY"]
    $TestEnvironment["NEW_DATA_ENCRYPTION_KEY"] = ""
    foreach ($name in $TestEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $TestEnvironment[$name], "Process")
    }
    & $Executable migrate
    if ($LASTEXITCODE -ne 0) { throw "Packaged application could not open the rotated database with the new key." }
    $backupOutput = & $Executable backup
    if ($LASTEXITCODE -ne 0) { throw "Packaged default backup command failed: $($backupOutput -join ' ')" }
    $BackupPath = [IO.Path]::GetFullPath(($backupOutput | Select-Object -Last 1).ToString().Trim())
    $ExpectedBackupDirectory = [IO.Path]::GetFullPath((Join-Path $RotatedDirectory "backups"))
    if (-not [string]::Equals((Split-Path -Parent $BackupPath), $ExpectedBackupDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Packaged default backup was written outside the configured data directory: $BackupPath"
    }
    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) { throw "Packaged backup command reported success without creating the backup file." }

} finally {
    foreach ($name in $TestEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $PreviousEnvironment[$name], "Process")
    }
}
try {
    $succeeded = $false
    $health = $null
    foreach ($name in $TestEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $TestEnvironment[$name], "Process")
    }
    $process = Start-Process -FilePath $Executable -WorkingDirectory $RunDirectory -RedirectStandardOutput (Join-Path $LogDirectory "package-test.out.log") -RedirectStandardError (Join-Path $LogDirectory "package-test.err.log") -WindowStyle Hidden -PassThru
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
        encryptionRotation = $rotation.encrypted_database_values_rotated
        defaultBackupCreated = (Test-Path -LiteralPath $BackupPath -PathType Leaf)
        workingSetMiB = [Math]::Round($running.WorkingSet64 / 1MB, 1)
        logs = $null
    } | ConvertTo-Json
    $succeeded = $true
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        [void]$process.WaitForExit(10000)
    }

    $processStopped = $true
    if ($process) {
        $processStopped = $process.HasExited -or -not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)
    }
    foreach ($name in $TestEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $PreviousEnvironment[$name], "Process")
    }
    if ($succeeded -and $processStopped) {
        $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
        $testRootPath = [IO.Path]::GetFullPath($TestRoot)
        $testRootParent = Split-Path -Parent $testRootPath
        $testRootName = Split-Path -Leaf $testRootPath
        $ownsTestRoot = [string]::Equals($testRootParent, $temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and $testRootName -match '^AgendaRelay-package-test-[0-9a-f]{32}$'
        if ($ownsTestRoot -and (Test-Path -LiteralPath $testRootPath)) {
            Remove-Item -LiteralPath $testRootPath -Recurse -Force
        } elseif (-not $ownsTestRoot) {
            Write-Warning "Smoke-test artifacts were not removed because the temporary directory could not be verified: $testRootPath"
        }
    } elseif ($succeeded) {
        Write-Warning "The package smoke test passed, but its process exit was not confirmed. Diagnostic artifacts were retained at $TestRoot."
    }
}
