@echo off
rem Saves the Fish S2 Pro server log + PC memory/GPU info to fish-log.txt (read-only, changes nothing).
cd /d "%~dp0"
set OUT=%~dp0fish-log.txt
set FISH=%LOCALAPPDATA%\VoicebookStudio\fish-speech
if exist "%~dp0fish-location.txt" set /p FISH=<"%~dp0fish-location.txt"
echo Collecting Fish logs into fish-log.txt ...
> "%OUT%" echo ==== %DATE% %TIME%   Fish folder: %FISH%
pushd "%FISH%"
>> "%OUT%" echo ==== containers
docker compose --profile server ps -a >> "%OUT%" 2>&1
>> "%OUT%" echo ==== server log (last 400 lines)
docker compose --profile server logs --no-color --tail 400 >> "%OUT%" 2>&1
>> "%OUT%" echo ==== compose.yml
type compose.yml >> "%OUT%" 2>&1
>> "%OUT%" echo ==== .env
type .env >> "%OUT%" 2>&1
popd
>> "%OUT%" echo ==== docker memory limit
docker info --format "CPUs={{.NCPU}} RAM_GB={{.MemTotal}}" >> "%OUT%" 2>&1
>> "%OUT%" echo ==== .wslconfig
type "%USERPROFILE%\.wslconfig" >> "%OUT%" 2>&1
>> "%OUT%" echo ==== PC memory
powershell -NoProfile -Command "$o=Get-CimInstance Win32_OperatingSystem; 'Total RAM GB: {0:N1}  Free: {1:N1}' -f ($o.TotalVisibleMemorySize/1MB), ($o.FreePhysicalMemory/1MB)" >> "%OUT%" 2>&1
>> "%OUT%" echo ==== GPU
nvidia-smi >> "%OUT%" 2>&1
echo Done. Tell Claude "logs saved".
pause
