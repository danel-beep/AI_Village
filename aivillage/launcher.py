"""Desktop launcher for non-technical users: a small Russian menu on top of the live server.

Started by the desktop icon that scripts/install.sh / scripts/install.ps1 create
(they keep the code fresh from GitHub and install Python via uv). Can also be run directly:

    python -m aivillage.launcher [--home DIR]

An OpenAI or OpenRouter key is asked once and stored in <home>/settings.json (aivillage/keys.py,
never in the repo); the viewer's settings panel edits the same file.
Run logs go to <home>/runs, so code updates never touch them.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from . import keys
from .llm import DEFAULT_MODEL

ROOT = Path(__file__).resolve().parent.parent
LLM_AGENTS = 5  # default answer to "how many villagers"
MAX_VILLAGERS = 60  # population.MAX_SIZE
LLM_DAYS = 3  # test runs: short and cheap
BOT_DAYS = 30


def load_key(home: Path) -> str | None:
    """Any usable key: OpenAI or OpenRouter (settings.json, old openrouter_key file, or env)."""
    return keys.get("openai_key", home) or keys.get("openrouter_key", home)


def save_key(home: Path, key: str) -> str:
    """Store a pasted key under the right provider (sk-or-... = OpenRouter, other sk-... = OpenAI)."""
    field = "openrouter_key" if key.startswith("sk-or-") else "openai_key"
    keys.save({field: key}, home)
    return field


def ask_key(home: Path) -> str | None:
    print("\nНужен ключ, через него жители-ИИ думают. Подходит любой из двух:")
    print("  • OpenAI (начинается с sk-): https://platform.openai.com/api-keys → «Create new secret key»")
    print("  • OpenRouter (начинается с sk-or-): https://openrouter.ai/keys → «Create Key»")
    print("Ключи можно поменять и в самой игре: кнопка «⚙️ Настройки» вверху слева.")
    key = input("Вставьте ключ (или просто Enter, чтобы отменить): ").strip()
    if not key:
        return None
    if not key.startswith("sk-"):
        print("Похоже, это не ключ (он начинается с sk-). Попробуйте ещё раз.")
        return None
    field = save_key(home, key)
    print(f"Ключ {'OpenAI' if field == 'openai_key' else 'OpenRouter'} сохранён на этом компьютере, "
          "больше спрашивать не буду.")
    return key


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


def live(home: Path, extra: list[str]) -> int:
    from . import server

    port = free_port()
    log = home / "runs" / f"{datetime.now():%Y-%m-%d_%H-%M}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{port}"
    print(f"\nДеревня запускается, браузер откроется сам: {url}")
    print("Кнопка «⚡ Режим бога» внизу справа. Не закрывайте это окно, пока смотрите.")
    print("Остановить: закрыть окно или нажать Ctrl+C.\n")
    open_later(url)
    try:
        return server.main(["--port", str(port), "--log", str(log), "--reports", str(home / "reports"),
                            "--reveal-reports", *extra])
    except KeyboardInterrupt:
        return 0


def watch_old(home: Path) -> int:
    runs = sorted((home / "runs").glob("*.jsonl"), reverse=True)[:9]
    if not runs:
        print("\nПрошлых прогонов пока нет.")
        return 0
    print()
    for i, r in enumerate(runs, 1):
        print(f"  {i} — {r.stem}")
    choice = input("Какой открыть? Цифра и Enter [1]: ").strip() or "1"
    if not choice.isdigit() or not 1 <= int(choice) <= len(runs):
        return 0
    log = runs[int(choice) - 1]
    out = log.with_suffix(".html")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_demo.py"), str(log), str(out)],
                   check=True, stdout=subprocess.DEVNULL)
    webbrowser.open(out.as_uri())
    print(f"Открыл в браузере: {out}")
    return 0


def ask_villagers(llm: bool) -> int:
    price = " Примерно $0.003 за жителя за игровой день." if llm else ""
    while True:
        ans = input(f"Сколько жителей? От 2 до {MAX_VILLAGERS}, Enter = {LLM_AGENTS}.{price} ").strip()
        if not ans:
            return LLM_AGENTS
        if ans.isdigit() and 2 <= int(ans) <= MAX_VILLAGERS:
            return int(ans)
        print(f"Нужно число от 2 до {MAX_VILLAGERS}.")


def ask_mode() -> str:
    from .modes import DEFAULT_MODE, MODES

    names = list(MODES)
    print("\nРежим экономики (правила мира, подсказка жителям та же):")
    for i, m in enumerate(names, 1):
        print(f"  {i} — {MODES[m]['title']}: {MODES[m]['about']}")
    choice = input(f"Введите цифру и нажмите Enter [{names.index(DEFAULT_MODE) + 1}]: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        return names[int(choice) - 1]
    return DEFAULT_MODE


def report_last(home: Path) -> int:
    """Same zip as the viewer's button, for when the browser is closed or a past run is open."""
    from . import reports
    runs = sorted((home / "runs").glob("*.jsonl"), reverse=True)
    if not runs:
        print("\nПрошлых прогонов пока нет.")
        return 0
    print(f"\nОтчёт о последнем прогоне ({runs[0].stem}).")
    note = input("Что было не так? Опишите одной строкой и нажмите Enter: ").strip()
    if not note:
        return 0
    path = reports.make_report(home / "reports", runs[0], note)
    reports.reveal(path)
    print(f"Готово: {path}")
    print("Папка с файлом открылась. Перетащите этот файл в чат проекта с Claude.")
    return 0


def menu(home: Path) -> int:
    print("\n=== AI Village ===")
    model = keys.get("model", home) or DEFAULT_MODEL
    print(f"  1 — Деревня с ИИ-жителями (модель {model}, стоит центы)")
    print("  2 — Деревня с ботами (бесплатно, без ключа)")
    print("  3 — Посмотреть прошлый прогон")
    print("  4 — Добавить или сменить ключ (OpenAI или OpenRouter)")
    print("  5 — Сообщить о проблеме в последнем прогоне")
    choice = input("Введите цифру и нажмите Enter [1]: ").strip() or "1"
    if choice == "1":
        if not (load_key(home) or ask_key(home)):
            return 0
        n = ask_villagers(llm=True)
        return live(home, ["--models", "default", "--agents", str(n), "--days", str(LLM_DAYS), "--mode", ask_mode()])
    if choice == "2":
        n = ask_villagers(llm=False)
        return live(home, ["--agents", str(n), "--days", str(BOT_DAYS), "--mode", ask_mode()])
    if choice == "3":
        return watch_old(home)
    if choice == "4":
        ask_key(home)
        return menu(home)
    if choice == "5":
        return report_last(home)
    print("Не понял выбор.")
    return menu(home)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AI Village launcher (menu in Russian).")
    p.add_argument("--home", default=str(Path.home() / "AIVillage"), help="where the key and runs are kept")
    a = p.parse_args(argv)
    try:
        os.environ["AIVILLAGE_HOME"] = a.home  # the server and LLM clients read keys from there
        return menu(Path(a.home))
    except (KeyboardInterrupt, EOFError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
