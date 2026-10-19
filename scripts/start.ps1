param([int]$Nodes=11, [string]$Config='', [string]$RunDir='')
$ErrorActionPreference='Stop'
$nodesWasSpecified=$PSBoundParameters.ContainsKey('Nodes')
$project=Split-Path $PSScriptRoot -Parent
if ($Config) { $Config=(Resolve-Path $Config).Path }
if ($RunDir) { $RunDir=[IO.Path]::GetFullPath($RunDir) }
Set-Location $project
if (-not $RunDir) { $RunDir=Join-Path $project ('demo-runs\'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')) }
New-Item -ItemType Directory -Force $RunDir | Out-Null
$persistedConfig=Join-Path $RunDir 'nodes.json'
$configExists=Test-Path $persistedConfig
$runHasContent=@(Get-ChildItem -Force $RunDir | Where-Object FullName -ne $persistedConfig).Count -gt 0

function Get-Members([string]$Path) {
    return @((Get-Content $Path -Raw | ConvertFrom-Json).nodes)
}
function Get-MemberSignature([object[]]$Members) {
    return (($Members | Sort-Object { [int]$_.id } | ForEach-Object { '{0}|{1}' -f ([int]$_.id),([string]$_.addr) }) -join "`n")
}

& go build -o raft-node.exe .
if ($LASTEXITCODE -ne 0) { throw 'Build failed. Close old nodes and check that Go is on PATH.' }

if ($configExists) {
    & .\raft-node.exe -config $persistedConfig -check-config
    if ($LASTEXITCODE -ne 0) { throw 'Persisted configuration validation failed.' }
    $members=Get-Members $persistedConfig
    if ($nodesWasSpecified -and $Nodes -ne $members.Count) { throw "-Nodes $Nodes conflicts with the $($members.Count) persisted members; use a new RunDir. nodes.json was not changed." }
    if ($Config) {
        & .\raft-node.exe -config $Config -check-config
        if ($LASTEXITCODE -ne 0) { throw 'Supplied configuration validation failed.' }
        if ((Get-MemberSignature (Get-Members $Config)) -ne (Get-MemberSignature $members)) {
            throw "Supplied configuration conflicts with RunDir nodes.json; use a new RunDir. The persisted configuration was not changed."
        }
    }
    $Config=$persistedConfig
} else {
    if ($runHasContent) { throw "RunDir contains existing files or data but has no nodes.json; refusing to guess its fixed members: $RunDir" }
    if ($Config) {
        & .\raft-node.exe -config $Config -check-config
        if ($LASTEXITCODE -ne 0) { throw 'Configuration validation failed.' }
        if ($nodesWasSpecified -and $Nodes -ne (Get-Members $Config).Count) { throw '-Nodes conflicts with supplied configuration; use a new directory with matching members.' }
        Copy-Item -LiteralPath $Config -Destination $persistedConfig
    } else {
        & .\raft-node.exe -generate-config $persistedConfig -nodes $Nodes -port 8001
        if ($LASTEXITCODE -ne 0) { throw 'Invalid node configuration.' }
    }
    $Config=$persistedConfig
    & .\raft-node.exe -config $Config -check-config
    if ($LASTEXITCODE -ne 0) { throw 'Configuration validation failed.' }
    $members=Get-Members $Config
}

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
$ready=$false
$lastStatus='No status received'
try {
    foreach ($node in $members) {
        $arguments="-id $($node.id) -config `"$Config`" -data-dir `"$RunDir\data`" -log-dir `"$RunDir\logs`""
        $started += Start-Process -FilePath "$project\raft-node.exe" -ArgumentList $arguments -PassThru
    }
    $started.Id | ConvertTo-Json | Set-Content "$RunDir\pids.json"
    $expected=(@($members | ForEach-Object { [int]$_.id } | Sort-Object) -join ',')
    $deadline=[DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (@($started | Where-Object HasExited).Count -gt 0) { throw 'A node exited during startup; inspect node logs.' }
        $raw=& .\raft-node.exe -config $Config -status-all -timeout 2s
        if ($LASTEXITCODE -ne 0) { throw 'Status client failed during startup.' }
        $lastStatus=$raw -join "`n"
        $statuses=ConvertFrom-Json -InputObject $lastStatus
        $ids=@(foreach ($status in $statuses) { [int]$status.id })
        $hasErrors=$false
        foreach ($status in $statuses) { if ($status.error) { $hasErrors=$true } }
        if (-not $hasErrors -and $ids.Count -eq $members.Count -and
            @($ids | Select-Object -Unique).Count -eq $members.Count -and
            (($ids | Sort-Object) -join ',') -eq $expected -and
            @($started | Where-Object HasExited).Count -eq 0 -and [DateTime]::UtcNow -lt $deadline) {
            $ready=$true
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $ready) { throw 'Nodes did not report healthy Status within 15 seconds.' }
} finally {
    # Keep diagnostics even when startup fails; only this invocation's handles are stopped.
    try { $lastStatus | Set-Content "$RunDir\startup-status.json" } catch { Write-Warning $_ }
    if (-not $ready) {
        $cleanupErrors=@()
        foreach ($process in $started) {
            try {
                if (-not $process.HasExited) { $process.Kill() }
                if (-not $process.WaitForExit(5000)) { throw "Process $($process.Id) did not exit." }
            } catch { $cleanupErrors += $_.ToString() }
        }
        if ($cleanupErrors.Count) { Write-Warning ($cleanupErrors -join '; ') }
    }
}

Write-Host "Started and checked $($members.Count) nodes. Keep a majority alive for failover."
Write-Host "Configuration: $Config"
Write-Host "Data and logs: $RunDir"
Write-Host ".\raft-node.exe -config `"$Config`" -demo 2101 -seed 42"
Write-Host ".\raft-node.exe -config `"$Config`" -verify"
Write-Host 'Restart a closed node with the same ID, configuration and data directory.'
