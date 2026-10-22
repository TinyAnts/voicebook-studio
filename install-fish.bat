@echo off
cd /d "%~dp0"
echo Installing the optional Fish S2 Pro (4-bit) engine. Needs Docker Desktop and about 15 GB of disk.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-fish.ps1" %*
if errorlevel 1 (
  echo Fish setup failed. Qwen still works normally.
)
pause
