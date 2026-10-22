# Push the current app source to https://github.com/TinyAnts/voicebook-studio (branch main).
# Copies ONLY source/scripts/docs/tests. Never audiobooks, recordings, .venv-* folders,
# backups, logs or model files. Uses your own GitHub sign-in (gh auth login).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$Repo = 'https://github.com/TinyAnts/voicebook-studio.git'

function Find-Tool([string]$Name, [string[]]$Fallbacks) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($f in $Fallbacks) { if (Test-Path $f) { return $f } }
    return $null
}
$git = Find-Tool 'git' @("${env:ProgramFiles}\Git\cmd\git.exe")
if (-not $git) { throw 'Git is not installed. Install it from https://git-scm.com/downloads/win and run this again.' }
$gh = Find-Tool 'gh' @("${env:ProgramFiles}\GitHub CLI\gh.exe", "${env:LOCALAPPDATA}\Programs\GitHub CLI\gh.exe")
if ($gh) {
    & $gh auth status 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { & $gh auth login --hostname github.com --git-protocol https --web }
    & $gh auth setup-git | Out-Null
}

$Work = Join-Path $env:TEMP 'voicebook-studio-push'
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
& $git clone --quiet $Repo $Work
if ($LASTEXITCODE -ne 0) { throw 'Could not download the GitHub repository.' }

# Mirror source into the clone; excluded folders/files are neither copied nor deleted.
robocopy $PSScriptRoot $Work /MIR /NFL /NDL /NJH /NJS /NP `
    /XD .git audiobooks __pycache__ .gradio visual-review "_backup-*" ".venv-ui" ".venv-qwen" ".venv-qwenfast" ".venv-chatterbox" ".venv-kokoro" .cache `
    /XF *.log *.pyc *.key *.pem .env | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copy failed (robocopy code $LASTEXITCODE)." }

Set-Location $Work
& $git add -A
& $git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Host 'GitHub is already up to date.' -ForegroundColor Green; exit 0 }
Write-Host 'Files to upload:' -ForegroundColor Cyan
& $git status --short
$msg = Read-Host 'Commit message [Update Voicebook Studio]'
if ([string]::IsNullOrWhiteSpace($msg)) { $msg = 'Update Voicebook Studio' }
& $git commit --quiet -m $msg
& $git push origin HEAD:main
if ($LASTEXITCODE -ne 0) { throw 'Push failed. Nothing in your app folder was changed.' }
Write-Host "`nPushed to https://github.com/TinyAnts/voicebook-studio" -ForegroundColor Green
