@echo off
setlocal
echo Recommended console: http://127.0.0.1:8080/prototype/?renderer=svg
cd /d "%~dp0" || exit /b 1
raft-console.exe -node-bin ".\raft-node.exe" -source-dir "." -allow-control
pause
