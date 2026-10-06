"""Desktop launcher for non-technical users: starts the app and opens it in the browser.

Started by the desktop icon that scripts/install.sh / scripts/install.ps1 create
(they keep the code fresh from GitHub and install Python via uv). Can also be run directly:

    python -m aivillage.launcher [--home DIR]

Nothing is asked in the terminal: the browser opens on the start screen (viewer/setup.js), where the
village is set up with sliders and started with "Play"; keys and model live under "⚙️ Настройки"
(<home>/settings.json, aivillage/keys.py, never in the repo). Past runs and problem reports are on the
start screen too. Run logs go to <home>/runs, so code updates never touch them.
"""

from __future__ import annotations

import argparse
import os
import socket
import threading
import webbrowser
from pathlib import Path


def free_port(start: int = 8000) -> int:
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port")


def open_later(url: str, delay: float = 2.0) -> None:
    threading.Timer(delay, lambda: webbrowser.open(url)).start()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AI Village launcher: opens the app in the browser.")
    p.add_argument("--home", default=str(Path.home() / "AIVillage"), help="where keys, runs and reports are kept")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    a = p.parse_args(argv)
    home = Path(a.home)
    os.environ["AIVILLAGE_HOME"] = a.home  # the server and LLM clients read keys from there
    (home / "runs").mkdir(parents=True, exist_ok=True)

    from . import server

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    print("\n=== AI Village ===")
    print(f"Игра открывается в браузере: {url}")
    print("Там всё и настраивается: ползунки, ключи (⚙️ Настройки), кнопка «▶ Играть».")
    print("Не закрывайте это окно, пока играете. Выйти: закрыть окно или Ctrl+C.\n")
    if not a.no_browser:
        open_later(url)
    try:
        return server.main(["--setup", "--port", str(port), "--runs", str(home / "runs"),
                            "--reports", str(home / "reports"), "--reveal-reports"])
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
