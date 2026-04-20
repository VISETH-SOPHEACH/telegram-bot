$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$BotScriptPath = Join-Path $ProjectRoot "bot.py"
$EscapedBotScriptPath = [regex]::Escape($BotScriptPath)

$ExistingBots = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match $EscapedBotScriptPath -and $_.ProcessId -ne $PID
}

if ($ExistingBots) {
    Write-Host "Bot is already running."
    exit 0
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    & $VenvPython $BotScriptPath
    exit $LASTEXITCODE
}

$PythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($PythonCommand) {
    & py -3 $BotScriptPath
    exit $LASTEXITCODE
}

$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($PythonCommand) {
    & python $BotScriptPath
    exit $LASTEXITCODE
}

throw "Python was not found. Install Python 3 and make sure 'py' or 'python' is available."
