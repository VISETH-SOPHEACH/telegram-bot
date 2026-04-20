$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$BotScriptPath = Join-Path $ProjectRoot "bot.py"
$EscapedBotScriptPath = [regex]::Escape($BotScriptPath)

$Targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "python.exe" -or $_.Name -eq "py.exe") -and $_.CommandLine -match $EscapedBotScriptPath
}

foreach ($Process in $Targets) {
    Stop-Process -Id $Process.ProcessId -Force
}

Start-Sleep -Seconds 2
wscript.exe .\start_bot_hidden.vbs

Write-Host "Bot restarted in the background."
