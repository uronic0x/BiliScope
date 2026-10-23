@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Run install.bat first.
 pause
 exit /b 1
)
if not exist "runtime\logs" mkdir "runtime\logs"
.venv\Scripts\python.exe -I -B main.py %* > "runtime\logs\console.log" 2>&1
if errorlevel 1 (
 echo Application failed. See runtime\logs\console.log.
 pause
)
