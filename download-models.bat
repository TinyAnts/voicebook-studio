@echo off
cd /d "%~dp0"
if "%HF_HOME%"=="" if exist D:\hf-cache set HF_HOME=D:\hf-cache
echo Downloading the three Qwen 1.7B voice models (about 4.5 GB each, skipped if already there)
echo into: %HF_HOME%
".venv-qwen\Scripts\python.exe" download_models.py
if errorlevel 1 (
  echo.
  echo Download not finished. Run this file again - finished files are kept.
) else (
  echo.
  echo All Qwen models are ready: built-in voices, library narrators and Create a narrator.
)
pause
