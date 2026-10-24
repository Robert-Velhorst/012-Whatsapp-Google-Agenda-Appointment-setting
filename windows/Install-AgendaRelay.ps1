[CmdletBinding()]
param([switch]$SkipPassword, [string]$PythonExecutable)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
    & .\.venv\Scripts\python.exe -I -c "import sqlite3,sys; assert sys.version_info[:3]==(3,15,1) and sqlite3.sqlite_version=='3.54.1'"
    if ($LASTEXITCODE -ne 0) { throw "Existing .venv is not the current runtime. Preserve it and use a fresh checkout/environment before upgrading real data." }
} else {
    if (Test-Path -LiteralPath '.venv') { throw 'An incomplete .venv already exists; preserve it before creating a fresh environment.' }
    $PythonCommand = $null
    $PythonArguments = @()
    if ($PythonExecutable) {
        & $PythonExecutable -I -c "import sys; assert sys.version_info[:3]==(3,15,1) and sys.implementation.name=='cpython'"
        if ($LASTEXITCODE -ne 0) { throw 'The supplied interpreter must be CPython 3.15.1.' }
        $PythonCommand = $PythonExecutable
    }
    if (-not $PythonCommand -and (Get-Command py.exe -ErrorAction SilentlyContinue)) {
        foreach ($version in @("3.15t", "3.15")) {
            & py.exe "-$version" -c "import sys; assert sys.version_info[:3]==(3,15,1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $PythonCommand = "py.exe"; $PythonArguments = @("-$version"); break }
        }
    }
    if (-not $PythonCommand -and (Get-Command python.exe -ErrorAction SilentlyContinue)) {
        & python.exe -c "import sys; assert sys.version_info[:3]==(3,15,1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $PythonCommand = "python.exe" }
    }
    if (-not $PythonCommand) { throw "CPython 3.15.1 is required; -PythonExecutable can select an explicit interpreter. The packaged executable does not require Python." }
    & $PythonCommand @PythonArguments tools/prepare_sqlite_runtime.py
    if ($LASTEXITCODE -ne 0) { throw 'Isolated Python/SQLite runtime preparation failed.' }
    $preparedRuntime = Get-Content .runtime/sqlite-runtime.json -Raw | ConvertFrom-Json
    & $preparedRuntime.executable -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Creating the local Python environment failed." }
}
& .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r requirements.lock
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
