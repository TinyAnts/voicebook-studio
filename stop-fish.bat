@echo off
set FISH=%LOCALAPPDATA%\VoicebookStudio\fish-speech
if exist "%~dp0fish-location.txt" set /p FISH=<"%~dp0fish-location.txt"
if not exist "%FISH%\compose.yml" (
  echo Fish S2 Pro is not installed.
  pause
  exit /b 0
)
cd /d "%FISH%"
docker compose --profile server down
echo Fish server stopped. The GPU is free for Qwen.
pause
