# Local demonstration process ownership; never identify a process by PID alone.
function Get-NodeArguments([int]$Id, [string]$RunDir) {
    return "-id $Id -config `"$RunDir\nodes.json`" -data-dir `"$RunDir\data`" -log-dir `"$RunDir\logs`""
}
function New-NodeRecord($Process, [int]$Id, [string]$RunDir) {
    return [pscustomobject]@{ id=$Id; pid=$Process.Id; started_utc_ticks=$Process.StartTime.ToUniversalTime().Ticks.ToString(); arguments=(Get-NodeArguments $Id $RunDir) }
}
function Save-Session($Session, [string]$RunDir) {
    $path=Join-Path $RunDir 'session.json'
    [IO.File]::WriteAllText("$path.tmp", ($Session | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath "$path.tmp" -Destination $path -Force
}
function Read-Session([string]$RunDir) {
    $path=Join-Path $RunDir 'session.json'
    if (-not (Test-Path $path)) { throw 'No owned session. Run scripts/start.ps1 with this RunDir first.' }
    $session=Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($session.version -ne 1 -or $session.run_dir -ine $RunDir) { throw 'Session belongs to a different directory.' }
    if ((Get-FileHash "$RunDir\nodes.json" -Algorithm SHA256).Hash -ne $session.config_sha256) { throw 'Configuration changed since startup; refusing process control.' }
    if ((Get-FileHash $session.executable -Algorithm SHA256).Hash -ne $session.executable_sha256) { throw 'Executable changed since startup; start a new owned session.' }
    $members=(Get-Content "$RunDir\nodes.json" -Raw -Encoding UTF8 | ConvertFrom-Json).nodes
    $ids=@($session.nodes | ForEach-Object { [int]$_.id })
    if (@($ids | Select-Object -Unique).Count -ne $ids.Count) { throw 'Duplicate session node IDs.' }
    foreach ($record in $session.nodes) {
        if ($record.id -notin $members.id -or $record.arguments -cne (Get-NodeArguments $record.id $RunDir)) { throw 'Session node configuration does not match.' }
    }
    return $session
}
function Get-OwnedProcess($Session, $Record) {
    if ($Record.pid -eq 0) { return $null }
    $process=Get-Process -Id $Record.pid -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    $null=$process.Handle
    if ($process.Path -ine $Session.executable -or $process.StartTime.ToUniversalTime().Ticks.ToString() -ne $Record.started_utc_ticks) {
        throw "Process identity changed for node $($Record.id); no process was stopped."
    }
    $info=Get-CimInstance Win32_Process -Filter "ProcessId = $($Record.pid)"
    if (-not $info.CommandLine.TrimEnd().EndsWith(' '+$Record.arguments,[StringComparison]::Ordinal)) {
        throw "Process arguments differ for node $($Record.id); no process was stopped."
    }
    return $process
}
function Stop-OwnedNode($Session, $Record) {
    $process=Get-OwnedProcess $Session $Record
    if ($process) {
        $process.Kill()
        if (-not $process.WaitForExit(5000)) { throw "Node $($Record.id) did not exit." }
    }
    $Record.pid=0
    $Record.started_utc_ticks=''
}
function Test-LeaderObserved($States) {
    $leaders=@($States | Where-Object { -not $_.error -and $_.state -eq 'Leader' -and $_.leader_id -eq $_.id })
    if ($leaders.Count -ne 1) { return $false }
    foreach ($state in $States) {
        if ($state.error -or $state.term -ne $leaders[0].term -or $state.leader_id -ne $leaders[0].id) { return $false }
    }
    return $true
}
