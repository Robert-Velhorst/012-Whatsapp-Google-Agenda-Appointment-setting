[CmdletBinding()]
param([switch]$SkipPassword)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    $PythonCommand = $null
    $PythonArguments = @()
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3.13 -c "import sys; assert (3, 11) <= sys.version_info[:2] < (3, 14)" 2>$null
        if ($LASTEXITCODE -eq 0) { $PythonCommand = "py.exe"; $PythonArguments = @("-3.13") }
    }
    if (-not $PythonCommand -and (Get-Command python.exe -ErrorAction SilentlyContinue)) {
        & python.exe -c "import sys; assert (3, 11) <= sys.version_info[:2] < (3, 14)" 2>$null
        if ($LASTEXITCODE -eq 0) { $PythonCommand = "python.exe" }
    }
    if (-not $PythonCommand) { throw "Python 3.11, 3.12, or 3.13 is required for a source installation. The packaged AgendaRelay.exe does not require Python." }
    & $PythonCommand @PythonArguments -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Creating the local Python environment failed." }
}
& .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    $tokens = & .\.venv\Scripts\python.exe -c "import secrets; print('\n'.join(secrets.token_urlsafe(48) for _ in range(4)))"
    $values = @($tokens)
    $content = Get-Content -LiteralPath ".env" -Raw
    $content = $content -replace '(?m)^FLASK_SECRET_KEY=.*$', "FLASK_SECRET_KEY=$($values[0])"
    $content = $content -replace '(?m)^ADMIN_API_TOKEN=.*$', "ADMIN_API_TOKEN=$($values[1])"
    $content = $content -replace '(?m)^DATA_ENCRYPTION_KEY=.*$', "DATA_ENCRYPTION_KEY=$($values[2])"
    $content = $content -replace '(?m)^WHATSAPP_VERIFY_TOKEN=.*$', "WHATSAPP_VERIFY_TOKEN=$($values[3])"
    Set-Content -LiteralPath ".env" -Value $content -Encoding utf8
}

if (-not $SkipPassword) {
    $secure = Read-Host "Create the operator password (12+ characters)" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($plain.Length -lt 12) { throw "Operator password must contain at least 12 characters." }
    $hash = $plain | & .\.venv\Scripts\python.exe -c "import sys; from werkzeug.security import generate_password_hash; print(generate_password_hash(sys.stdin.read().rstrip('\r\n')))"
    $plain = $null
    $content = Get-Content -LiteralPath ".env" -Raw
    $content = $content -replace '(?m)^ADMIN_PASSWORD_HASH=.*$', "ADMIN_PASSWORD_HASH=$hash"
    Set-Content -LiteralPath ".env" -Value $content -Encoding utf8
}

& .\.venv\Scripts\python.exe -m scheduler.cli migrate
if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
Write-Host "Agenda Relay is installed. Add Meta/Google credentials to .env, then run windows\Start-AgendaRelay.cmd."
