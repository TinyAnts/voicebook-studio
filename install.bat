@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Model qwen
if errorlevel 1 (
  echo Installation failed. Read the error above.
  pause
  exit /b 1
)
pause
