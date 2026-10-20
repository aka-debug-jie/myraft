$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$package='P:\Xinbao\绿色移交验收 with spaces 20261020'
$project=Join-Path $package 'project'
$python='P:\Xinbao\acceptance-20261020-native\portable-experiment-python'
if(Test-Path $python){throw 'new isolated interpreter directory required'}
Copy-Item 'P:\Xinbao\myraft-win11\tools\python' $python -Recurse
[IO.File]::WriteAllText("$python\python313._pth","python313.zip`n.`n$project\scripts`n",[Text.UTF8Encoding]::new($false))
$env:PATH="$python;P:\Xinbao\myraft-win11\tools\go\bin;$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
$env:GOTOOLCHAIN='local';$env:GOFLAGS='-buildvcs=false';$env:GOCACHE='P:\Xinbao\myraft-win11\.cache\go-build';$env:GOPATH='P:\Xinbao\myraft-win11\.cache\gopath'
$env:TEMP='P:\Xinbao\public-build-temp';$env:TMP=$env:TEMP
Set-Location $project
& python -m unittest discover -s scripts -p 'test_*.py'
if($LASTEXITCODE){throw 'packaged Python tests failed'}
& python scripts/benchmark.py --nodes 3 --entries 2101 --rounds 1 --scenarios replication --output "$package\reproduction-check"
if($LASTEXITCODE){throw 'packaged experiment failed'}
Get-Content "$package\reproduction-check\run-status.json" -Raw
Write-Output 'PORTABLE_EXPERIMENT_PASS explicit_Go_Python_dependencies'
