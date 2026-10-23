@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" exit /b 1
.venv\Scripts\python.exe -I -B main.py --doctor > runtime\logs\doctor-console.log 2>&1
echo Report: runtime\exports\doctor.json
pause
