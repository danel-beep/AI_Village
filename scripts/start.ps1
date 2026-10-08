# AI Village launcher for Windows. install.ps1 puts a Desktop shortcut "AI Village" to this file.
# Each start: get uv (it brings Python), refresh the code from GitHub, open the Russian menu
# (aivillage/launcher.py). Key and runs live in %USERPROFILE%\AIVillage.
# The code is the `stable` tag (CI moves it to main only after the tests pass), and the
# packages are the exact versions from uv.lock (`--frozen`), so a broken main never reaches players.
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
# The previous version stays in app.prev: if a new one fails to start, the old one is run.
$Prev = "$App.prev"
$SumFile = Join-Path $HomeDir "app.sum"
$Tmp = Join-Path $HomeDir ".download"
Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Tmp | Out-Null
try {
    $Zip = Join-Path $Tmp "game.zip"
    Invoke-WebRequest "https://codeload.github.com/$Repo/zip/refs/tags/stable" -OutFile $Zip -UseBasicParsing
    $Sum = (Get-FileHash $Zip -Algorithm SHA256).Hash
    $OldSum = if (Test-Path $SumFile) { (Get-Content $SumFile -Raw).Trim() } else { "" }
    if (-not (Test-Path $App) -or $Sum -ne $OldSum) {
        Expand-Archive $Zip -DestinationPath $Tmp -Force
        $New = Get-ChildItem $Tmp -Directory | Select-Object -First 1
        Remove-Item -Recurse -Force $Prev -ErrorAction SilentlyContinue
        if (Test-Path $App) { Move-Item $App $Prev }
        Move-Item $New.FullName $App
        Set-Content $SumFile $Sum
    }
} catch {
    if (-not (Test-Path $App)) { Stop-WithPause "Не получилось скачать игру. Проверьте интернет и запустите ещё раз." }
    Write-Host "Нет связи с GitHub, запускаю версию, что уже есть."
}
Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue

function Start-Game($Dir) {
    Set-Location $Dir
    $Frozen = @(); if (Test-Path "uv.lock") { $Frozen = @("--frozen") }
    uv run --quiet @Frozen --python 3.12 --extra live python -m aivillage.launcher --home $HomeDir
}

$Started = Get-Date
Start-Game $App  # called as a statement so the game prints to the window; result in $LASTEXITCODE
if ($LASTEXITCODE -eq 0) { exit 0 }
# A crash in the first minute means the new version does not start: fall back to the previous one.
if (((Get-Date) - $Started).TotalSeconds -lt 60 -and (Test-Path $Prev)) {
    Write-Host "Новая версия не запустилась, запускаю прошлую."
    Start-Game $Prev
    if ($LASTEXITCODE -eq 0) { exit 0 }
}
Read-Host "Нажмите Enter, чтобы закрыть окно"
