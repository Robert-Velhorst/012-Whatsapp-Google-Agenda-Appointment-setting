[CmdletBinding()]
param(
    [string]$OutputPath,
    [string]$WorkPath
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) { throw "Run Install-AgendaRelay.ps1 first." }
$OutputRoot = if ($OutputPath) { [IO.Path]::GetFullPath($OutputPath) } else { Join-Path $Root "dist" }
$BuildWorkPath = if ($WorkPath) {
    [IO.Path]::GetFullPath($WorkPath)
} else {
    Join-Path ([IO.Path]::GetTempPath()) ("AgendaRelay-PyInstaller-" + [guid]::NewGuid().ToString("N"))
}
New-Item -ItemType Directory -Force -Path $OutputRoot, $BuildWorkPath | Out-Null
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-build.lock
if ($LASTEXITCODE -ne 0) { throw "Installing Windows build dependencies failed." }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --workpath $BuildWorkPath --distpath $OutputRoot agenda-relay.spec
if ($LASTEXITCODE -ne 0) { throw "Windows package build failed." }
$PackageDirectory = Join-Path $OutputRoot "AgendaRelay"
Copy-Item -LiteralPath ".env.example" -Destination (Join-Path $PackageDirectory ".env.example") -Force
Copy-Item -LiteralPath "README.md" -Destination (Join-Path $PackageDirectory "README.md") -Force
& tar.exe -a -c -f (Join-Path $OutputRoot "AgendaRelay-Windows-x64.zip") -C $PackageDirectory .
if ($LASTEXITCODE -ne 0) { throw "Creating the Windows ZIP failed." }
Get-FileHash -Algorithm SHA256 (Join-Path $OutputRoot "AgendaRelay-Windows-x64.zip")
