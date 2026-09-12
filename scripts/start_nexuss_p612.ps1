# Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.
# P6.12 SECURE RUNTIME BOOTSTRAP
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [string]$ExistingLauncher = (
        Join-Path $env:USERPROFILE (
            "Downloads\nexuss_youtube_configuration_recovery_v2\" +
            "start_nexuss_with_youtube_v2.ps1"
        )
    ),

    [string]$PythonPath = "",

    [ValidateRange(1, 65535)]
    [int]$CorePort = 8100,

    [ValidateRange(1, 65535)]
    [int]$NodePort = 8101,

    [string]$RegionCode = "KE",

    [string]$Language = "en"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-LoopbackPort {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(250)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function New-ProcessLocalSecret {
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
        $base64 = [Convert]::ToBase64String($bytes)
        return $base64.TrimEnd("=").Replace("+", "-").Replace("/", "_")
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $rng.Dispose()
    }
}

$repositoryPath = (Resolve-Path -LiteralPath $Repository).Path
if (-not (Test-Path -LiteralPath $ExistingLauncher -PathType Leaf)) {
    throw "STOP: validated YouTube launcher not found: $ExistingLauncher"
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    if ($env:VIRTUAL_ENV) {
        $candidate = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $PythonPath = $candidate
        }
    }
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $resolvedPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $resolvedPython) {
        $resolvedPython = Get-Command python -ErrorAction SilentlyContinue
    }
    if (-not $resolvedPython) {
        throw "STOP: Python executable not found."
    }
    $PythonPath = $resolvedPython.Source
}

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "STOP: Python executable not found: $PythonPath"
}

if (Test-LoopbackPort -Port $CorePort) {
    throw "STOP: Core port $CorePort is already listening."
}
if (Test-LoopbackPort -Port $NodePort) {
    throw "STOP: trusted node port $NodePort is already listening."
}

$nodeProcess = $null
$deviceSecret = $null
$previousNodeUrl = $env:NEXUSS_DEVICE_NODE_URL
$previousNodeSecret = $env:NEXUSS_DEVICE_NODE_SECRET
$previousNodeId = $env:NEXUSS_WINDOWS_NODE_ID
$previousCoreMode = $env:NEXUSS_CORE_MODE
$previousDeveloperSelfBuild = $env:NEXUSS_DEVELOPER_SELF_BUILD
$previousDeveloperSelfBuildApply = $env:NEXUSS_DEVELOPER_SELF_BUILD_APPLY

try {
    Set-Location -LiteralPath $repositoryPath

    $deviceSecret = New-ProcessLocalSecret
    $env:NEXUSS_DEVICE_NODE_SECRET = $deviceSecret
    $env:NEXUSS_DEVICE_NODE_URL = "http://127.0.0.1:$NodePort"
    $env:NEXUSS_WINDOWS_NODE_ID = "windows-primary"
    $env:NEXUSS_CORE_MODE = "p612_runtime_reliability"
# Early-development Prompt-to-Build mode. The engineering service remains isolated,
# baseline-aware, backup-protected, secret-denied, and never stages or publishes Git.
$env:NEXUSS_DEVELOPER_SELF_BUILD = "1"
$env:NEXUSS_DEVELOPER_SELF_BUILD_APPLY = "1"

    Write-Host ""
    Write-Host "Nexuss P6.12 runtime bootstrap"
    Write-Host "Trusted Windows node: loopback only"
    Write-Host "Device secret written to disk: false"
    Write-Host "Device secret printed or logged: false"
    Write-Host "Android developer mode required: false"
    Write-Host ""

    $nodeArguments = @(
        "-m",
        "uvicorn",
        "nexuss.device_node.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        [string]$NodePort
    )

    $nodeProcess = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList $nodeArguments `
        -WorkingDirectory $repositoryPath `
        -WindowStyle Hidden `
        -PassThru

    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($nodeProcess.HasExited) {
            throw (
                "STOP: trusted Windows node exited before becoming ready. " +
                "Exit code: $($nodeProcess.ExitCode)"
            )
        }
        if (Test-LoopbackPort -Port $NodePort) {
            break
        }
        Start-Sleep -Milliseconds 250
    }

    if (-not (Test-LoopbackPort -Port $NodePort)) {
        throw "STOP: trusted Windows node did not become reachable on loopback."
    }

    try {
        $nodeHealth = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$NodePort/health/ready" `
            -TimeoutSec 5 `
            -ErrorAction Stop
    }
    catch {
        throw "STOP: trusted Windows node health check failed. $($_.Exception.Message)"
    }

    if (
        $nodeHealth.status -ne "ready" -or
        $nodeHealth.mode -ne "p5_trusted_windows_node" -or
        $nodeHealth.node_id -ne "windows-primary"
    ) {
        throw (
            "STOP: trusted Windows node health contract mismatch. " +
            "Expected ready | p5_trusted_windows_node | windows-primary."
        )
    }

    Write-Host (
        "PASS: trusted Windows node verified: " +
        "$($nodeHealth.node_id) | $($nodeHealth.mode)"
    )
    Write-Host "Starting the previously validated YouTube/Core launcher..."
    Write-Host ""

    & $ExistingLauncher `
        -Repository $repositoryPath `
        -RegionCode $RegionCode `
        -Language $Language
}
finally {
    if ($nodeProcess -and -not $nodeProcess.HasExited) {
        Stop-Process -Id $nodeProcess.Id -Force -ErrorAction SilentlyContinue
        try {
            $nodeProcess.WaitForExit(5000)
        }
        catch {
            # Best effort cleanup only.
        }
    }

    if ($null -eq $previousNodeUrl) {
        Remove-Item Env:NEXUSS_DEVICE_NODE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:NEXUSS_DEVICE_NODE_URL = $previousNodeUrl
    }

    if ($null -eq $previousNodeSecret) {
        Remove-Item Env:NEXUSS_DEVICE_NODE_SECRET -ErrorAction SilentlyContinue
    }
    else {
        $env:NEXUSS_DEVICE_NODE_SECRET = $previousNodeSecret
    }

    if ($null -eq $previousNodeId) {
        Remove-Item Env:NEXUSS_WINDOWS_NODE_ID -ErrorAction SilentlyContinue
    }
    else {
        $env:NEXUSS_WINDOWS_NODE_ID = $previousNodeId
    }

    if ($null -eq $previousCoreMode) {
        Remove-Item Env:NEXUSS_CORE_MODE -ErrorAction SilentlyContinue
    }
    else {
        $env:NEXUSS_CORE_MODE = $previousCoreMode
    }

    if ($null -eq $previousDeveloperSelfBuild) {
        Remove-Item Env:NEXUSS_DEVELOPER_SELF_BUILD -ErrorAction SilentlyContinue
    }
    else {
        $env:NEXUSS_DEVELOPER_SELF_BUILD = $previousDeveloperSelfBuild
    }

    if ($null -eq $previousDeveloperSelfBuildApply) {
        Remove-Item Env:NEXUSS_DEVELOPER_SELF_BUILD_APPLY -ErrorAction SilentlyContinue
    }
    else {
        $env:NEXUSS_DEVELOPER_SELF_BUILD_APPLY = $previousDeveloperSelfBuildApply
    }

    $deviceSecret = $null
    Write-Host ""
    Write-Host "Trusted Windows node stopped."
    Write-Host "P6.12 device secret removed from this PowerShell environment."
}
