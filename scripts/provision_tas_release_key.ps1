param(
    [string]$VpsHost = "167.233.158.160"
)

$ErrorActionPreference = "Stop"
$directory = Join-Path $env:LOCALAPPDATA "Nexuss\release"
$keyFile = Join-Path $directory "approval.key"
New-Item -ItemType Directory -Path $directory -Force | Out-Null
if (-not (Test-Path $keyFile)) {
    $bytes = [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    $hex = [Convert]::ToHexString($bytes).ToLowerInvariant()
    [System.IO.File]::WriteAllText($keyFile, $hex, [System.Text.Encoding]::ASCII)
    $bytes = $null
    $hex = $null
}
if ((Get-Item $keyFile).Length -lt 32) {
    throw "The local approval key is invalid. No key was sent."
}

$destination = "root@${VpsHost}:/root/nexuss-release-approval.key"
& scp $keyFile $destination
if ($LASTEXITCODE -ne 0) { throw "Secure copy failed. No release service was enabled." }
& ssh "root@$VpsHost" 'install -d -m 0700 /etc/nexuss-release && install -m 0600 /root/nexuss-release-approval.key /etc/nexuss-release/approval.key && rm -f /root/nexuss-release-approval.key'
if ($LASTEXITCODE -ne 0) { throw "Server key installation failed. No release service was enabled." }

Write-Host "Release approval key provisioned without displaying its value."
Write-Host "Local fingerprint: $((Get-FileHash -Algorithm SHA256 $keyFile).Hash)"
