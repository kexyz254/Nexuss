param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$PreviousSha,

    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$TargetSha
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repository = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..")).TrimEnd("\")
$ResultFile = Join-Path $Repository ".nexuss-runtime\update-result.json"

function Write-Result {
    param([string]$Status, [string]$ActiveSha, [string]$Detail)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ResultFile) | Out-Null
    @{
        status = $Status
        previous_sha = $PreviousSha
        target_sha = $TargetSha
        active_sha = $ActiveSha
        detail = $Detail
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $ResultFile -Encoding utf8
}

Set-Location -LiteralPath $Repository
Start-Sleep -Seconds 2

try {
    & (Join-Path $PSScriptRoot "stop_p5.ps1")
}
catch {
    Write-Host "Existing runtime stop returned: $($_.Exception.Message)"
}

try {
    & (Join-Path $PSScriptRoot "start_p5.ps1")
    $ActiveSha = (git rev-parse HEAD).Trim()
    if ($ActiveSha -ne $TargetSha) {
        throw "Restarted repository SHA does not match approved target."
    }
    Write-Result -Status "completed" -ActiveSha $ActiveSha -Detail "Verified update restarted successfully."
    exit 0
}
catch {
    $ForwardError = $_.Exception.Message
}

Write-Warning ("Verified update failed health/startup checks. Rolling back to " + $PreviousSha)

try {
    git reset --hard $PreviousSha
    if ($LASTEXITCODE -ne 0) { throw "git reset failed." }
    & (Join-Path $PSScriptRoot "start_p5.ps1")
    $RolledBackSha = (git rev-parse HEAD).Trim()
    if ($RolledBackSha -ne $PreviousSha) { throw "Rollback SHA verification failed." }
    Write-Result -Status "rolled_back" -ActiveSha $RolledBackSha -Detail ("Target revision failed startup health checks and was rolled back. Forward error: " + $ForwardError)
    exit 1
}
catch {
    $RollbackError = $_.Exception.Message
    $ActiveSha = (git rev-parse HEAD).Trim()
    Write-Result -Status "recovery_failed" -ActiveSha $ActiveSha -Detail ("Update failed and automatic rollback could not restore service. Forward error: " + $ForwardError + "; rollback error: " + $RollbackError)
    exit 2
}
