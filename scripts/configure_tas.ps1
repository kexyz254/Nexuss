param(
    [string]$BridgeUrl = "http://127.0.0.1:8300",
    [string]$SecretFile = (Join-Path $env:LOCALAPPDATA "Nexuss\bridge\bridge.key")
)
$ErrorActionPreference = "Stop"
$uri = [Uri]$BridgeUrl
if ($uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne "/") {
    throw "Supply a bridge origin without credentials, a path, or query parameters."
}
$address = $null
$privateHttp = $false
if ([System.Net.IPAddress]::TryParse($uri.Host, [ref]$address)) {
    $bytes = $address.GetAddressBytes()
    $privateHttp = [System.Net.IPAddress]::IsLoopback($address) -or (
        $bytes.Length -eq 4 -and $bytes[0] -eq 100 -and $bytes[1] -ge 64 -and $bytes[1] -le 127
    )
}
if ($uri.Scheme -ne "https" -and -not ($uri.Scheme -eq "http" -and $privateHttp)) {
    throw "Use HTTPS, a loopback IP, or a private Tailscale IP."
}
if (!(Test-Path -LiteralPath $SecretFile -PathType Leaf)) {
    throw "The private bridge key file does not exist."
}
$resolvedKey = (Resolve-Path -LiteralPath $SecretFile).Path
$directory = Join-Path $env:LOCALAPPDATA "Nexuss\bridge"
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$settings = @{url=$BridgeUrl.TrimEnd('/'); secret_file=$resolvedKey} | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $directory "connection.json"), $settings,
    (New-Object System.Text.UTF8Encoding($false)))
$env:NEXUSS_TAS_BRIDGE_URL = $BridgeUrl.TrimEnd('/')
$env:NEXUSS_TAS_SECRET_FILE = $resolvedKey
Write-Host "TAS connection settings saved. The key was not displayed or copied."
Write-Host "Restart Nexuss, then type 'check TAS' in chat."
