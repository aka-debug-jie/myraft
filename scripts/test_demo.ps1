param([Parameter(Mandatory=$true)][string]$WorkRoot)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'session.ps1')
$project=Split-Path $PSScriptRoot -Parent
$work=[IO.Path]::GetFullPath($WorkRoot)
if (Test-Path $work) { throw 'WorkRoot must be new.' }
$run=Join-Path $work 'eleven nodes with spaces'
$exe=Join-Path $project 'raft-node.exe'
$extra=$null;$watcher=$null;$originalSession=$null
function Demo([string[]]$Arguments,[bool]$Success=$true) {
    $saved=$ErrorActionPreference;$ErrorActionPreference='Continue'
    try { $out=& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\demo.ps1" -RunDir $run @Arguments 2>&1;$code=$LASTEXITCODE } finally {$ErrorActionPreference=$saved}
    if ($Success -and $code -ne 0) {throw "Demo failed: $($out -join ' ')"}
    if (-not $Success -and $code -eq 0) {throw 'Unsafe demo operation unexpectedly succeeded.'}
    return ($out -join "`n")
}
function Verify-Eventually([int]$Target=0) {
    $deadline=[DateTime]::UtcNow.AddSeconds(30)
    do {
        $text=& $exe -config "$run\nodes.json" -verify -target-index $Target
        if ($LASTEXITCODE -eq 0) {return ($text | ConvertFrom-Json)}
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Cluster did not verify.'
}
try {
    $startup=& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\start.ps1" -RunDir $run
    if ($LASTEXITCODE -ne 0) {throw 'Startup failed.'}
    $startup=$startup -join "`n"
    if ($startup.IndexOf('[1/3]') -lt 0 -or $startup.IndexOf('[2/3]') -lt $startup.IndexOf('[1/3]') -or $startup.IndexOf('[3/3]') -lt $startup.IndexOf('[2/3]')) {throw 'Startup phases missing/out of order.'}
    $session=Read-Session $run
    if ($session.nodes.Count -ne 11) {throw 'Expected eleven owned processes.'}
    $states=(& $exe -config "$run\nodes.json" -status-all) | ConvertFrom-Json
    if (@($states | Where-Object applied_commands -ne 0).Count) {throw 'Startup implicitly wrote arithmetic commands.'}
    if (@($states | Where-Object { -not $_.log_hash }).Count) {throw 'Default JSON lost full hashes.'}
    if ((Demo @('-Action','status')) -notmatch 'ROLE\(local\)') {throw 'Missing terminal table.'}
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$exe
    $info.Arguments="-config `"$run\nodes.json`" -status-all -format table -watch 200ms"
    $info.UseShellExecute=$false
    $info.RedirectStandardOutput=$true
    $info.CreateNoWindow=$true
    $watcher=New-Object Diagnostics.Process
    $watcher.StartInfo=$info
    if (-not $watcher.Start()) {throw 'Could not start watch client.'}
    $deadline=[DateTime]::UtcNow.AddSeconds(8);$snapshots=0
    while ($snapshots -lt 2 -and [DateTime]::UtcNow -lt $deadline) {
        $line=$watcher.StandardOutput.ReadLineAsync()
        if (-not $line.Wait([int][Math]::Max(1,($deadline-[DateTime]::UtcNow).TotalMilliseconds))) {throw 'Watch read timed out.'}
        if ($null -eq $line.Result) {throw 'Watch exited before two observations.'}
        if ($line.Result -match '^Observed at ') {$snapshots++}
    }
    if ($snapshots -lt 2) {throw 'Watch did not refresh.'}
    $watcher.Kill();$watcher.WaitForExit();$watcher.Dispose();$watcher=$null

    # Another independently started node uses the same executable and ID, but a different directory.
    $other=Join-Path $work 'unrelated session'
    New-Item -ItemType Directory $other | Out-Null
    $socket=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0);$socket.Start();$port=$socket.LocalEndpoint.Port;$socket.Stop()
    $otherConfig=@{cluster_id='test-demo-other-cluster';nodes=@(@{id=$session.nodes[0].id;addr="127.0.0.1:$port"})}
    [IO.File]::WriteAllText("$other\nodes.json",($otherConfig | ConvertTo-Json -Depth 4),(New-Object Text.UTF8Encoding($false)))
    $extra=Start-Process -FilePath $exe -ArgumentList (Get-NodeArguments $session.nodes[0].id $other) -PassThru
    $manifest=Join-Path $run 'session.json'
    $originalSession=[IO.File]::ReadAllText($manifest)
    $session.nodes[0].pid=$extra.Id;$session.nodes[0].started_utc_ticks=$extra.StartTime.ToUniversalTime().Ticks.ToString()
    Save-Session $session $run
    Demo @('-Action','stop','-NodeID',[string]$session.nodes[0].id) $false | Out-Null
    if ($extra.HasExited) {throw 'Demo killed a process from another directory.'}
    [IO.File]::WriteAllText($manifest,$originalSession,(New-Object Text.UTF8Encoding($false)))
    $session=Read-Session $run
    $session.nodes[0].started_utc_ticks='1';Save-Session $session $run
    Demo @('-Action','stop','-NodeID',[string]$session.nodes[0].id) $false | Out-Null
    [IO.File]::WriteAllText($manifest,$originalSession,(New-Object Text.UTF8Encoding($false)));$originalSession=$null

    if ((Demo @('-Action','generate')) -notmatch 'COMMITTED: 2101') {throw 'Write was not confirmed.'}
    $initial=Verify-Eventually
    $checkpoint=$initial.nodes[0]
    $leader=@($initial.nodes | Where-Object state -eq 'Leader')[0].id
    Demo @('-Action','stop','-NodeID',[string]$leader) | Out-Null
    if ((Demo @('-Action','generate','-Count','1','-Seed','43')) -notmatch 'COMMITTED: 1') {throw 'Majority write after failure failed.'}
    Demo @('-Action','restart','-NodeID',[string]$leader) | Out-Null
    $final=Verify-Eventually $checkpoint.commit_index
    foreach ($node in $final.nodes) {
        if ($node.applied_commands -ne 2102 -or $node.target_hash -ne $checkpoint.committed_hash -or $node.target_x -ne $checkpoint.x) {throw 'Recovery changed command history.'}
    }
    if ((Demo @('-Action','verify')) -notmatch 'VERIFIED: 11') {throw 'Verify menu action failed.'}
    Demo @('-Action','stop-all') | Out-Null
    if (@((Read-Session $run).nodes | Where-Object pid -ne 0).Count) {throw 'Stop-all left owned records live.'}
    if ($extra.HasExited) {throw 'Stop-all killed an unrelated process.'}
    Write-Output 'DEMO_ACCEPTANCE_PASS: phases, JSON, table/watch, 2101 commands, failover/restart, history, identity guards, owned cleanup'
} finally {
    if ($originalSession) {[IO.File]::WriteAllText((Join-Path $run 'session.json'),$originalSession,(New-Object Text.UTF8Encoding($false)))}
    $cleanupError=$null
    if (Test-Path "$run\session.json") {try {Demo @('-Action','stop-all') | Out-Null} catch {$cleanupError=$_}}
    if ($watcher -and -not $watcher.HasExited) {$watcher.Kill();$watcher.WaitForExit()}
    if ($extra -and -not $extra.HasExited) {$extra.Kill();$extra.WaitForExit()}
    if ($cleanupError) {throw $cleanupError}
}
