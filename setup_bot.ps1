$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "Checking Python..."
$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PythonLauncher) {
    $BootstrapExe = "py"
    $BootstrapArgs = @("-3")
} else {
    $PythonLauncher = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonLauncher) {
        throw "Python 3 was not found. Install Python 3 first."
    }
    $BootstrapExe = "python"
    $BootstrapArgs = @()
}

$VenvPath = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment in .venv..."
    & $BootstrapExe @BootstrapArgs -m venv $VenvPath
}

Write-Host "Installing or updating Python packages..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt

Write-Host "Registering Windows auto-start task..."
& (Join-Path $ProjectRoot "install_autostart.ps1")

Write-Host ""
Write-Host "Setup complete."
Write-Host "The bot will use the .venv environment automatically."
Write-Host "You can test the bot with: powershell -ExecutionPolicy Bypass -File .\run_bot.ps1"
