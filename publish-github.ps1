# One-time GitHub publication. Creates a private repo (default: voicebook-studio).
# Requires the user's explicit GitHub authorization via gh auth login.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Resolve-Tool([string]$ToolName, [string[]]$Fallbacks) {
    $cmd = Get-Command $ToolName -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($candidate in $Fallbacks) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

$git = Resolve-Tool 'git' @( "${env:ProgramFiles}\Git\cmd\git.exe", "${env:ProgramFiles}\Git\bin\git.exe" )
if (-not $git) {
    Write-Host 'Git is required. Installing with winget...' -ForegroundColor Yellow
    winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
    $git = Resolve-Tool 'git' @( "${env:ProgramFiles}\Git\cmd\git.exe", "${env:ProgramFiles}\Git\bin\git.exe" )
}
if (-not $git) { throw 'Could not locate Git. Reopen PowerShell or install https://git-scm.com/downloads/win' }

$gh = Resolve-Tool 'gh' @( "${env:ProgramFiles}\GitHub CLI\gh.exe", "${env:LOCALAPPDATA}\Programs\GitHub CLI\gh.exe" )
if (-not $gh) {
    Write-Host 'Installing GitHub CLI with winget...' -ForegroundColor Yellow
    winget install --id GitHub.cli -e --accept-package-agreements --accept-source-agreements
    $gh = Resolve-Tool 'gh' @( "${env:ProgramFiles}\GitHub CLI\gh.exe", "${env:LOCALAPPDATA}\Programs\GitHub CLI\gh.exe" )
}
if (-not $gh) { throw 'Could not locate GitHub CLI. Reopen PowerShell or install https://cli.github.com/' }

& $gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "\nSign into GitHub once in your browser (you will approve access):" -ForegroundColor Cyan
    & $gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { throw 'GitHub login was not completed.' }
}
& $gh auth setup-git
if ($LASTEXITCODE -ne 0) { throw 'Could not set up GitHub Git authentication.' }

$name = Read-Host 'Name your PRIVATE repo [voicebook-studio]'
if ([string]::IsNullOrWhiteSpace($name)) { $name = 'voicebook-studio' }
if ($name -notmatch '^[a-zA-Z0-9_.-]+$') { throw 'Use only letters, numbers, hyphens, underscores or periods in the repo name.' }

$localGit = Test-Path '.git'
if (-not $localGit) {
    & $git init -b main
    if ($LASTEXITCODE -ne 0) { throw 'git init failed.' }
}
$existingName = & $git config --get user.name
if (-not $existingName) {
    $login = (& $gh api user --jq .login).Trim()
    & $git config user.name $login
}
$existingEmail = & $git config --get user.email
if (-not $existingEmail) {
    $login = (& $gh api user --jq .login).Trim()
    $accountID = (& $gh api user --jq .id).Trim()
    & $git config user.email ("{0}+{1}@users.noreply.github.com" -f $accountID,$login)
}
& $git add -A
if ($LASTEXITCODE -ne 0) { throw 'git add failed.' }
& $git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    & $git commit -m 'Build Voicebook Studio audiobook converter'
    if ($LASTEXITCODE -ne 0) { throw 'git commit failed.' }
}

# Safeguard: avoid modifying an existing, potentially unrelated GitHub repo.
& $git remote get-url origin 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Repository already configured; pushing changes to its existing origin...' -ForegroundColor Cyan
    & $git push -u origin HEAD
} else {
    $login = (& $gh api user --jq .login).Trim()
    & $gh repo view "$login/$name" --json name 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        throw "A repo named $login/$name already exists. No existing repository was changed. Rerun and choose a different name."
    }
    Write-Host 'Creating a PRIVATE GitHub repository and uploading the application...' -ForegroundColor Cyan
    & $gh repo create $name --private --source . --remote origin --push --description 'Offline PDF and EPUB to AI audiobooks (Qwen3-TTS, Chatterbox, Kokoro)'
}
if ($LASTEXITCODE -ne 0) { throw 'Publishing failed. The local files are still safe.' }
Write-Host "\nAll done. Repo URL:" -ForegroundColor Green
& $gh repo view --json url --jq .url
