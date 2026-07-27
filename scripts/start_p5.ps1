# Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.
# Start the P5 knowledge/media core, phone client, and loopback-only Windows node.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repository = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..")
).TrimEnd("\")
$RuntimeDirectory = Join-Path $Repository ".nexuss-runtime"
$RuntimeFile = Join-Path $RuntimeDirectory "p5-processes.json"

Set-Location $Repository

$PythonCommand = Get-Command python -ErrorAction Stop
$PythonExecutable = $PythonCommand.Source
$PythonVersion = & $PythonExecutable -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"

if ($LASTEXITCODE -ne 0 -or -not $PythonVersion.StartsWith("3.12.")) {
    throw (
        "STOP: P5 requires the approved Python 3.12 virtual environment. " +
        "Found $PythonVersion at $PythonExecutable."
    )
}

if ((git branch --show-current).Trim() -ne "feature/p5-knowledge-media-mobile") {
    Write-Warning (
        "P5 normally runs from feature/p5-knowledge-media-mobile " +
        "during development."
    )
}

$OccupiedPorts = @(
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in @(8100, 8200) }
)

if ($OccupiedPorts.Count -gt 0) {
    $OccupiedPorts |
        Select-Object LocalAddress, LocalPort, OwningProcess |
        Format-Table -AutoSize
    throw (
        "STOP: Port 8100 or 8200 is already in use. " +
        "Run scripts\stop_p5.ps1 first."
    )
}

$PrivateProfiles = @(
    Get-NetConnectionProfile -ErrorAction SilentlyContinue |
        Where-Object { $_.NetworkCategory -eq "Private" }
)

if ($PrivateProfiles.Count -eq 0) {
    throw "STOP: No active Private Windows network profile was found."
}

$LanAddress = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        (
            $_.IPAddress -like "10.*" -or
            $_.IPAddress -like "192.168.*" -or
            $_.IPAddress -match '^172\.(1[6-9]|2[0-9]|3[0-1])\.'
        )
    } |
    Sort-Object InterfaceMetric |
    Select-Object -First 1 -ExpandProperty IPAddress

if (-not $LanAddress) {
    throw "STOP: A private-LAN IPv4 address could not be resolved."
}

$SecretBytes = New-Object byte[] 48
$RandomGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()

try {
    $RandomGenerator.GetBytes($SecretBytes)
}
finally {
    $RandomGenerator.Dispose()
}

$DeviceSecret = [Convert]::ToBase64String($SecretBytes)
$MobileUrl = "http://${LanAddress}:8100/mobile"
$EscapedRepository = $Repository.Replace("'", "''")
$EscapedPython = $PythonExecutable.Replace("'", "''")

$NodeCommand = @"
Set-Location '$EscapedRepository'
`$env:PYTHONPATH = '$EscapedRepository\src'
`$env:PYTHONDONTWRITEBYTECODE = '1'
& '$EscapedPython' -m uvicorn nexuss.device_node.app:app --host 127.0.0.1 --port 8200
"@

$CoreCommand = @"
Set-Location '$EscapedRepository'
`$env:PYTHONPATH = '$EscapedRepository\src'
`$env:PYTHONDONTWRITEBYTECODE = '1'
& '$EscapedPython' -m uvicorn nexuss.api.app:app --host 0.0.0.0 --port 8100
"@

$PreviousSecret = $env:NEXUSS_DEVICE_NODE_SECRET
$PreviousNodeUrl = $env:NEXUSS_DEVICE_NODE_URL
$PreviousNodeId = $env:NEXUSS_WINDOWS_NODE_ID
$PreviousMobileUrl = $env:NEXUSS_MOBILE_PUBLIC_URL
$PreviousYouTubeApiKey = $env:NEXUSS_YOUTUBE_API_KEY
$PreviousDeviceStore = $env:NEXUSS_MOBILE_DEVICE_STORE

# Paired phones survive restarts from here. The runtime directory is already
# excluded from version control, so no device record reaches a commit.
$DeviceStorePath = Join-Path $RuntimeDirectory "paired-devices.db"
New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null

