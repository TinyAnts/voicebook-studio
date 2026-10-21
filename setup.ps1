param(
    [ValidateSet('qwen','chatterbox','kokoro','all')]
    [string]$Model = 'qwen'
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Run-Checked([string]$Exe, [string[]]$Arguments) {
    Write-Host ("> " + $Exe + " " + ($Arguments -join " ")) -ForegroundColor DarkGray
    & $Exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Exe" }
}

try {
    & py -3.11 --version | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required. Install Python 3.11 and its Windows Python Launcher first.' }
} catch { throw 'Install Python 3.11 (with py launcher) first: https://www.python.org/downloads/' }

function Make-Env([string]$Name) {
    $Python = Join-Path $PSScriptRoot ('.venv-' + $Name + '\Scripts\python.exe')
    if (-not (Test-Path $Python)) { Run-Checked 'py' @('-3.11','-m','venv',('.venv-' + $Name)) }
    Run-Checked $Python @('-m','pip','install','--upgrade','pip','wheel','setuptools')
    return $Python
}

Write-Host 'Installing Voicebook Studio user interface...' -ForegroundColor Cyan
$Ui = Make-Env 'ui'
Run-Checked $Ui @('-m','pip','install','-r','requirements-ui.txt')

$Models = if ($Model -eq 'all') { @('qwen','chatterbox','kokoro') } else { @($Model) }
foreach ($Choice in $Models) {
    Write-Host "Installing $Choice model backend in its own Python environment..." -ForegroundColor Cyan
    $Py = Make-Env $Choice
    if ($Choice -eq 'chatterbox') {
        # Chatterbox pins PyTorch 2.6 and Transformers 5.2; isolate it from Qwen.
        Run-Checked $Py @('-m','pip','install','torch==2.6.0','torchaudio==2.6.0','--index-url','https://download.pytorch.org/whl/cu124')
        Run-Checked $Py @('-m','pip','install','chatterbox-tts==0.1.7','soundfile')
    } elseif ($Choice -eq 'qwen') {
        Run-Checked $Py @('-m','pip','install','torch==2.6.0','torchaudio==2.6.0','--index-url','https://download.pytorch.org/whl/cu124')
        Run-Checked $Py @('-m','pip','install','qwen-tts==0.1.1','soundfile')
    } elseif ($Choice -eq 'kokoro') {
        Run-Checked $Py @('-m','pip','install','torch==2.6.0','torchaudio==2.6.0','--index-url','https://download.pytorch.org/whl/cu124')
        Run-Checked $Py @('-m','pip','install','kokoro>=0.9.4','soundfile')
        Write-Warning 'Kokoro also requires espeak-ng on Windows. See README.'
    }
    Run-Checked $Py @('-c',"import torch; print('CUDA available:', torch.cuda.is_available())")
}
Write-Host "`nInstallation completed! Double-click start.bat to launch the app." -ForegroundColor Green
