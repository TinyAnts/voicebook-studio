@echo off
cd /d "%~dp0"
echo Installing the optional FAST Qwen engine (CUDA graphs) in .venv-qwenfast ...
echo Your existing .venv-qwen, models and audiobooks are not changed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Model qwenfast
if errorlevel 1 (
  echo Installation failed. Read the error above. The standard batched engine still works.
  pause
  exit /b 1
)
echo Done. Restart start.bat. "Auto" engine now uses the fast engine.
pause
