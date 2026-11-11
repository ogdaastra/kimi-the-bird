@echo off
REM Sets up Kimi on Windows: creates a virtual environment and installs dependencies.
REM Requires Python 3.13 from python.org (or: winget install Python.Python.3.13).
REM Does not need administrator rights and does not change any system settings.
setlocal
cd /d "%~dp0\.."
where py >nul 2>nul
if %errorlevel%==0 (
    py -3.13 -m venv .venv
) else (
    python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo Could not create the virtual environment. Is Python 3.13 installed?
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installing dependencies failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo.
echo Kimi is installed. Start it with scripts\start_kimi.bat
pause
