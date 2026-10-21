@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Model chatterbox
if errorlevel 1 echo Chatterbox setup failed. Qwen and the app are unaffected.
pause
