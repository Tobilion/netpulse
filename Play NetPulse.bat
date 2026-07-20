@echo off
title NetPulse - ISP Performance Tracker
cd /d "%~dp0"

echo ==========================================
echo    NetPulse
echo    ISP Performance Tracker
echo ==========================================
echo.

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo [!] Python is not installed, or not on your PATH.
    echo     Install it from https://python.org and tick
    echo     "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" goto setup
goto run

:setup
echo First run detected - creating a virtual environment...
echo.
call %PY% -m venv venv
if errorlevel 1 (
    echo [!] Could not create the virtual environment.
    pause
    exit /b 1
)
echo Installing dependencies. This can take a minute...
call "venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [!] Dependency install failed. Scroll up to see why.
    pause
    exit /b 1
)
echo.

:run
echo Starting the dashboard on port 5000...
echo Your browser will open automatically.
echo.
echo Leave this window open. Press Ctrl+C to stop.
echo.

start "" /min cmd /c "timeout /t 4 /nobreak >nul & start "" http://localhost:5000"
"venv\Scripts\python.exe" main.py serve

echo.
echo Dashboard stopped.
pause
