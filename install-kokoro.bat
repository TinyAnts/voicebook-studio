@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Model kokoro
if errorlevel 1 echo Kokoro setup failed. Other models remain available.
pause
