$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "Checking Python..."
$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PythonLauncher) {
    $PythonExe = "py"
    $PythonArgs = @("-3")
} else {
    $PythonLauncher = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonLauncher) {
        throw "Python 3 was not found. Install Python 3 first."
    }
    $PythonExe = "python"
    $PythonArgs = @()
}

Write-Host "Installing or updating Python packages..."
& $PythonExe @PythonArgs -m pip install --upgrade pip
& $PythonExe @PythonArgs -m pip install -r requirements.txt

Write-Host "Checking ffmpeg..."
$Ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $Ffmpeg) {
    throw "ffmpeg was not found in PATH. Install ffmpeg before using MP3 downloads."
}

Write-Host "Registering Windows auto-start task..."
& (Join-Path $ProjectRoot "install_autostart.ps1")

Write-Host ""
Write-Host "Setup complete."
Write-Host "Next, rotate the Telegram bot token in BotFather and update .env if needed."
Write-Host "You can test the bot with: powershell -ExecutionPolicy Bypass -File .\run_bot.ps1"
