Set shell = CreateObject("WScript.Shell")
scriptPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\run_bot.ps1"
shell.Run "powershell.exe -ExecutionPolicy Bypass -File """ & scriptPath & """", 0, False
