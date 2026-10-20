$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$zip='P:\Xinbao\myraft-course-candidate2.zip'
$root='P:\Xinbao\绿色移交验收 with spaces 20261020'
if(Test-Path $root){throw 'fresh directory required'}
Expand-Archive -LiteralPath $zip -DestinationPath $root
$project=Join-Path $root 'project'
$run=Join-Path $root 'runs\classroom'
$env:PATH="$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
$env:TEMP='P:\Xinbao\public-build-temp';$env:TMP=$env:TEMP
if((Get-Command go -ErrorAction SilentlyContinue) -or (Get-Command python -ErrorAction SilentlyContinue)){throw 'demo dependency isolation failed'}
$checked=0
foreach($line in [IO.File]::ReadAllLines("$root\SHA256SUMS.txt",[Text.Encoding]::UTF8)){
 if($line -notmatch '^([a-f0-9]{64})  (.+)$'){throw 'invalid checksum line'}
 if((Get-FileHash -LiteralPath (Join-Path $root $Matches[2])).Hash.ToLowerInvariant() -ne $Matches[1]){throw "checksum differs: $($Matches[2])"}
 $checked++
}
Set-Location $project
$exe=Join-Path $project 'raft-node.exe'
$result=@{result='FAIL';checksums=$checked;go_on_path=$false;python_on_path=$false;manual_visible_windows='NOT RUN';source='fresh portable ZIP, original prebuilt EXEs';package_sha256=(Get-FileHash $zip).Hash.ToLowerInvariant()}
function Demo([string]$action,[int]$id=0){
 & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$project\scripts\demo.ps1" -RunDir $run -Action $action -NodeID $id
 if($LASTEXITCODE){throw "demo $action failed"}
}
function Verify([int]$target=0){
 $end=[DateTime]::UtcNow.AddSeconds(30)
 do {
  $raw=& $exe -config "$run\nodes.json" -verify -target-index $target
  if($LASTEXITCODE -eq 0){return ($raw|ConvertFrom-Json)}
  Start-Sleep -Milliseconds 100
 }while([DateTime]::UtcNow -lt $end)
 throw 'full convergence verification failed'
}
$failure=$null
try{
 & cmd.exe /d /c "`"$root\Start-Terminals.cmd`" <nul" | Out-File "$root\terminal-start.txt" -Encoding UTF8
 if($LASTEXITCODE){throw 'prebuilt terminal entry failed'}
 $owned=Get-Content "$run\session.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if($owned.nodes.Count -ne 11){throw 'not 11 independent owned nodes'}
 $result.initial_processes=$owned.nodes.Count
 $write=(& $exe -config "$run\nodes.json" -demo 2101 -seed 42 -timeout 60s)|ConvertFrom-Json
 if($LASTEXITCODE -or !$write.accepted -or !$write.committed){throw 'unconfirmed write'}
 $first=Verify
 if(@($first.nodes|Where-Object applied_commands -ne 2101).Count){throw 'arithmetic command count differs'}
 [IO.File]::WriteAllText("$root\initial-verify.json",($first|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
 $checkpoint=$first.nodes[0];$leader=@($first.nodes|Where-Object state -eq 'Leader')[0].id
 Demo 'stop' $leader
 $next=(& $exe -config "$run\nodes.json" -demo 1 -seed 43 -timeout 60s)|ConvertFrom-Json
 if($LASTEXITCODE -or !$next.committed){throw 'majority failover write failed'}
 Demo 'restart' $leader
 $restored=Verify $checkpoint.commit_index
 foreach($s in $restored.nodes){if($s.target_hash -ne $checkpoint.committed_hash -or $s.target_x -ne $checkpoint.x -or $s.applied_commands -ne 2102){throw 'restored node changed history'}}
 Demo 'stop-all'
 & cmd.exe /d /c "`"$root\Start-Terminals.cmd`" <nul" | Out-File "$root\terminal-resume.txt" -Encoding UTF8
 if($LASTEXITCODE){throw 'same-directory resume failed'}
 $final=Verify $checkpoint.commit_index
 foreach($s in $final.nodes){if($s.target_hash -ne $checkpoint.committed_hash -or $s.target_x -ne $checkpoint.x -or $s.applied_commands -ne 2102){throw 'whole-cluster restart changed history'}}
 [IO.File]::WriteAllText("$root\final-verify.json",($final|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
 $result.result='PASS';$result.commands=2101;$result.final_commands=2102;$result.checkpoint_index=$checkpoint.commit_index;$result.checkpoint_hash=$checkpoint.committed_hash;$result.checkpoint_x=$checkpoint.x;$result.closed_leader=$leader;$result.restart_verified=$true
} catch {$failure=$_.ToString();$result.error=$failure}
finally{
 if(Test-Path "$run\session.json") {try{Demo 'stop-all'}catch{$result.result='FAIL';$result.cleanup_error=$_.ToString()}}
 $live=@(Get-CimInstance Win32_Process -Filter "Name='raft-node.exe'"|Where-Object ExecutablePath -eq $exe)
 $result.owned_nodes_remaining=$live.Count
 if($live.Count){$result.result='FAIL'}
 [IO.File]::WriteAllText("$root\portable-check.json",($result|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
}
$result|ConvertTo-Json -Depth 8
if($result.result -ne 'PASS'){throw 'portable acceptance failed; see saved diagnostics'}
Write-Output 'PORTABLE_TERMINALS_AUTOMATED_PASS manual_visibility_not_run'
