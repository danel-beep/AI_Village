#!/bin/sh
# One-time setup for macOS / Linux. In Terminal:
#   curl -fsSL https://raw.githubusercontent.com/danel-beep/ai_village/main/scripts/install.sh | sh
# macOS: installs the "AI Village" app (own window, updates itself; desktop/, release `desktop-latest`)
# into Applications, puts it on the Desktop and in the Dock, and opens it. Files fetched with curl are
# not quarantined, so macOS opens the unsigned app without the "unidentified developer" block.
# Linux, or macOS when the app cannot be fetched: the Desktop icon that runs scripts/start.sh.
set -e
REPO="danel-beep/ai_village"
HOME_DIR="$HOME/AIVillage"
mkdir -p "$HOME_DIR"

install_app() {
  case "$(uname -m)" in arm64) ARCH=arm64 ;; *) ARCH=x86_64 ;; esac
  TMP=$(mktemp -d) || return 1
  echo "Скачиваю приложение AI Village..."
  curl -fsSL "https://github.com/$REPO/releases/download/desktop-latest/AI-Village-mac-$ARCH.zip" -o "$TMP/app.zip" \
    && ditto -x -k "$TMP/app.zip" "$TMP" && [ -d "$TMP/AI Village.app" ] || { rm -rf "$TMP"; return 1; }
  DEST="/Applications"
  [ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
  APP="$DEST/AI Village.app"
  rm -rf "$APP" && mv "$TMP/AI Village.app" "$APP" || { rm -rf "$TMP"; return 1; }
  rm -rf "$TMP"
  # the old icon ran the game in Terminal and the browser; the app replaces it
  rm -f "$HOME/Desktop/AI Village.command" "$HOME_DIR/AI Village.command"
  [ -d "$HOME/Desktop" ] && ln -sfn "$APP" "$HOME/Desktop/AI Village"
  if ! defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "AI%20Village.app\|AI Village.app"; then
    defaults write com.apple.dock persistent-apps -array-add \
      "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>" \
      && killall Dock 2>/dev/null || true
  fi
  echo "Готово: приложение «AI Village» есть в Программах, на рабочем столе и в Доке. Это окно можно закрыть."
  open "$APP"
}

if [ "$(uname)" = Darwin ] && install_app; then
  exit 0
fi
# start.sh calls this script to switch to the app; if that failed it just carries on itself
[ -n "$AIV_FROM_START" ] && exit 1

curl -fsSL https://raw.githubusercontent.com/danel-beep/ai_village/stable/scripts/start.sh -o "$HOME_DIR/start.sh"
chmod +x "$HOME_DIR/start.sh"
DESK="$HOME/Desktop"
[ -d "$DESK" ] || DESK="$HOME_DIR"
cp "$HOME_DIR/start.sh" "$DESK/AI Village.command"
chmod +x "$DESK/AI Village.command"
echo "Готово: на рабочем столе появился значок «AI Village». Дальше запускайте игру им."
exec "$HOME_DIR/start.sh" </dev/tty
