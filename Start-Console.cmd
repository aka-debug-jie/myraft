@echo off
setlocal
cd /d "%~dp0" || exit /b 1
raft-console.exe -node-bin ".\raft-node.exe" -source-dir "." -allow-control
pause
