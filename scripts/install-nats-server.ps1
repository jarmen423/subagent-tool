$ErrorActionPreference = "Stop"

$Version = "2.10.24"
$Root = Join-Path $env:USERPROFILE ".cursor\subagents\bin"
New-Item -ItemType Directory -Force -Path $Root | Out-Null

$Zip = Join-Path $env:TEMP "nats-server.zip"
$Url = "https://github.com/nats-io/nats-server/releases/download/v$Version/nats-server-v$Version-windows-amd64.zip"

Write-Host "Downloading nats-server v$Version..."
Invoke-WebRequest -Uri $Url -OutFile $Zip

Expand-Archive -Path $Zip -DestinationPath $env:TEMP -Force
$Extracted = Get-ChildItem -Path $env:TEMP -Filter "nats-server-v$Version-windows-amd64" -Directory | Select-Object -First 1
Copy-Item -Force (Join-Path $Extracted.FullName "nats-server.exe") (Join-Path $Root "nats-server.exe")

Write-Host "Installed to $(Join-Path $Root 'nats-server.exe')"
