#!/bin/sh
# One-time setup for macOS / Linux. In Terminal:
#   curl -fsSL https://raw.githubusercontent.com/danel-beep/ai_village/main/scripts/install.sh | sh
# Puts "AI Village.command" on the Desktop and starts the game.
set -e
HOME_DIR="$HOME/AIVillage"
mkdir -p "$HOME_DIR"
curl -fsSL https://raw.githubusercontent.com/danel-beep/ai_village/main/scripts/start.sh -o "$HOME_DIR/start.sh"
chmod +x "$HOME_DIR/start.sh"
DESK="$HOME/Desktop"
[ -d "$DESK" ] || DESK="$HOME_DIR"
cp "$HOME_DIR/start.sh" "$DESK/AI Village.command"
chmod +x "$DESK/AI Village.command"
echo "Готово: на рабочем столе появился значок «AI Village». Дальше запускайте игру им."
exec "$HOME_DIR/start.sh" </dev/tty
