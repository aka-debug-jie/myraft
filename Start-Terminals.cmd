@echo off
setlocal
set "runDir=%~1"
if not defined runDir set "runDir=%~dp0demo-runs\classroom"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -UsePrebuilt -RunDir "%runDir%"
exit /b %errorlevel%
