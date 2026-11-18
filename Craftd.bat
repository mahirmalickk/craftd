@echo off
REM Double-click to start Craftd (after the one-time setup in README.md).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Craftd is not set up yet. Follow the Windows steps in README.md first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m craftd
