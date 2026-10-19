@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
if not "%~1"=="" (
 powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Config "%~1"
) else (
 set "nodeCount=11"
 set /p "nodeCount=Number of nodes [11]: "
 powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Nodes !nodeCount!
)
set "result=%errorlevel%"
pause
exit /b %result%
