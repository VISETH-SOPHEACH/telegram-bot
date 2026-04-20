$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$ExistingBots = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*bot.py*" -and $_.ProcessId -ne $PID
}

if ($ExistingBots) {
    Write-Host "Bot is already running."
    exit 0
}

$PythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($PythonCommand) {
    & py -3 bot.py
    exit $LASTEXITCODE
}

$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($PythonCommand) {
    & python bot.py
    exit $LASTEXITCODE
}

throw "Python was not found. Install Python 3 and make sure 'py' or 'python' is available."
