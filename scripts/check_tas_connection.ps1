# Read-only diagnostics. Never print connection files or credential contents.
$ErrorActionPreference = "Stop"
$directory = Join-Path $env:LOCALAPPDATA "Nexuss\bridge"
$descriptor = Join-Path $directory "connection.json"
$settings = @{}
if (Test-Path -LiteralPath $descriptor -PathType Leaf) {
    $settings = Get-Content -LiteralPath $descriptor -Raw | ConvertFrom-Json
}
$bridgeUrl = $env:NEXUSS_TAS_BRIDGE_URL
if ([string]::IsNullOrWhiteSpace($bridgeUrl)) { $bridgeUrl = $settings.url }
$keyFile = $env:NEXUSS_TAS_SECRET_FILE
if ([string]::IsNullOrWhiteSpace($keyFile)) { $keyFile = $settings.secret_file }
$origin = $null
$valid = [Uri]::TryCreate([string]$bridgeUrl, [UriKind]::Absolute, [ref]$origin)
if (!$valid -or $origin.UserInfo -or $origin.Scheme -notin @("http", "https")) {
    Write-Output "Bridge configuration is missing or invalid. No credentials were displayed."
    return
}
$keyPresent = $false
if (![string]::IsNullOrWhiteSpace($keyFile)) {
    $keyPresent = Test-Path -LiteralPath $keyFile -PathType Leaf
}
$reachable = Test-NetConnection -ComputerName $origin.DnsSafeHost -Port $origin.Port `
    -InformationLevel Quiet -WarningAction SilentlyContinue
$publicKeys = @(Get-ChildItem -LiteralPath (Join-Path $HOME ".ssh") -Filter "*.pub" `
    -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
[PSCustomObject]@{
    SettingsScope = "This terminal's environment overrides, otherwise saved connection.json"
    BridgeHost = $origin.DnsSafeHost
    BridgePort = $origin.Port
    TcpReachable = [bool]$reachable
    BridgeKeyFilePresent = [bool]$keyPresent
    ManagedTunnelSettingsPresent = (Test-Path -LiteralPath (Join-Path $directory "tunnel.json"))
    SshClientAvailable = [bool](Get-Command ssh -ErrorAction SilentlyContinue)
    PublicKeyFileNames = ($publicKeys -join ", ")
    Note = "TCP reachability does not verify bridge authentication or TAS health."
} | Format-List
