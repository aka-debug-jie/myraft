param(
    [string]$RunDir='',
    [ValidateSet('menu','status','watch','generate','verify','stop','restart','stop-all')][string]$Action='menu',
    [int]$NodeID=0,
    [ValidateRange(1,100000)][int]$Count=2101,
    [long]$Seed=42
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'session.ps1')
if (-not $RunDir) { $RunDir=Read-Host 'Experiment directory' }
$RunDir=(Resolve-Path $RunDir).Path
$config=Join-Path $RunDir 'nodes.json'

function Invoke-DemoAction([string]$Operation,[int]$Id) {
    $session=Read-Session $RunDir
    $exe=$session.executable
    if ($Operation -eq 'status' -or $Operation -eq 'watch') {
        $arguments=@('-config',$config,'-status-all','-format','table')
        if ($Operation -eq 'watch') { $arguments+=@('-watch','1s') }
        & $exe @arguments
        if ($LASTEXITCODE -ne 0) { throw 'Status command failed.' }
    } elseif ($Operation -eq 'generate') {
        $raw=& $exe -config $config -demo $Count -seed $Seed -timeout 60s
        $code=$LASTEXITCODE
        $reply=$raw | ConvertFrom-Json
        if ($code -ne 0 -or -not $reply.accepted -or -not $reply.committed -or $reply.error) {
            throw 'Write was not confirmed. Its outcome may be unknown; inspect state before retrying. No automatic retry was performed.'
        }
        Write-Host "COMMITTED: $($reply.commands) commands, indices $($reply.first_index)..$($reply.last_index)."
    } elseif ($Operation -eq 'verify') {
        $raw=& $exe -config $config -verify
        $code=$LASTEXITCODE
        $reply=$raw | ConvertFrom-Json
        if ($code -ne 0 -or -not $reply.ok) { throw "Verification failed: $($reply.error). Offline nodes are not ignored." }
        Write-Host "VERIFIED: $($reply.nodes.Count) nodes; logs, commit/apply indices and x match."
    } elseif ($Operation -eq 'stop-all') {
        $errors=@()
        foreach ($record in $session.nodes) {
            try { Stop-OwnedNode $session $record } catch { $errors+=$_.ToString() }
        }
        Save-Session $session $RunDir
        if ($errors.Count) { throw ($errors -join '; ') }
        Write-Host 'Stopped only the processes owned by this session. Data was retained.'
    } else {
        $record=@($session.nodes | Where-Object id -eq $Id)
        if ($record.Count -ne 1) { throw 'Choose a configured node owned by this session.' }
        $record=$record[0]
        if ($Operation -eq 'stop') {
            Stop-OwnedNode $session $record
            Save-Session $session $RunDir
            Write-Host "Stopped node $Id. Configuration and data retained."
        } else {
            if (Get-OwnedProcess $session $record) { throw "Node $Id is already running." }
            $member=@((Get-Content $config -Raw -Encoding UTF8 | ConvertFrom-Json).nodes | Where-Object id -eq $Id)[0]
            $uri=[Uri]('tcp://'+$member.addr)
            $ip=[Net.Dns]::GetHostAddresses($uri.DnsSafeHost) | Select-Object -First 1
            $listener=[Net.Sockets.TcpListener]::new($ip,$uri.Port)
            $listener.Server.ExclusiveAddressUse=$true
            try { $listener.Start() } finally { $listener.Stop() }
            $process=$null
            $ok=$false
            try {
                $process=Start-Process -FilePath $exe -ArgumentList (Get-NodeArguments $Id $RunDir) -PassThru
                $new=New-NodeRecord $process $Id $RunDir
                $deadline=[DateTime]::UtcNow.AddSeconds(10)
                while ([DateTime]::UtcNow -lt $deadline) {
                    if ($process.HasExited) { throw 'Restarted process exited; inspect node log.' }
                    $raw=& $exe -config $config -status-all -timeout 1s
                    if ($LASTEXITCODE -ne 0) { throw 'Restart status query failed.' }
                    $states=$raw | ConvertFrom-Json
                    $state=@($states | Where-Object id -eq $Id)
                    if ($state.Count -eq 1 -and -not $state[0].error -and -not $process.HasExited) {
                        $record.pid=$new.pid;$record.started_utc_ticks=$new.started_utc_ticks
                        Save-Session $session $RunDir
                        $ok=$true
                        break
                    }
                    Start-Sleep -Milliseconds 100
                }
                if (-not $ok) { throw 'Restarted node did not report Status within 10 seconds.' }
                Write-Host "Restarted node $Id using its original directory; use verify after catch-up."
            } finally {
                if (-not $ok -and $process -and -not $process.HasExited) { $process.Kill();$process.WaitForExit(5000) | Out-Null }
            }
        }
    }
}

if ($Action -ne 'menu') { Invoke-DemoAction $Action $NodeID; exit 0 }
while ($true) {
    Write-Host "`n1 Status  2 Watch  3 Generate $Count commands  4 Verify  5 Stop node  6 Restart node  7 Stop all  0 Exit (leave nodes running)"
    $choice=Read-Host 'Action'
    if ($choice -eq '0') { break }
    $operations=@{'1'='status';'2'='watch';'3'='generate';'4'='verify';'5'='stop';'6'='restart';'7'='stop-all'}
    if (-not $operations.ContainsKey($choice)) { Write-Host 'Choose 0..7.';continue }
    $id=0
    if ($choice -in '5','6') {
        if (-not [int]::TryParse((Read-Host 'Node ID'),[ref]$id)) { Write-Host 'Invalid node ID.';continue }
    }
    try { Invoke-DemoAction $operations[$choice] $id } catch { Write-Warning $_ }
}
