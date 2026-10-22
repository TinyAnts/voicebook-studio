# Read-only C: drive report. Deletes NOTHING. Shows where space went, so you can decide.
# Run:  right-click > Run with PowerShell   (or: powershell -ExecutionPolicy Bypass -File disk-report.ps1)
$ErrorActionPreference = 'SilentlyContinue'
$out = Join-Path $PSScriptRoot 'disk-report.txt'

function SizeGB([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    $item = Get-Item -LiteralPath $path -Force
    if (-not $item.PSIsContainer) { return [math]::Round($item.Length / 1GB, 2) }
    $sum = (Get-ChildItem -LiteralPath $path -Recurse -Force -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    return [math]::Round(($sum / 1GB), 2)
}

Write-Host 'Measuring folders on C: - this can take 5-15 minutes. Nothing is deleted.' -ForegroundColor Cyan
$lines = @()
$c = Get-PSDrive C
$lines += "C: free $([math]::Round($c.Free/1GB,1)) GB of $([math]::Round(($c.Used+$c.Free)/1GB)) GB   ($(Get-Date))"
$lines += ''
$lines += '== Known space users (GB) =='
$known = [ordered]@{
    'Hugging Face model cache'          = "$env:USERPROFILE\.cache\huggingface"
    'Other .cache (torch, uv, ...)'     = "$env:USERPROFILE\.cache"
    'pip download cache'                = "$env:LOCALAPPDATA\pip\Cache"
    'uv cache'                          = "$env:LOCALAPPDATA\uv\cache"
    'npm cache'                         = "$env:LOCALAPPDATA\npm-cache"
    'conda / miniconda'                 = "$env:USERPROFILE\miniconda3"
    'anaconda'                          = "$env:USERPROFILE\anaconda3"
    'Docker Desktop data (WSL disk)'    = "$env:LOCALAPPDATA\Docker"
    'WSL distributions'                 = "$env:LOCALAPPDATA\Packages"
    'Temp (user)'                       = "$env:TEMP"
    'Temp (Windows)'                    = "C:\Windows\Temp"
    'Downloads'                         = "$env:USERPROFILE\Downloads"
    'OneDrive (local copies)'           = "$env:OneDrive"
    'Voicebook Fish half-install'       = "$env:LOCALAPPDATA\VoicebookStudio"
    'Windows.old (previous Windows)'    = "C:\Windows.old"
    'hiberfil.sys (hibernation)'        = "C:\hiberfil.sys"
    'pagefile.sys'                      = "C:\pagefile.sys"
    'Recycle Bin'                       = 'C:\$Recycle.Bin'
}
foreach ($k in $known.Keys) {
    $g = SizeGB $known[$k]
    if ($g -ne $null) { $lines += ('{0,8:N2}  {1}  ({2})' -f $g, $k, $known[$k]) }
}

$lines += ''
$lines += '== Python virtual environments under your user folder (repeat installs show up here) =='
Get-ChildItem -Path $env:USERPROFILE -Recurse -File -Force -Filter 'pyvenv.cfg' -ErrorAction SilentlyContinue |
    ForEach-Object { $_.Directory.FullName } | Sort-Object -Unique |
    ForEach-Object { $lines += ('{0,8:N2}  {1}' -f (SizeGB $_), $_) }

$lines += ''
$lines += '== Largest folders in your user profile (top 25, GB) =='
Get-ChildItem -Path $env:USERPROFILE -Directory -Force | ForEach-Object {
    Get-ChildItem -LiteralPath $_.FullName -Directory -Force -ErrorAction SilentlyContinue
} | ForEach-Object { [pscustomobject]@{ GB = SizeGB $_.FullName; Path = $_.FullName } } |
    Sort-Object GB -Descending | Select-Object -First 25 |
    ForEach-Object { $lines += ('{0,8:N2}  {1}' -f $_.GB, $_.Path) }

$lines += ''
$lines += '== Largest top-level folders on C: (GB) =='
Get-ChildItem -Path 'C:\' -Directory -Force | Where-Object { $_.Name -notin @('Windows','Users','$Recycle.Bin') } |
    ForEach-Object { [pscustomobject]@{ GB = SizeGB $_.FullName; Path = $_.FullName } } |
    Sort-Object GB -Descending | Select-Object -First 12 |
    ForEach-Object { $lines += ('{0,8:N2}  {1}' -f $_.GB, $_.Path) }

$lines | Tee-Object -FilePath $out
Write-Host "`nSaved to $out - nothing was deleted." -ForegroundColor Green
Read-Host 'Press Enter to close'
