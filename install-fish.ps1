# Optional engine: Fish Audio S2 Pro, 4-bit (NF4) build, served by Docker on your NVIDIA GPU.
# Licence: Fish Audio Research License (research / non-commercial use).
# Installs to %LOCALAPPDATA%\VoicebookStudio\fish-speech (outside OneDrive). Your app, audiobooks
# and Qwen environments are not changed. Needs Docker Desktop (WSL2 backend, GPU support) and Git.
param([string]$Target = '')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$Pointer = Join-Path $PSScriptRoot 'fish-location.txt'
if (-not $Target -and (Test-Path $Pointer)) { $Target = (Get-Content $Pointer -Raw).Trim() }
if (-not $Target) { $Target = Join-Path $env:LOCALAPPDATA 'VoicebookStudio\fish-speech' }

# About 6 GB for the model + code, plus 10-15 GB for the Docker image (stored by Docker Desktop).
function FreeGB($path) {
    $root = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($path))
    [math]::Round((New-Object System.IO.DriveInfo($root)).AvailableFreeSpace / 1GB, 1)
}
$free = FreeGB $Target
Write-Host "Install folder: $Target  ($free GB free on that drive)"
if ($free -lt 8) {
    $others = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 10GB -and $_.Root -ne [System.IO.Path]::GetPathRoot($Target) } |
              ForEach-Object { "$($_.Root) ($([math]::Round($_.Free/1GB)) GB free)" }
    Write-Host "Not enough free space (need about 8 GB here, plus room for Docker's image)." -ForegroundColor Red
    if ($others) { Write-Host ("Drives with more space: " + ($others -join ', ')) -ForegroundColor Yellow
                   Write-Host 'Install there with:  install-fish.bat D:\VoicebookFish   (any folder on that drive)' -ForegroundColor Yellow }
    throw 'Free up disk space or choose another drive, then run install-fish.bat again. Nothing was changed.'
}
Set-Content -Encoding ascii -Path $Pointer -Value $Target
$Repo = 'https://github.com/scarxity/fish-speech-int4-patch.git'
$Commit = '3fd7da6a65dfeb9f8ad1975813301ed16c4da47a'   # tested revision of the 4-bit fork

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Need($ok, $msg) { if (-not $ok) { throw $msg } }

Step 'Checking Docker Desktop'
docker version --format '{{.Server.Version}}' | Out-Host
Need ($LASTEXITCODE -eq 0) 'Docker is not running. Start Docker Desktop, wait until it says "Engine running", then run this again.'
docker compose version | Out-Host
Need ($LASTEXITCODE -eq 0) 'Docker Compose v2 is missing. Update Docker Desktop.'
Step 'Checking that Docker can see your NVIDIA GPU'
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi | Out-Host
Need ($LASTEXITCODE -eq 0) 'Docker cannot use the GPU. In Docker Desktop: Settings > General > "Use the WSL 2 based engine", update the NVIDIA driver, then retry.'

Step 'Getting the Fish S2 Pro 4-bit server code'
$git = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $git) { $git = "${env:ProgramFiles}\Git\cmd\git.exe" }
Need (Test-Path $git) 'Git is required: https://git-scm.com/downloads/win'
if (-not (Test-Path (Join-Path $Target '.git'))) {
    $parent = Split-Path $Target
    if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    & $git clone $Repo $Target
    Need ($LASTEXITCODE -eq 0) 'Could not download the Fish server code.'
}
& $git -C $Target fetch --quiet origin
& $git -C $Target checkout --quiet $Commit
Need ($LASTEXITCODE -eq 0) 'Could not switch to the tested Fish revision.'

Step 'Downloading the 4-bit model (about 5 GB, once)'
$Py = Join-Path $PSScriptRoot '.venv-qwen\Scripts\python.exe'
Need (Test-Path $Py) 'Run install.bat first (it provides the downloader).'
& $Py -c "from huggingface_hub import snapshot_download as d; d('scarxity/fish-speech-s2-pro-nf4', local_dir=r'$Target\checkpoints\s2-pro-nf4')"
Need ($LASTEXITCODE -eq 0) 'Model download failed. Check your internet connection and retry; finished files are kept.'

Step 'Writing server settings'
# Load the model on the first request and unload after 5 idle minutes, so Qwen gets the GPU back.
@"
ENABLE_LAZY_LOAD=1
COMPILE=1
API_PORT=8880
"@ | Set-Content -Encoding ascii (Join-Path $Target '.env')

Step 'Building the Docker image (10-20 minutes the first time)'
Push-Location $Target
docker compose --profile server build
$built = $LASTEXITCODE
Pop-Location
Need ($built -eq 0) 'Docker build failed. Read the error above.'

Write-Host "`nFish S2 Pro is installed in $Target" -ForegroundColor Green
Write-Host 'In Voicebook Studio choose Speech engine: Fish S2 Pro, and a library narrator. The app starts the server itself.'
Write-Host 'stop-fish.bat stops the server and frees the GPU.'
