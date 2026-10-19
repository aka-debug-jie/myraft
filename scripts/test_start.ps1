param(
    [Parameter(Mandatory=$true)][string]$WorkRoot,
    [switch]$BaselineOnly
)
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'start.ps1'
$project = Split-Path $PSScriptRoot -Parent
$work = [IO.Path]::GetFullPath($WorkRoot)
$owned=@{}

function Invoke-Start([string[]]$Arguments, [bool]$ExpectSuccess = $true) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptPath @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($ExpectSuccess -and $code -ne 0) { throw "start.ps1 failed ($code): $($output -join "`n")" }
    if (-not $ExpectSuccess -and $code -eq 0) { throw "start.ps1 unexpectedly succeeded: $($output -join "`n")" }
    if ($code -eq 0) {
        $index=[Array]::IndexOf($Arguments, '-RunDir')
        $run=$Arguments[$index+1]
        $owned[$run]=@(foreach ($nodePid in (Get-Content (Join-Path $run 'pids.json') -Raw | ConvertFrom-Json)) { Get-Process -Id $nodePid })
    }
    return ,$output
}

function Stop-Run([string]$RunDir) {
    foreach ($process in $owned[$RunDir]) {
        if ($process -and -not $process.HasExited) { $process.Kill() }
        if ($process -and -not $process.WaitForExit(10000)) { throw 'Owned test process did not exit.' }
    }
    $owned.Remove($RunDir)

}

function Read-Members([string]$ConfigPath) {
    return @((Get-Content $ConfigPath -Raw | ConvertFrom-Json).nodes)
}

if (Test-Path $work) { throw 'WorkRoot must be a new directory.' }
New-Item -ItemType Directory $work | Out-Null
if ($BaselineOnly) {
    $run = Join-Path $work 'baseline three nodes'
    try {
        Invoke-Start @('-Nodes','3','-RunDir',$run) | Out-Null
        $config = Join-Path $run 'nodes.json'
        $before = (Get-FileHash $config -Algorithm SHA256).Hash
        $countBefore = (Read-Members $config).Count
        Stop-Run $run
        Invoke-Start @('-RunDir',$run) | Out-Null
        $after = (Get-FileHash $config -Algorithm SHA256).Hash
        $countAfter = (Read-Members $config).Count
        if ($countBefore -ne 3 -or $countAfter -ne 11 -or $before -eq $after) {
            throw "Baseline did not reproduce overwrite: members $countBefore -> $countAfter; SHA256 $before -> $after"
        }
        Write-Host "BASELINE_REPRODUCED members=$countBefore->$countAfter SHA256=$before->$after"
    } finally { Stop-Run $run }
    return
}

# Every test uses a newly created work root. The harness only stops PIDs recorded
# by starts it invoked; it never removes the root or any data/configuration.
$externalRun = Join-Path $work 'external config run'
$externalConfig = Join-Path $work 'external configs with spaces\members.json'
New-Item -ItemType Directory -Force (Split-Path $externalConfig -Parent) | Out-Null
$external = @{ nodes = @(
    @{ id = 7; addr = '127.0.0.1:18007' },
    @{ id = 19; addr = '127.0.0.1:18019' },
    @{ id = 42; addr = '127.0.0.1:18042' }
) }
[IO.File]::WriteAllText($externalConfig, ($external | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
try {
    Invoke-Start @('-Config',$externalConfig,'-RunDir',$externalRun) | Out-Null
    $runConfig = Join-Path $externalRun 'nodes.json'
    if (-not (Test-Path $runConfig)) { throw 'First external config was not copied to RunDir/nodes.json.' }
    $persisted = Read-Members $runConfig
    if (($persisted.id -join ',') -ne '7,19,42') { throw "Unexpected persisted members: $($persisted.id -join ',')" }
    $beforeHash = (Get-FileHash $runConfig -Algorithm SHA256).Hash
    $write=& "$project\raft-node.exe" -config $runConfig -demo 2101 -seed 42 -timeout 60s
    if ($LASTEXITCODE -ne 0) { throw 'Initial 2101-command write failed.' }
    $write=$write | ConvertFrom-Json
    if (-not $write.committed) { throw 'Write was not committed.' }

    Stop-Run $externalRun
    Invoke-Start @('-RunDir',$externalRun) | Out-Null
    $afterHash = (Get-FileHash $runConfig -Algorithm SHA256).Hash
    if ($beforeHash -ne $afterHash) { throw 'Reusing RunDir changed nodes.json.' }
    if ((Read-Members $runConfig).Count -ne 3) { throw 'Omitted Nodes changed three members.' }
    $deadline=[DateTime]::UtcNow.AddSeconds(20)
    do {
        $verified=& "$project\raft-node.exe" -config $runConfig -verify -target-index $write.last_index
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($LASTEXITCODE -ne 0) { throw 'Recovered nodes failed verification.' }
    $verified=$verified | ConvertFrom-Json
    foreach ($node in $verified.nodes) { if ($node.applied_commands -ne 2101) { throw 'Restart lost commands.' } }

    Stop-Run $externalRun
    $conflictingConfig = Join-Path $work 'external configs with spaces\conflicting-members.json'
    $external.nodes[2].addr = '127.0.0.1:18043'
    [IO.File]::WriteAllText($conflictingConfig, ($external | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
    Invoke-Start @('-Config',$conflictingConfig,'-RunDir',$externalRun) $false | Out-Null
    if ((Get-FileHash $runConfig -Algorithm SHA256).Hash -ne $beforeHash) { throw 'Conflicting same-count member addresses overwrote nodes.json.' }
    Invoke-Start @('-Nodes','11','-RunDir',$externalRun) $false | Out-Null
    if ((Get-FileHash $runConfig -Algorithm SHA256).Hash -ne $beforeHash) { throw 'Conflicting Nodes overwrote nodes.json.' }
} finally { Stop-Run $externalRun }

$missingRun = Join-Path $work 'legacy data without config'
New-Item -ItemType Directory -Force (Join-Path $missingRun 'data') | Out-Null
Set-Content -Encoding ascii (Join-Path $missingRun 'data\existing.marker') 'keep'
try {
    Invoke-Start @('-RunDir',$missingRun) $false | Out-Null
    if (Test-Path (Join-Path $missingRun 'nodes.json')) { throw 'Missing-config legacy directory was guessed and populated.' }
    if (-not (Test-Path (Join-Path $missingRun 'data\existing.marker'))) { throw 'Existing legacy data was removed.' }
} finally { Stop-Run $missingRun }


$brokenRun=Join-Path $work 'broken node startup'
New-Item -ItemType Directory (Join-Path $brokenRun 'data') -Force | Out-Null
Copy-Item $runConfig (Join-Path $brokenRun 'nodes.json')
$brokenState=Join-Path $brokenRun 'data\node-7-state.json'
[IO.File]::WriteAllText($brokenState,'broken')
$brokenHash=(Get-FileHash $brokenState).Hash
Invoke-Start @('-RunDir',$brokenRun) $false | Out-Null
if ((Get-FileHash $brokenState).Hash -ne $brokenHash) { throw 'Failed startup changed corrupt state.' }
foreach ($nodePid in (Get-Content (Join-Path $brokenRun 'pids.json') -Raw | ConvertFrom-Json)) {
    $process=Get-Process -Id $nodePid -ErrorAction SilentlyContinue
    if ($process -and $process.Path -eq (Join-Path $project 'raft-node.exe')) { throw 'Failed startup left a node alive.' }
}

Write-Host 'START_ACCEPTANCE_PASSED'
