# Gives Docker (WSL) more RAM + a swap file on D:, so Fish S2 Pro can load without being killed.
# Writes %USERPROFILE%\.wslconfig (backs up an existing one), then restarts WSL and Docker Desktop.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
function Say($t, $c = 'Cyan') { Write-Host "`n$t" -ForegroundColor $c }
$log = Join-Path $PSScriptRoot 'fish-log2.txt'

# 1. Confirm the cause (kernel out-of-memory kills) before restarting clears it.
Say 'Step 1/4 - Checking for out-of-memory kills...'
$oom = docker run --rm --privileged alpine sh -c "dmesg | grep -iE 'out of memory|oom-kill|killed process' | tail -n 20" 2>&1
"==== OOM lines $(Get-Date)" | Set-Content $log
$oom | Add-Content $log
if ($oom -match 'Killed process|Out of memory|oom') { Say 'Confirmed: Linux killed the Fish server for running out of memory.' 'Yellow' }
else { Say 'No out-of-memory line found (it may have been cleared). Applying the fix anyway.' 'Yellow' }

# 2. Write .wslconfig: 22 GB RAM for Docker/WSL (Windows keeps ~10 GB) + 16 GB swap on D:.
Say 'Step 2/4 - Giving Docker 22 GB RAM + 16 GB swap on D: ...'
$cfg = Join-Path $env:USERPROFILE '.wslconfig'
if (Test-Path $cfg) { Copy-Item $cfg "$cfg.bak" -Force; Say "Old settings saved to $cfg.bak" }
New-Item -ItemType Directory -Force -Path 'D:\wsl' | Out-Null
@"
[wsl2]
memory=22GB
swap=16GB
swapFile=D:\\wsl\\swap.vhdx

[experimental]
autoMemoryReclaim=gradual
"@ | Set-Content -Path $cfg -Encoding ascii
Get-Content $cfg | Add-Content $log

# 3. Restart WSL + Docker Desktop so the new limit applies.
Say 'Step 3/4 - Restarting Docker (about 1-2 minutes)...'
$fish = if (Test-Path 'fish-location.txt') { (Get-Content 'fish-location.txt' -Raw).Trim() } else { '' }
if ($fish -and (Test-Path (Join-Path $fish 'compose.yml'))) {
    Push-Location $fish; docker compose --profile server down 2>&1 | Out-Null; Pop-Location
}
Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 3
wsl --shutdown
Start-Sleep 5
$exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
if (Test-Path $exe) { Start-Process $exe } else { Say 'Start Docker Desktop yourself now.' 'Yellow' }
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep 5
    docker info --format '{{.MemTotal}}' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
}

# 4. Report.
if ($ok) {
    $gb = [math]::Round([double](docker info --format '{{.MemTotal}}') / 1GB, 1)
    "Docker RAM now: $gb GB" | Add-Content $log
    if ($gb -ge 20) { Say "Step 4/4 - Done. Docker now has $gb GB RAM (was 15.5) + 16 GB swap." 'Green' }
    else { Say "Step 4/4 - Docker shows $gb GB. Restart the PC once so the new limit applies." 'Yellow' }
} else {
    Say 'Step 4/4 - Docker did not come back yet. Open Docker Desktop, wait for "Engine running".' 'Yellow'
}
Write-Host 'Now in the app: Speech engine = Fish, pick a library narrator, try again (first load ~3-5 min).'
Read-Host "`nPress Enter to close"
