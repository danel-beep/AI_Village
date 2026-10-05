#!/bin/sh
# AI Village launcher for macOS / Linux. install.sh copies this file to the Desktop as
# "AI Village.command". Each start: get uv (it brings Python), refresh the code from GitHub,
# open the Russian menu (aivillage/launcher.py). Key and runs live in ~/AIVillage.
REPO="danel-beep/ai_village"
HOME_DIR="$HOME/AIVillage"
APP="$HOME_DIR/app"
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME_DIR/.venv"
mkdir -p "$HOME_DIR"
cd "$HOME_DIR" || exit 1

pause() { printf '\nНажмите Enter, чтобы закрыть окно.'; read -r _; }

if ! command -v uv >/dev/null 2>&1; then
  echo "Первый запуск: ставлю нужные программы (одна минута)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null || { echo "Не получилось скачать установщик. Проверьте интернет."; pause; exit 1; }
fi

echo "Проверяю обновления игры..."
TMP="$HOME_DIR/.download"
rm -rf "$TMP" && mkdir -p "$TMP"
if curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/main" | tar xz -C "$TMP" 2>/dev/null; then
  rm -rf "$APP.old"; [ -d "$APP" ] && mv "$APP" "$APP.old"
  mv "$TMP"/*/ "$APP" && rm -rf "$APP.old"
elif [ ! -d "$APP" ]; then
  echo "Не получилось скачать игру. Проверьте интернет и запустите ещё раз."; pause; exit 1
else
  echo "Нет связи с GitHub, запускаю версию, что уже есть."
fi
rm -rf "$TMP"

cd "$APP" || exit 1
uv run --quiet --python 3.12 --extra live python -m aivillage.launcher --home "$HOME_DIR" || pause
