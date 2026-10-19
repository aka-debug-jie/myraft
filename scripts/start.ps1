param([int]$Nodes=11, [string]$Config='', [string]$RunDir='')
$ErrorActionPreference='Stop'
$project=Split-Path $PSScriptRoot -Parent
if ($Config) { $Config=(Resolve-Path $Config).Path }
if ($RunDir) { $RunDir=[IO.Path]::GetFullPath($RunDir) }
Set-Location $project
if (-not $RunDir) { $RunDir=Join-Path $project ('demo-runs\'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')) }
New-Item -ItemType Directory -Force $RunDir | Out-Null
& go build -o raft-node.exe .
if ($LASTEXITCODE -ne 0) { throw 'Build failed. Close old nodes and check that Go is on PATH.' }
if (-not $Config) {
    $Config=Join-Path $RunDir 'nodes.json'
    & .\raft-node.exe -generate-config $Config -nodes $Nodes -port 8001
    if ($LASTEXITCODE -ne 0) { throw 'Invalid node configuration.' }
}
& .\raft-node.exe -config $Config -check-config
if ($LASTEXITCODE -ne 0) { throw 'Configuration validation failed.' }
$members=(Get-Content $Config -Raw | ConvertFrom-Json).nodes
$listeners=@()
try {
    foreach ($node in $members) {
        $uri=[Uri]('tcp://'+$node.addr)
        $ip=[Net.Dns]::GetHostAddresses($uri.DnsSafeHost) | Where-Object AddressFamily -eq InterNetwork | Select-Object -First 1
        if (-not $ip) { $ip=[Net.IPAddress]::Parse($uri.DnsSafeHost) }
        $listener=[Net.Sockets.TcpListener]::new($ip,$uri.Port)
        $listener.Server.ExclusiveAddressUse=$true
        $listener.Start()
        $listeners += $listener
    }
} finally { foreach ($listener in $listeners) { $listener.Stop() } }
$started=@()
try {
    foreach ($node in $members) {
        $arguments="-id $($node.id) -config `"$Config`" -data-dir `"$RunDir\data`" -log-dir `"$RunDir\logs`""
        $started += Start-Process -FilePath "$project\raft-node.exe" -ArgumentList $arguments -PassThru
    }
} catch {
    foreach ($process in $started) { $process | Stop-Process -Force -ErrorAction SilentlyContinue }
    throw
}
$started.Id | ConvertTo-Json | Set-Content "$RunDir\pids.json"
Write-Host "Started $($members.Count) nodes. Keep a majority alive for failover."
Write-Host "Configuration: $Config"
Write-Host "Data and logs: $RunDir"
Write-Host ".\raft-node.exe -config `"$Config`" -demo 2101 -seed 42"
Write-Host ".\raft-node.exe -config `"$Config`" -verify"
Write-Host 'Restart a closed node with the same ID, configuration and data directory.'