try {
    # Child processes inherit these values without exposing secrets in arguments.
    $env:NEXUSS_DEVICE_NODE_SECRET = $DeviceSecret
    $env:NEXUSS_DEVICE_NODE_URL = "http://127.0.0.1:8200"
    $env:NEXUSS_WINDOWS_NODE_ID = "windows-primary"
    $env:NEXUSS_MOBILE_PUBLIC_URL = $MobileUrl
    $env:NEXUSS_MOBILE_DEVICE_STORE = $DeviceStorePath

    # The trusted Windows node never receives external-provider credentials.
    Remove-Item Env:\NEXUSS_YOUTUBE_API_KEY -ErrorAction SilentlyContinue

    $NodeProcess = Start-Process powershell.exe -PassThru -ArgumentList @(
        "-NoExit",
        "-Command",
        $NodeCommand
    )

    Start-Sleep -Seconds 2

    if (-not [string]::IsNullOrWhiteSpace($PreviousYouTubeApiKey)) {
        $env:NEXUSS_YOUTUBE_API_KEY = $PreviousYouTubeApiKey
    }

    $CoreProcess = Start-Process powershell.exe -PassThru -ArgumentList @(
        "-NoExit",
        "-Command",
        $CoreCommand
    )
}
finally {
    $env:NEXUSS_DEVICE_NODE_SECRET = $PreviousSecret
    $env:NEXUSS_DEVICE_NODE_URL = $PreviousNodeUrl
    $env:NEXUSS_WINDOWS_NODE_ID = $PreviousNodeId
    $env:NEXUSS_MOBILE_PUBLIC_URL = $PreviousMobileUrl
    $env:NEXUSS_MOBILE_DEVICE_STORE = $PreviousDeviceStore

    if ([string]::IsNullOrWhiteSpace($PreviousYouTubeApiKey)) {
        Remove-Item Env:\NEXUSS_YOUTUBE_API_KEY -ErrorAction SilentlyContinue
    }
    else {
        $env:NEXUSS_YOUTUBE_API_KEY = $PreviousYouTubeApiKey
    }
}

# Poll until both services answer. A fixed sleep is a race: uvicorn needs
# longer than a few seconds to import FastAPI, pydantic, httpx and the media
# and knowledge modules on a cold virtual environment, and losing that race
# previously killed both services before they had finished starting.
$HealthDeadline = (Get-Date).AddSeconds(60)
$NodeHealth = $null
$CoreHealth = $null
$LastHealthError = "no probe was attempted"

while ((Get-Date) -lt $HealthDeadline) {
    Start-Sleep -Seconds 1

    foreach ($Child in @($NodeProcess, $CoreProcess)) {
        if ($Child.HasExited) {
            throw (
                "STOP: A P5 service exited during startup (PID $($Child.Id), " +
                "exit code $($Child.ExitCode)). Its PowerShell window was " +
                "started with -NoExit and holds the traceback."
            )
        }
    }

    try {
        $NodeHealth = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8200/health/ready" `
            -TimeoutSec 5
        $CoreHealth = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8100/health/ready" `
            -TimeoutSec 5
        break
    }
    catch {
        $LastHealthError = $_.Exception.Message
        $NodeHealth = $null
        $CoreHealth = $null
    }
}

if ($null -eq $NodeHealth -or $null -eq $CoreHealth) {
    foreach ($ProcessId in @($NodeProcess.Id, $CoreProcess.Id)) {
        & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    }
    throw (
        "P5 startup health verification failed after 60s. " +
        "Last error: $LastHealthError"
    )
}

if (
    $NodeHealth.status -ne "ready" -or
    $NodeHealth.mode -ne "p5_trusted_windows_node" -or
    $NodeHealth.node_id -ne "windows-primary"
) {
    foreach ($ProcessId in @($NodeProcess.Id, $CoreProcess.Id)) {
        & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    }
    throw "P5 trusted Windows node health contract was not satisfied."
}

if (
    $CoreHealth.status -ne "ready" -or
    $CoreHealth.mode -ne "p5_knowledge_media_mobile"
) {
    foreach ($ProcessId in @($NodeProcess.Id, $CoreProcess.Id)) {
        & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    }
    throw "P5 Core health contract was not satisfied."
}

New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null
@{
    node_process_id = $NodeProcess.Id
    core_process_id = $CoreProcess.Id
    desktop_url = "http://127.0.0.1:8100/"
    mobile_url = $MobileUrl
    started_at = [DateTimeOffset]::UtcNow.ToString("o")
    python_executable = $PythonExecutable
    youtube_configured = -not [string]::IsNullOrWhiteSpace(
        $PreviousYouTubeApiKey
    )
} | ConvertTo-Json | Set-Content -LiteralPath $RuntimeFile -Encoding utf8

Write-Host ""
Write-Host "Nexuss P5 is ready." -ForegroundColor Green
Write-Host "Desktop: http://127.0.0.1:8100/"
Write-Host "Phone:   $MobileUrl"
Write-Host "Node:    $($NodeHealth.node_id) | $($NodeHealth.mode)"
Write-Host "Core:    $($CoreHealth.mode)"
Write-Host "Python:  $PythonExecutable"
Write-Host (
    "YouTube: " +
    $(if ([string]::IsNullOrWhiteSpace($PreviousYouTubeApiKey)) {
        "not configured"
    }
    else {
        "configured"
    })
)
Write-Host ""
Write-Warning (
    "Private-LAN prototype only. Never port-forward or publicly expose " +
    "port 8100."
)
Write-Host "If Windows Firewall prompts, allow access only on Private networks."
