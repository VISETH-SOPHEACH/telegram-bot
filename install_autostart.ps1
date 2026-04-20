$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "TelegramVideoDownloaderBot"
$LauncherPath = Join-Path $ProjectRoot "start_bot_hidden.vbs"
$StartupFolder = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$StartupScriptPath = Join-Path $StartupFolder "TelegramVideoDownloaderBot.vbs"

if (-not (Test-Path $LauncherPath)) {
    throw "Launcher file not found: $LauncherPath"
}

function Install-StartupFolderLauncher {
    if (-not (Test-Path $StartupFolder)) {
        New-Item -ItemType Directory -Path $StartupFolder -Force | Out-Null
    }

    $StartupScript = @"
Set shell = CreateObject("WScript.Shell")
shell.Run "powershell.exe -ExecutionPolicy Bypass -File ""$ProjectRoot\run_bot.ps1""", 0, False
"@

    Set-Content -LiteralPath $StartupScriptPath -Value $StartupScript -Encoding ASCII
    Write-Host "Autostart enabled using Startup folder:"
    Write-Host $StartupScriptPath
}

try {
    $Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$LauncherPath`""
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "Starts the Telegram downloader bot in the background at user logon." `
        -Force | Out-Null

    Write-Host "Scheduled task '$TaskName' created or updated."
} catch {
    Write-Warning "Scheduled Task registration failed. Falling back to Startup folder launcher."
    Install-StartupFolderLauncher
}
