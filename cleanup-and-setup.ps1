# One-click: free space on C:, move AI model downloads to D:, then install Fish S2 Pro on D:.
# Safe: deletes only Recycle Bin, temp files, Python download caches and the half-finished Fish
# download. Your app, audiobooks, Python environments and documents are not touched.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$Drive = 'D:'
function FreeGB($d) { [math]::Round((New-Object System.IO.DriveInfo($d)).AvailableFreeSpace / 1GB, 1) }
function Say($t, $c = 'Cyan') { Write-Host "`n$t" -ForegroundColor $c }

Say "C: free before: $(FreeGB 'C:') GB"

# 0. The app must be closed (it holds the model files open).
if (Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue) {
    Say 'Voicebook Studio is still running. Close its black terminal window, then run this again.' 'Red'
    Read-Host 'Press Enter to exit'; exit 1
}

# 1. Safe clean-up
Say 'Step 1/4 - Emptying Recycle Bin and temp files...'
Clear-RecycleBin -Force -ErrorAction SilentlyContinue
Get-ChildItem $env:TEMP -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
foreach ($venv in '.venv-qwen', '.venv-qwenfast', '.venv-ui') {
    $py = Join-Path $PSScriptRoot "$venv\Scripts\python.exe"
    if (Test-Path $py) { & $py -m pip cache purge 2>$null | Out-Null }
}
$half = Join-Path $env:LOCALAPPDATA 'VoicebookStudio'
if (Test-Path $half) { Remove-Item $half -Recurse -Force -ErrorAction SilentlyContinue }
Say "C: free now: $(FreeGB 'C:') GB" 'Green'

# 2. Move downloaded AI models (Hugging Face cache) to D:
Say 'Step 2/4 - Moving downloaded AI models to D:\hf-cache ...'
$src = Join-Path $env:USERPROFILE '.cache\huggingface'
$dst = "$Drive\hf-cache"
if (Test-Path $src) {
    robocopy $src $dst /E /MOVE /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Say 'Some model files could not be moved (in use?). They stay on C: and still work.' 'Yellow' }
} else { New-Item -ItemType Directory -Force -Path $dst | Out-Null }
setx HF_HOME $dst | Out-Null
$env:HF_HOME = $dst
Say "Models now live in $dst. C: free now: $(FreeGB 'C:') GB" 'Green'

# 3. Docker must keep its data on D: too, or the Fish image (10-15 GB) fills C: again.
Say 'Step 3/4 - Checking where Docker keeps its data...'
$dockerOnC = (Test-Path "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx") -or
             (Test-Path "$env:LOCALAPPDATA\Docker\wsl\data\ext4.vhdx")
if ($dockerOnC -and (FreeGB 'C:') -ge 40) {
    Say "Docker keeps its data on C:, but C: has $(FreeGB 'C:') GB free - enough. Continuing." 'Green'
    $dockerOnC = $false
}
if ($dockerOnC) {
    Say 'Docker still stores its data on C:. Do this once, then run this file again:' 'Yellow'
    Write-Host '  1. Open Docker Desktop'
    Write-Host '  2. Click the gear (Settings) > Resources > Advanced'
    Write-Host '  3. "Disk image location" > Browse > choose D:\Docker (make the folder) > Apply & restart'
    Write-Host '  4. Wait until Docker says "Engine running", then double-click cleanup-and-setup.bat again'
    Read-Host "`nPress Enter to exit"; exit 0
}

# 4. Install Fish S2 Pro on D:
Say 'Step 4/4 - Installing Fish S2 Pro to D:\VoicebookFish (20-40 minutes)...'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'install-fish.ps1') "$Drive\VoicebookFish"
if ($LASTEXITCODE -ne 0) { Say 'Fish install stopped - read the message above. Everything else is done.' 'Yellow' }
else { Say 'All done.' 'Green' }

Say "C: free at the end: $(FreeGB 'C:') GB   |   D: free: $(FreeGB 'D:') GB"
Write-Host 'Start the app again with start.bat (use a NEW window so it sees the model folder on D:).'
Read-Host "`nPress Enter to close"
