@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3.12 -V >nul 2>nul
if not errorlevel 1 goto py312
py -3.13 -V >nul 2>nul
if not errorlevel 1 goto py313
py -3.14 -V >nul 2>nul
if not errorlevel 1 goto py314
goto usepython
:py312
py -3.12 -I -B bootstrap.py %*
goto done
:py313
py -3.13 -I -B bootstrap.py %*
goto done
:py314
py -3.14 -I -B bootstrap.py %*
goto done
:usepython
python -I -B bootstrap.py %*
:done
if errorlevel 1 (
 echo Setup failed. Check runtime\logs\setup.log. Install 64-bit CPython 3.12-3.14.
 pause
 exit /b 1
)
pause
