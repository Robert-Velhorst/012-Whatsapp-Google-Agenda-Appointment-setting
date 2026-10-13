[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) { throw "Run Install-AgendaRelay.ps1 first." }
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm agenda-relay.spec
if ($LASTEXITCODE -ne 0) { throw "Windows package build failed." }
Copy-Item -LiteralPath ".env.example" -Destination "dist\AgendaRelay\.env.example" -Force
Copy-Item -LiteralPath "README.md" -Destination "dist\AgendaRelay\README.md" -Force
& tar.exe -a -c -f "dist\AgendaRelay-Windows-x64.zip" -C "dist\AgendaRelay" .
if ($LASTEXITCODE -ne 0) { throw "Creating the Windows ZIP failed." }
Get-FileHash -Algorithm SHA256 "dist\AgendaRelay-Windows-x64.zip"
