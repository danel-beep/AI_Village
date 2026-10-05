# AI Village launcher for Windows. install.ps1 puts a Desktop shortcut "AI Village" to this file.
# Each start: get uv (it brings Python), refresh the code from GitHub, open the Russian menu
# (aivillage/launcher.py). Key and runs live in %USERPROFILE%\AIVillage.
$Repo = "danel-beep/ai_village"
$HomeDir = Join-Path $env:USERPROFILE "AIVillage"
$App = Join-Path $HomeDir "app"
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $HomeDir ".venv"
$env:PYTHONUTF8 = "1"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
New-Item -ItemType Directory -Force $HomeDir | Out-Null

function Stop-WithPause($msg) { Write-Host $msg; Read-Host "Нажмите Enter, чтобы закрыть окно"; exit 1 }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Первый запуск: ставлю нужные программы (одна минута)..."
    try { powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null }
    catch { Stop-WithPause "Не получилось скачать установщик. Проверьте интернет." }
}

Write-Host "Проверяю обновления игры..."
$Tmp = Join-Path $HomeDir ".download"
Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Tmp | Out-Null
try {
    $Zip = Join-Path $Tmp "game.zip"
    Invoke-WebRequest "https://codeload.github.com/$Repo/zip/refs/heads/main" -OutFile $Zip -UseBasicParsing
    Expand-Archive $Zip -DestinationPath $Tmp -Force
    $New = Get-ChildItem $Tmp -Directory | Select-Object -First 1
    Remove-Item -Recurse -Force $App -ErrorAction SilentlyContinue
    Move-Item $New.FullName $App
} catch {
    if (-not (Test-Path $App)) { Stop-WithPause "Не получилось скачать игру. Проверьте интернет и запустите ещё раз." }
    Write-Host "Нет связи с GitHub, запускаю версию, что уже есть."
}
Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue

Set-Location $App
uv run --quiet --python 3.12 --extra live python -m aivillage.launcher --home $HomeDir
if ($LASTEXITCODE -ne 0) { Read-Host "Нажмите Enter, чтобы закрыть окно" }
