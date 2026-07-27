# Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.
# Stop only process trees recorded by the P5 startup script.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repository = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..")
).TrimEnd("\")
$RuntimeFile = Join-Path $Repository ".nexuss-runtime\p5-processes.json"

if (-not (Test-Path -LiteralPath $RuntimeFile -PathType Leaf)) {
    Write-Host "No recorded Nexuss P5 runtime was found."
    exit 0
}

$Runtime = Get-Content -LiteralPath $RuntimeFile -Raw | ConvertFrom-Json
$ProcessIds = @($Runtime.node_process_id, $Runtime.core_process_id) |
    Where-Object { $_ -is [int] -or $_ -is [long] } |
    Select-Object -Unique

foreach ($ProcessId in $ProcessIds) {
    Write-Host "Stopping Nexuss process tree rooted at PID $ProcessId"
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

Remove-Item -LiteralPath $RuntimeFile -Force
Write-Host "Nexuss P5 stopped."
