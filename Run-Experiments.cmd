@echo off
setlocal
cd /d "%~dp0" || exit /b 1
where go >nul 2>&1
if errorlevel 1 (
 echo Install Go 1.26.3 or newer and add it to PATH. See docs\quick-start-zh.md.
 pause
 exit /b 1
)
where python >nul 2>&1
if errorlevel 1 (
 echo Install Python 3.12 or newer and add it to PATH. See docs\quick-start-zh.md.
 pause
 exit /b 1
)
python scripts\benchmark.py --nodes 10 20 50 100 --entries 2101 --rounds 3 --scenarios election failover replication catchup divergence
set "result=%errorlevel%"
pause
exit /b %result%
