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

    if (-not $Process.ExecutablePath -or -not $Process.CommandLine) {
        Write-Verbose 'Ngrok process metadata is incomplete.'
        return $false
    }
    foreach ($property in @('executablePath', 'configPath', 'agentConfigPath', 'domain', 'port')) {
        if (-not $Runtime.PSObject.Properties[$property] -or -not $Runtime.$property) {
            Write-Verbose "Ngrok runtime state is missing $property."
            return $false
        }
    }

    try {
        $expectedExecutable = [IO.Path]::GetFullPath([string]$Runtime.executablePath)
        $actualExecutable = [IO.Path]::GetFullPath([string]$Process.ExecutablePath)
        $expectedAgentConfig = [IO.Path]::GetFullPath((Join-Path $Root 'data\runtime\ngrok-agent.yml'))
        $actualAgentConfig = [IO.Path]::GetFullPath([string]$Runtime.agentConfigPath)
        $configPath = [IO.Path]::GetFullPath([string]$Runtime.configPath)
        $port = 0
        if (-not [int]::TryParse([string]$Runtime.port, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
            Write-Verbose 'Ngrok runtime state contains an invalid local port.'
            return $false
        }
        if (-not [string]::Equals($expectedExecutable, $actualExecutable, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Verbose 'Ngrok process executable does not match the recorded path.'
            return $false
        }
        if (-not [string]::Equals($expectedAgentConfig, $actualAgentConfig, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Verbose 'Ngrok agent config is not the Agenda Relay isolated config.'
            return $false
        }

        $requiredArguments = @(
            'http',
            "--config=$configPath",
            "--config=$actualAgentConfig",
            "--url=$([string]$Runtime.domain)",
            "http://127.0.0.1:$port"
        )
        $commandLine = [string]$Process.CommandLine
        for ($index = 0; $index -lt $requiredArguments.Count; $index++) {
            $argument = $requiredArguments[$index]
            $escaped = [regex]::Escape($argument)
            $pattern = '(?i)(?:^|\s)(?:"' + $escaped + '"|' + $escaped + ')(?=\s|$)'
            if (-not [regex]::IsMatch($commandLine, $pattern)) {
                Write-Verbose "Ngrok process argument check $index failed."
                return $false
            }
        }
        return $true
    } catch {
        Write-Verbose "Ngrok process identity check failed: $($_.Exception.Message)"
        return $false
    }
}

Export-ModuleMember -Function Test-AgendaRelayProcessIdentity, Get-AgendaRelayProcess, Get-AgendaRelayRuntimeAction, Test-AgendaRelayNgrokProcessIdentity
