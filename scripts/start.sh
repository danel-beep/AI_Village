#!/bin/sh
# AI Village launcher for macOS / Linux. install.sh copies this file to the Desktop as
# "AI Village.command". Each start: get uv (it brings Python), refresh the code from GitHub,
# open the app (aivillage/launcher.py). Key and runs live in ~/AIVillage.
# The code is the `stable` tag (CI moves it to main only after the tests pass), and the
# packages are the exact versions from uv.lock (`--frozen`), so a broken main never reaches players.
REPO="danel-beep/ai_village"
HOME_DIR="$HOME/AIVillage"
APP="$HOME_DIR/app"
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME_DIR/.venv"
mkdir -p "$HOME_DIR"
cd "$HOME_DIR" || exit 1

# macOS: the "AI Village" app (own window, updates itself) replaces this script. The first start
# after the update installs it, removes this icon and opens the app; offline, the old way goes on.
if [ "$(uname)" = Darwin ]; then
  curl -fsSL "https://raw.githubusercontent.com/$REPO/stable/scripts/install.sh" | AIV_FROM_START=1 sh && exit 0
fi

pause() { printf '\nНажмите Enter, чтобы закрыть окно.'; read -r _; }

if ! command -v uv >/dev/null 2>&1; then
  echo "Первый запуск: ставлю нужные программы (одна минута)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null || { echo "Не получилось скачать установщик. Проверьте интернет."; pause; exit 1; }
fi

echo "Проверяю обновления игры..."
# The previous version stays in app.prev: if a new one fails to start, the old one is run.
TMP="$HOME_DIR/.download"
rm -rf "$TMP" && mkdir -p "$TMP"
if curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/tags/stable" -o "$TMP/game.tgz" \
   && tar xzf "$TMP/game.tgz" -C "$TMP" 2>/dev/null; then
  SUM=$(cksum < "$TMP/game.tgz")
  if [ ! -d "$APP" ] || [ "$SUM" != "$(cat "$HOME_DIR/app.sum" 2>/dev/null)" ]; then
    rm -rf "$APP.prev"; [ -d "$APP" ] && mv "$APP" "$APP.prev"
    mv "$TMP"/*/ "$APP" && echo "$SUM" > "$HOME_DIR/app.sum"
  fi
elif [ ! -d "$APP" ]; then
  echo "Не получилось скачать игру. Проверьте интернет и запустите ещё раз."; rm -rf "$TMP"; pause; exit 1
else
  echo "Нет связи с GitHub, запускаю версию, что уже есть."
fi
rm -rf "$TMP"

play() {
  cd "$1" || return 1
  FROZEN=""; [ -f uv.lock ] && FROZEN="--frozen"
  uv run --quiet $FROZEN --python 3.12 --extra live python -m aivillage.launcher --home "$HOME_DIR"
}

STARTED=$(date +%s)
play "$APP" && exit 0
# A crash in the first minute means the new version does not start: fall back to the previous one.
if [ $(( $(date +%s) - STARTED )) -lt 60 ] && [ -d "$APP.prev" ]; then
  echo "Новая версия не запустилась, запускаю прошлую."
  play "$APP.prev" && exit 0
fi
pause
