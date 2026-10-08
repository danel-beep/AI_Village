# One-time setup for Windows. In PowerShell:
#   irm https://raw.githubusercontent.com/danel-beep/ai_village/main/scripts/install.ps1 | iex
# Puts an "AI Village" shortcut on the Desktop and starts the game.
$HomeDir = Join-Path $env:USERPROFILE "AIVillage"
New-Item -ItemType Directory -Force $HomeDir | Out-Null
$Start = Join-Path $HomeDir "start.ps1"
$ProgressPreference = "SilentlyContinue"
Invoke-WebRequest "https://raw.githubusercontent.com/danel-beep/ai_village/stable/scripts/start.ps1" -OutFile $Start -UseBasicParsing
$Desk = [Environment]::GetFolderPath("Desktop")
$Link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $Desk "AI Village.lnk"))
$Link.TargetPath = "powershell.exe"
$Link.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Start`""
$Link.WorkingDirectory = $HomeDir
$Link.Save()
Write-Host "Готово: на рабочем столе появился значок «AI Village». Дальше запускайте игру им."
powershell -NoProfile -ExecutionPolicy Bypass -File $Start
