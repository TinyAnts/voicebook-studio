@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish-github.ps1"
if errorlevel 1 (
  echo Publishing was not completed. Your local application is unchanged.
)
pause
