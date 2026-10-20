$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$package='P:\Xinbao\绿色移交验收 with spaces 20261020'
$root=Join-Path $package 'project'
$env:PATH="$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
if((Get-Command go -ErrorAction SilentlyContinue) -or (Get-Command python -ErrorAction SilentlyContinue)){throw 'demo dependency isolation failed'}
$env:TEMP='P:\Xinbao\public-build-temp';$env:TMP=$env:TEMP
Set-Location $root
$out=Join-Path $root 'native-console-final-out.txt'
$errlog=Join-Path $root 'native-console-final-err.txt'
$launcher=Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" -ArgumentList "/d /c `"`"$package\Start-Console.cmd`" <nul`"" -RedirectStandardOutput $out -RedirectStandardError $errlog -PassThru
$controller=$null
$end=[DateTime]::UtcNow.AddSeconds(10)
while([DateTime]::UtcNow -lt $end){
 $child=@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($launcher.Id)"|Where-Object ExecutablePath -eq "$root\raft-console.exe")
 if($child.Count -eq 1){$controller=Get-Process -Id $child[0].ProcessId;$null=$controller.Handle;break}
 if($launcher.HasExited){throw 'console entry exited'}
 Start-Sleep -Milliseconds 100
}
if(!$controller){throw 'console entry did not start its executable'}
try {
 $url=$null
 for($i=0;$i -lt 100;$i++) {
  if(Test-Path $out) {$line=Get-Content $out -Raw;if($line){$m=[regex]::Match($line,'http://127\.0\.0\.1:\d+');if($m.Success){$url=$m.Value;break}}}
  Start-Sleep -Milliseconds 100
 }
 if(!$url){throw 'No console URL'}
 function Read-Frame {Invoke-RestMethod "$url/api/snapshot"}
 function Send-Op([string]$kind,[hashtable]$extra=@{}) {
  $boot=Invoke-RestMethod "$url/api/session";$frame=Read-Frame
  $id='';if($null -ne $frame.session){$id=$frame.session.id}
  $body=@{kind=$kind;controller_id=$frame.controller_id;session_id=$id;generation=$frame.generation}
  foreach($key in $extra.Keys){$body[$key]=$extra[$key]}
  Invoke-RestMethod "$url/api/operations" -Method Post -ContentType 'application/json; charset=utf-8' -Headers @{Origin=$url;'X-CSRF-Token'=$boot.csrf_token} -Body ($body|ConvertTo-Json -Depth 8)
 }
 function Wait-Op($op) {
  for($i=0;$i -lt 600;$i++) {
   $r=Invoke-RestMethod "$url/api/operations/$($op.id)"
   if($r.ended_at){if($r.state -ne 'succeeded'){throw ($r|ConvertTo-Json -Depth 12)};return $r}
   Start-Sleep -Milliseconds 100
  }
  throw 'Operation timeout'
 }
 Send-Op 'enable_control' @{confirm=$true}|Out-Null
 Wait-Op (Send-Op 'create_session' @{name='Win11 console acceptance';nodes=@(11);batch=128})|Out-Null
 for($i=0;$i -lt 100;$i++) { $f=Read-Frame;if(@($f.snapshot.nodes|Where-Object {$_.status.state -eq 'Leader'}).Count -eq 1){break};Start-Sleep -Milliseconds 100 }
 $write=Wait-Op (Send-Op 'generate' @{count=2101;seed=42})
 if(!$write.accepted -or !$write.committed){throw 'Write not confirmed'}
 for($i=0;$i -lt 100;$i++) { $f=Read-Frame;if(@($f.snapshot.nodes|Where-Object {$_.status.applied_commands -eq 2101}).Count -eq 11){break};Start-Sleep -Milliseconds 100 }
 if(@($f.snapshot.nodes|Where-Object {$_.status.applied_commands -eq 2101}).Count -ne 11){throw 'Application did not converge'}
 Wait-Op (Send-Op 'checkpoint')|Out-Null
 Wait-Op (Send-Op 'verify')|Out-Null
 Wait-Op (Send-Op 'stop_all' @{confirm=$true})|Out-Null
 Wait-Op (Send-Op 'resume')|Out-Null
 for($i=0;$i -lt 100;$i++) { $f=Read-Frame;if(@($f.snapshot.nodes|Where-Object {$_.status.applied_commands -eq 2101}).Count -eq 11){break};Start-Sleep -Milliseconds 100 }
 Wait-Op (Send-Op 'verify_history')|Out-Null
 $export=Wait-Op (Send-Op 'export')
 Invoke-WebRequest -UseBasicParsing "$url/api/exports/$($export.id)" -OutFile "$root\native-console-final-evidence.zip"
 if((Get-FileHash "$root\native-console-final-evidence.zip").Hash.ToLowerInvariant() -ne $export.result.sha256){throw 'Export digest mismatch'}
 Wait-Op (Send-Op 'stop_all' @{confirm=$true})|Out-Null
 $f=Read-Frame
 $operations=$f.operations | ConvertTo-Json -Depth 30
 [IO.File]::WriteAllText("$root\native-console-operations.json",$operations,[Text.UTF8Encoding]::new($false))
 $result=@{entrypoint='Start-Console.cmd';go_on_path=$false;python_on_path=$false;result='PASS';platform='Windows 11';nodes=11;commands=2101;checkpoint=$f.checkpoint;history=$f.history_verification.state;export_sha256=$export.result.sha256;protocol='real HTTP + real net/rpc';browser='not used in this native smoke'}
 $result|ConvertTo-Json -Depth 8|Set-Content "$root\native-console-final-result.json" -Encoding UTF8
 $result|ConvertTo-Json -Depth 8
} finally {
 if($url){try {Wait-Op (Send-Op 'stop_all' @{confirm=$true})|Out-Null}catch{Write-Output "cleanup note: $_"}}
 if(!$controller.HasExited){$controller.Kill();$controller.WaitForExit()}
 if(!$launcher.WaitForExit(5000)){$launcher.Kill();$launcher.WaitForExit();throw 'entry launcher did not finish'}
}
