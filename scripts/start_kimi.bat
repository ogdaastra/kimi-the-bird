@echo off
REM Starts Kimi's desktop app without a console window.
cd /d "%~dp0\.."
if not exist ".venv\Scripts\pythonw.exe" (
    echo Kimi is not installed yet. Run scripts\install_windows.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
