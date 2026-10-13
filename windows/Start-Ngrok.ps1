[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Get-Command ngrok.exe -ErrorAction SilentlyContinue)) { throw "ngrok is not installed. Install it with: winget install Ngrok.Ngrok" }
Get-Content -LiteralPath ".env" | ForEach-Object { if ($_ -match '^\s*([^#][A-Za-z0-9_]*)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process") } }
if ($env:APP_ENV -ne "production") { throw "Public tunnelling requires APP_ENV=production." }
if (-not $env:NGROK_DOMAIN) { throw "Set NGROK_DOMAIN to an assigned ngrok domain." }
if (-not $env:PUBLIC_BASE_URL) { throw "Set PUBLIC_BASE_URL to the public HTTPS URL." }
if (-not $env:ADMIN_API_TOKEN) { throw "ADMIN_API_TOKEN is required to verify local production readiness." }
$expected = "https://$($env:NGROK_DOMAIN.Trim('/'))"
if ($env:PUBLIC_BASE_URL.TrimEnd('/') -ne $expected) { throw "PUBLIC_BASE_URL must exactly equal $expected so booking and OAuth links are correct." }
$port = if ($env:PORT) { [int]$env:PORT } else { 5000 }
$inspectorPort = if ($env:NGROK_INSPECTOR_PORT) { [int]$env:NGROK_INSPECTOR_PORT } else { 4042 }
$baseConfig = if ($env:NGROK_CONFIG_FILE) { $env:NGROK_CONFIG_FILE } else { Join-Path $env:LOCALAPPDATA "ngrok\ngrok.yml" }
if (-not (Test-Path -LiteralPath $baseConfig)) { throw "ngrok authentication configuration was not found. Run: ngrok config add-authtoken <token>" }
if (Get-NetTCPConnection -LocalPort $inspectorPort -State Listen -ErrorAction SilentlyContinue) { throw "NGROK_INSPECTOR_PORT $inspectorPort is already in use." }
try {
    $headers = @{ Authorization = "Bearer $($env:ADMIN_API_TOKEN)" }
    $readiness = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/operator/readiness" -Headers $headers -TimeoutSec 5
} catch { throw "Could not verify local operator readiness; public exposure was refused. Check that Agenda Relay is running and ADMIN_API_TOKEN matches its configuration." }
if (-not $readiness.public_ingress.ready) {
    $reasons = @($readiness.errors) -join "; "
    if (-not $reasons) { $reasons = $readiness.public_ingress.detail }
    throw "Production ingress prerequisites are not satisfied; public exposure was refused. $reasons"
}
$runtime = Join-Path $Root "data\runtime"; $logs = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $runtime,$logs | Out-Null
$agentConfig = Join-Path $runtime "ngrok-agent.yml"
@("version: 3", "agent:", "  web_addr: 127.0.0.1:$inspectorPort") | Set-Content -LiteralPath $agentConfig -Encoding ascii
$ngrokLog = Join-Path $logs "ngrok.log"
$ngrokError = Join-Path $logs "ngrok.err.log"
Set-Content -LiteralPath $ngrokLog -Value "" -NoNewline
Set-Content -LiteralPath $ngrokError -Value "" -NoNewline
$process = Start-Process -FilePath "ngrok.exe" -ArgumentList @('http',"--config=$baseConfig","--config=$agentConfig","--url=$($env:NGROK_DOMAIN)","http://127.0.0.1:$port",'--log=stdout','--log-format=json') -WorkingDirectory $Root -RedirectStandardOutput $ngrokLog -RedirectStandardError $ngrokError -WindowStyle Hidden -PassThru
try {
    $public = $null
    $startupTimer = [Diagnostics.Stopwatch]::StartNew()
    while ($startupTimer.Elapsed.TotalSeconds -lt 45) {
        $process.Refresh()
        if ($process.HasExited) { throw "ngrok exited before creating the configured endpoint. Review data\logs\ngrok.err.log." }
        if ((Get-Content -LiteralPath $ngrokError -Raw -ErrorAction SilentlyContinue) -match 'ERR_NGROK_\d+') { throw "ngrok rejected the endpoint. Review data\logs\ngrok.err.log." }
        try {
            $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:$inspectorPort/api/tunnels" -TimeoutSec 1
            $public = ($tunnels.tunnels | Where-Object {$_.proto -eq 'https'} | Select-Object -First 1).public_url
            if ($public) { break }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    if (-not $public) { throw "ngrok did not create an HTTPS tunnel." }
    if ($public.TrimEnd('/') -ne $expected) { throw "ngrok did not publish the configured domain." }
    $health = Invoke-RestMethod -Uri "$public/api/health" -TimeoutSec 10
    if (-not $health.ok) { throw "Public health verification failed." }
    if (-not $readiness.ready) {
        Write-Warning "The HTTPS ingress is verified, but scheduling readiness is not green. Complete Google OAuth if it is disconnected, run the real-provider acceptance checks, and keep automation paused until verified."
    }
    @{ pid=$process.Id; publicUrl=$public; startedAt=(Get-Date).ToUniversalTime().ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime "ngrok.json") -Encoding utf8
} catch {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw
}
Write-Host "Verified public URL: $public"
