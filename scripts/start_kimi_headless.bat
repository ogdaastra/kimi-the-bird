@echo off
REM Runs Kimi without a window (it keeps living in the background).
REM Close this window or press Ctrl+C to stop Kimi; its world is saved on exit.
cd /d "%~dp0\.."
".venv\Scripts\python.exe" main.py --headless
