Set-StrictMode -Version Latest

function Test-AgendaRelayProcessIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Process,
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][ValidateSet('web', 'worker')][string]$Role
    )

    if (-not $Process.ExecutablePath -or -not $Process.CommandLine) { return $false }
    try {
        $expectedExecutable = if ($Role -eq 'web') {
            Join-Path $Root '.venv\Scripts\waitress-serve.exe'
        } else {
            Join-Path $Root '.venv\Scripts\python.exe'
        }
        $expectedExecutable = [IO.Path]::GetFullPath($expectedExecutable)
        $actualExecutable = [IO.Path]::GetFullPath([string]$Process.ExecutablePath)
    } catch {
        return $false
    }
    if (-not [string]::Equals($expectedExecutable, $actualExecutable, [StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }

    $commandLine = [string]$Process.CommandLine
    if ($Role -eq 'web') {
        return $commandLine -match '(?i)(?:^|\s)--call(?:\s|$)' `
            -and $commandLine -match '(?i)(?:^|\s)--listen(?:\s|$)' `
            -and $commandLine -match '(?i)(?:^|\s)scheduler\.app:create_app(?:\s|$)'
    }
    return $commandLine -match '(?i)(?:^|\s)-m\s+scheduler\.cli\s+worker(?:\s|$)'
}

function Get-AgendaRelayProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateRange(1, 2147483647)][int]$ProcessId,
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][ValidateSet('web', 'worker')][string]$Role
    )

    $process = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    if (Test-AgendaRelayProcessIdentity -Process $process -Root $Root -Role $Role) { return $process }
    return $null
}

function Get-AgendaRelayRuntimeAction {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][bool]$WebOwned,
        [Parameter(Mandatory)][bool]$WorkerOwned,
        [Parameter(Mandatory)][bool]$HealthOk
    )

    if (-not $WebOwned) { return 'start' }
    if (-not $HealthOk) { return 'unhealthy' }
    if (-not $WorkerOwned) { return 'restart-worker' }
    return 'already-running'
}

function Test-AgendaRelayNgrokProcessIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Process,
        [Parameter(Mandatory)][object]$Runtime,
        [Parameter(Mandatory)][string]$Root
    )

    if (-not $Process.ExecutablePath -or -not $Process.CommandLine) { return $false }
    foreach ($property in @('executablePath', 'configPath', 'agentConfigPath', 'domain', 'port')) {
        if (-not $Runtime.PSObject.Properties[$property] -or -not $Runtime.$property) { return $false }
    }

    try {
        $expectedExecutable = [IO.Path]::GetFullPath([string]$Runtime.executablePath)
        $actualExecutable = [IO.Path]::GetFullPath([string]$Process.ExecutablePath)
        $expectedAgentConfig = [IO.Path]::GetFullPath((Join-Path $Root 'data\runtime\ngrok-agent.yml'))
        $actualAgentConfig = [IO.Path]::GetFullPath([string]$Runtime.agentConfigPath)
        $configPath = [IO.Path]::GetFullPath([string]$Runtime.configPath)
        $port = 0
        if (-not [int]::TryParse([string]$Runtime.port, [ref]$port) -or $port -lt 1 -or $port -gt 65535) { return $false }
        if (-not [string]::Equals($expectedExecutable, $actualExecutable, [StringComparison]::OrdinalIgnoreCase)) { return $false }
        if (-not [string]::Equals($expectedAgentConfig, $actualAgentConfig, [StringComparison]::OrdinalIgnoreCase)) { return $false }

        $requiredArguments = @(
            'http',
            "--config=$configPath",
            "--config=$actualAgentConfig",
            "--url=$([string]$Runtime.domain)",
            "http://127.0.0.1:$port"
        )
        $commandLine = [string]$Process.CommandLine
        foreach ($argument in $requiredArguments) {
            $escaped = [regex]::Escape($argument)
            $pattern = '(?i)(?:^|\s)(?:"' + $escaped + '"|' + $escaped + ')(?=\s|$)'
            if (-not [regex]::IsMatch($commandLine, $pattern)) { return $false }
        }
        return $true
    } catch {
        return $false
    }
}

Export-ModuleMember -Function Test-AgendaRelayProcessIdentity, Get-AgendaRelayProcess, Get-AgendaRelayRuntimeAction, Test-AgendaRelayNgrokProcessIdentity
