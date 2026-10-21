@echo off
cd /d "%~dp0"
if not exist ".venv-ui\Scripts\python.exe" (
  echo UI missing! Run install.bat first.
  pause
  exit /b 1
)
".venv-ui\Scripts\python.exe" app.py
if errorlevel 1 pause
