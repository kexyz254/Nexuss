param(
    [Parameter(Mandatory=$true)][string]$IdentityFile,
    [string]$ServerAddress = "167.233.158.160",
    [string]$SshUser = "root",
    [switch]$Disable
)
$ErrorActionPreference = "Stop"
Get-Command ssh -ErrorAction Stop | Out-Null
$address = [System.Net.IPAddress]::Parse($ServerAddress)
if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw "An IPv4 server address is required."
}
if ($SshUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw "Invalid SSH user" }
if (!(Test-Path -LiteralPath $IdentityFile -PathType Leaf)) {
    throw "Provide an existing SSH identity file. No password or private key is copied into Nexuss settings."
}
$directory = Join-Path $env:LOCALAPPDATA "Nexuss\bridge"
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$settings = @{
    enabled = -not [bool]$Disable
    host = $address.ToString()
    user = $SshUser
    identity_file = (Resolve-Path -LiteralPath $IdentityFile).Path
} | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $directory "tunnel.json"), $settings,
    (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Managed transport settings saved. Restart Nexuss to apply."
Write-Host "SSH key authentication and a previously verified server host key are required. Password prompts are disabled in the background worker."
Write-Host "Keep the bridge URL set to http://127.0.0.1:8300."
