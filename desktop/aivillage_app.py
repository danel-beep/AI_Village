"""AI Village desktop app: its own window and icon, no terminal and no browser.

Built into "AI Village.app" by .github/workflows/desktop.yml (pywebview + PyInstaller) and published
as the GitHub release `desktop-latest`; scripts/install.sh puts it into Applications. The app is only
a shell around the game, which is the `stable` tag (CI moves it to main once the tests pass).

Each start:
  1. a loading screen while the code is checked;
  2. a newer `stable` is downloaded into ~/AIVillage/app, the previous version is kept in app.prev;
  3. the game server (`python -m aivillage.launcher`) runs under uv with the packages pinned in uv.lock;
  4. the window opens the game as soon as the server answers;
  5. a just-updated version that dies before answering is rolled back to app.prev and skipped
     until `stable` moves again.
While the game is open, a newer `stable` is fetched in the background into app.next (used at the
next start), and a newer release of the app itself replaces it when the window is closed.
Keys, settings and runs stay in ~/AIVillage, as with the old launcher (scripts/start.sh).

Only the standard library here (pywebview is imported by `main`): the game code is downloaded
separately and may be newer or older than this file, so the only contract with it is the launcher
printing its address (http://127.0.0.1:<port>), which tests/test_desktop_app.py checks.

    python desktop/aivillage_app.py            # the window
    python desktop/aivillage_app.py --check    # no window: download, start, wait for an answer, stop
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
from pathlib import Path

REPO = "danel-beep/ai_village"
TAG = "stable"
RELEASE = f"https://github.com/{REPO}/releases/download/desktop-latest"
URL_RE = re.compile(r"http://127\.0\.0\.1:\d+")
VERSION_FILE = ".aiv-version"  # the commit a code folder was downloaded from
PREFETCH_EVERY = 30 * 60
READY_TIMEOUT = 15 * 60  # the first start installs Python and the packages


def build_info() -> dict:
    """{"version": <release number>, "commit": ...} written by CI next to this file; 0 when run from source."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        return json.loads((base / "build_info.json").read_text())
    except (OSError, ValueError):
        return {"version": 0}


class Home:
    """~/AIVillage: keys, runs and the game code folders."""

    def __init__(self, root: Path):
        self.root = root
        self.app = root / "app"
        self.prev = root / "app.prev"
        self.next = root / "app.next"
        self.bad = root / "app.bad"
        self.logs = root / "logs"

    def bad_version(self) -> str | None:
        try:
            return self.bad.read_text().strip() or None
        except OSError:
            return None


def version_of(folder: Path) -> str | None:
    try:
        return (folder / VERSION_FILE).read_text().strip() or None
    except OSError:
        return None


def http_get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "AIVillage-app"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def stable_commit(get=http_get) -> str | None:
    """The commit `stable` points at, or None when GitHub cannot be reached.

    Read from git's own ref list (no API rate limit); an annotated tag lists the commit as `^{}`."""
    try:
        refs = get(f"https://github.com/{REPO}.git/info/refs?service=git-upload-pack").decode("utf-8", "replace")
    except Exception:
        return None
    found = dict((ref, sha) for sha, ref in re.findall(rf"([0-9a-f]{{40}}) (refs/tags/{TAG}(?:\^{{}})?)\b", refs))
    return found.get(f"refs/tags/{TAG}^{{}}") or found.get(f"refs/tags/{TAG}")


def download_code(sha: str, dest: Path, get=http_get) -> None:
    """Unpack commit `sha` of the repo into `dest` (which must not exist)."""
    data = get(f"https://codeload.github.com/{REPO}/tar.gz/{sha}", timeout=300)
    unpack = dest.with_name(dest.name + ".unpack")
    shutil.rmtree(unpack, ignore_errors=True)
    unpack.mkdir(parents=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(unpack, filter="data")
        (top,) = [p for p in unpack.iterdir() if p.is_dir()]
        (top / VERSION_FILE).write_text(sha)
        os.replace(top, dest)
    finally:
        shutil.rmtree(unpack, ignore_errors=True)


def _swap_in(home: Home, new: Path) -> None:
    shutil.rmtree(home.prev, ignore_errors=True)
    if home.app.exists():
        os.replace(home.app, home.prev)
    os.replace(new, home.app)


def update_code(home: Home, remote: str | None, fetch=None) -> bool:
    """Bring ~/AIVillage/app to `remote` (the `stable` commit; None = offline). True if the code changed.

    A version fetched in the background last time (app.next) is used first. A version that was
    rolled back (app.bad) is not taken again. Raises only when there is no game code at all."""
    fetch = fetch or download_code
    home.root.mkdir(parents=True, exist_ok=True)
    bad = home.bad_version()
    changed = False
    ready = version_of(home.next)
    if ready and ready not in (version_of(home.app), bad):
        _swap_in(home, home.next)
        changed = True
    shutil.rmtree(home.next, ignore_errors=True)
    if remote and remote not in (version_of(home.app), bad):
        staging = home.root / "app.download"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            fetch(remote, staging)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if not home.app.exists():
                raise
            return changed
        _swap_in(home, staging)
        changed = True
    if not home.app.exists():
        raise RuntimeError("no game code and no connection to GitHub")
    return changed


def prefetch(home: Home, remote: str | None, fetch=None) -> bool:
    """Download a newer `stable` into app.next while the game runs; the next start uses it."""
    if not remote or remote in (version_of(home.app), version_of(home.next), home.bad_version()):
        return False
    fetch = fetch or download_code
    staging = home.root / "app.download-next"
    shutil.rmtree(staging, ignore_errors=True)
    fetch(remote, staging)
    shutil.rmtree(home.next, ignore_errors=True)
    os.replace(staging, home.next)
    return True


def rollback(home: Home) -> bool:
    """The new version died before answering: go back to app.prev and skip this one until `stable` moves."""
    if not home.prev.exists():
        return False
    broken = version_of(home.app)
    if broken:
        home.bad.write_text(broken)
    trash = home.root / "app.broken"
    shutil.rmtree(trash, ignore_errors=True)
    os.replace(home.app, trash)
    os.replace(home.prev, home.app)
    shutil.rmtree(trash, ignore_errors=True)
    return True


# ---- uv and the game server -------------------------------------------------------------------

def find_uv(install=True) -> str | None:
    """uv (it brings Python and the packages): the copy in ~/.local/bin, else on PATH, else installed now."""
    exe = "uv.exe" if os.name == "nt" else "uv"
    for p in (Path.home() / ".local" / "bin" / exe, Path.home() / ".cargo" / "bin" / exe):
        if p.is_file():
            return str(p)
    if shutil.which("uv"):
        return shutil.which("uv")
    if not install:
        return None
    env = dict(os.environ, UV_NO_MODIFY_PATH="1")
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "ByPass", "-c", "irm https://astral.sh/uv/install.ps1 | iex"]
    else:
        cmd = ["/bin/sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]
    subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, **_hidden())
    return find_uv(install=False)


def game_command(home: Home, uv: str) -> list[str]:
    cmd = [uv, "run", "--quiet"]
    if (home.app / "uv.lock").exists():
        cmd.append("--frozen")  # the exact packages CI tested
    return cmd + ["--python", "3.12", "--extra", "live", "python", "-m", "aivillage.launcher",
                  "--home", str(home.root), "--no-browser"]


def _hidden() -> dict:
    return {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW


def find_url(line: str) -> str | None:
    m = URL_RE.search(line)
    return m.group(0) if m else None


class Game:
    """The game server process; its output goes to ~/AIVillage/logs/app.log."""

    def __init__(self, home: Home, cmd: list[str], log):
        self.home, self.cmd, self.log = home, cmd, log
        self.url: str | None = None
        self.seen = threading.Event()
        self.stopping = False
        env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(home.root / ".venv"), PYTHONUNBUFFERED="1",
                   PYTHONIOENCODING="utf-8")
        env["PATH"] = os.pathsep.join([str(Path.home() / ".local" / "bin"), env.get("PATH", "")])
        if os.name == "nt":
            extra = {"creationflags": 0x08000000 | 0x00000200}  # no window, own process group
        else:
            extra = {"start_new_session": True}  # one group: uv and the python it starts stop together
        self.proc = subprocess.Popen(cmd, cwd=home.app, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **extra)
        if os.name != "nt":
            (home.logs / "server.pid").write_text(str(self.proc.pid))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            self.log(line.rstrip("\n"))
            if self.url is None and (url := find_url(line)):
                self.url = url
                self.seen.set()
        self.seen.set()

    def wait_ready(self, timeout: float = READY_TIMEOUT) -> str | None:
        """The game's address once it answers; None if the process ends or time runs out first."""
        deadline = time.monotonic() + timeout
        if not self.seen.wait(timeout) or self.url is None:
            return None
        while time.monotonic() < deadline and self.proc.poll() is None:
            try:
                urllib.request.urlopen(self.url, timeout=3).close()
                return self.url
            except Exception:
                time.sleep(0.3)
        return None

    def stop(self) -> None:
        self.stopping = True
        if self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True, **_hidden())
            else:
                _kill_group(self.proc.pid, signal.SIGTERM)
                try:
                    self.proc.wait(5)
                except subprocess.TimeoutExpired:
                    _kill_group(self.proc.pid, signal.SIGKILL)
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        try:
            (self.home.logs / "server.pid").unlink()
        except OSError:
            pass


def _kill_group(pgid: int, sig) -> None:
    try:
        os.killpg(pgid, sig)
    except OSError:
        pass


def stop_leftover(home: Home) -> None:
    """A server left running by an app that crashed would hold the usual port: stop it."""
    try:
        pgid = int((home.logs / "server.pid").read_text())
        out = subprocess.run(["ps", "-A", "-o", "pgid=,command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return
    if any(line.split(None, 1)[0] == str(pgid) and "aivillage" in line for line in out.splitlines() if line.strip()):
        _kill_group(pgid, signal.SIGTERM)
        time.sleep(1)


# ---- updating the app itself (macOS .app) -----------------------------------------------------

def app_bundle() -> Path | None:
    """…/AI Village.app when running as the built macOS app, else None."""
    if not getattr(sys, "frozen", False) or sys.platform != "darwin":
        return None
    bundle = Path(sys.executable).resolve().parents[2]
    return bundle if bundle.suffix == ".app" else None


def fetch_app_update(bundle: Path, version: int, get=http_get) -> bool:
    """Download a newer release next to the app (AI Village.app.new); `apply_app_update` swaps it in at exit.

    The swap waits for exit because the running app still reads its own files."""
    if not os.access(bundle.parent, os.W_OK):
        return False
    latest = int(get(f"{RELEASE}/version.txt").decode().strip())
    if latest <= version:
        return False
    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    new = bundle.with_name(bundle.name + ".new")
    work = bundle.with_name(bundle.name + ".download")
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(new, ignore_errors=True)
    work.mkdir()
    try:
        (work / "app.zip").write_bytes(get(f"{RELEASE}/AI-Village-mac-{arch}.zip", timeout=600))
        subprocess.run(["ditto", "-x", "-k", str(work / "app.zip"), str(work)], check=True, capture_output=True)
        if not (work / bundle.name / "Contents" / "MacOS").is_dir():
            return False
        os.replace(work / bundle.name, new)
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)


def apply_app_update(bundle: Path) -> bool:
    new, old = bundle.with_name(bundle.name + ".new"), bundle.with_name(bundle.name + ".old")
    if not new.is_dir():
        return False
    shutil.rmtree(old, ignore_errors=True)
    os.replace(bundle, old)
    os.replace(new, bundle)
    shutil.rmtree(old, ignore_errors=True)
    return True


# ---- the shell --------------------------------------------------------------------------------

def open_folder(path: Path) -> None:
    cmd = {"darwin": ["open"], "win32": ["explorer"]}.get(sys.platform, ["xdg-open"])
    subprocess.Popen(cmd + [str(path)], **_hidden())


class Shell:
    """Startup, rollback and background updates; `ui` shows progress (the window, or the console in --check)."""

    def __init__(self, home: Home, ui):
        self.home, self.ui = home, ui
        self.game: Game | None = None
        self.closing = False
        self.closed = threading.Event()  # wakes the background updater so the app can exit at once
        self.lock = threading.Lock()
        home.logs.mkdir(parents=True, exist_ok=True)
        log = home.logs / "app.log"
        if log.exists():
            os.replace(log, home.logs / "app-prev.log")
        self._log = open(log, "a", encoding="utf-8")

    def log(self, line: str) -> None:
        with self.lock:
            self._log.write(f"{time.strftime('%H:%M:%S')} {line}\n")
            self._log.flush()

    def log_tail(self, n: int = 30) -> str:
        try:
            return "\n".join((self.home.logs / "app.log").read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
        except OSError:
            return ""

    def start(self) -> str | None:
        """Update, start the game and wait for it; returns its address or shows what went wrong."""
        ui, home = self.ui, self.home
        self.log(f"app {build_info()} on {platform.platform()}")
        ui.say("Проверяю обновления игры…")
        remote = stable_commit()
        self.log(f"stable: {remote or 'no connection'}, here: {version_of(home.app)}")
        if remote and remote not in (version_of(home.app), home.bad_version()):
            ui.say("Скачиваю новую версию игры…")
        try:
            updated = update_code(home, remote)
        except Exception as e:
            self.log(f"download failed: {e!r}")
            ui.fail("Не получилось скачать игру. Проверьте интернет и нажмите «Попробовать ещё раз».", self.log_tail())
            return None
        first = not (home.root / ".venv").exists()
        uv = find_uv(install=False)
        if uv is None:
            ui.say("Первый запуск: ставлю нужные программы…", "Это нужно один раз, около минуты.")
            uv = find_uv()
        if uv is None:
            ui.fail("Не получилось поставить нужные программы. Проверьте интернет и нажмите «Попробовать ещё раз».",
                    self.log_tail())
            return None
        if os.name != "nt":
            stop_leftover(home)
        for attempt in (1, 2):
            ui.say("Запускаю игру…", "Первый запуск дольше обычного: скачиваются Python и библиотеки, до пары минут."
                   if first else "")
            self.log(f"start {version_of(home.app)}: {' '.join(game_command(home, uv))}")
            game = Game(home, game_command(home, uv), self.log)
            url = game.wait_ready()
            if url:
                self.game = game
                threading.Thread(target=self._watch, args=(game,), daemon=True).start()
                self.log(f"ready: {url}")
                return url
            game.stop()
            self.log(f"did not start (exit code {game.proc.returncode})")
            if attempt == 1 and updated and rollback(home):
                self.log(f"rolled back to {version_of(home.app)}")
                ui.say("Новая версия не запустилась, запускаю прошлую…")
                continue
            break
        ui.fail("Игра не запустилась. Нажмите «Попробовать ещё раз»; если не помогло, пришлите журнал из папки.",
                self.log_tail())
        return None

    def _watch(self, game: Game) -> None:
        game.proc.wait()
        if not game.stopping and not self.closing:
            self.log(f"the game stopped by itself (exit code {game.proc.returncode})")
            self.ui.fail("Игра неожиданно закрылась. Нажмите «Попробовать ещё раз».", self.log_tail())

    def stop(self) -> None:
        self.closing = True
        self.closed.set()
        if self.game:
            self.game.stop()

    def background(self, bundle: Path | None) -> None:
        """While the game is open: fetch a newer app release once and a newer `stable` every half hour."""
        if self.closed.wait(60):
            return
        if bundle:
            try:
                if fetch_app_update(bundle, int(build_info().get("version", 0))):
                    self.log("a new app version is ready; it is used from the next start")
            except Exception as e:
                self.log(f"app update check failed: {e!r}")
        while not self.closing:
            try:
                if prefetch(self.home, stable_commit()):
                    self.log(f"game {version_of(self.home.next)} downloaded; it is used from the next start")
            except Exception as e:
                self.log(f"background download failed: {e!r}")
            if self.closed.wait(PREFETCH_EVERY):
                return


# ---- the window -------------------------------------------------------------------------------

SPLASH = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#1f2b22;color:#f3ead2;font:16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:0 24px;text-align:center}
h1{margin:0;font-size:40px;letter-spacing:1px}
#s{font-size:19px;min-height:24px}#h{color:#b9c4a8;font-size:14px;min-height:18px;max-width:560px}
.bar{width:280px;height:6px;border-radius:3px;background:#34463a;overflow:hidden}
.bar i{display:block;width:35%;height:100%;background:#e0b04b;border-radius:3px;animation:go 1.4s ease-in-out infinite}
@keyframes go{0%{margin-left:-35%}100%{margin-left:100%}}
pre{max-width:min(900px,92vw);max-height:38vh;overflow:auto;text-align:left;background:#152019;color:#c9d3bd;
padding:12px;border-radius:8px;font-size:12px;white-space:pre-wrap}
button{font:inherit;padding:9px 18px;margin:0 6px;border:0;border-radius:8px;background:#e0b04b;color:#1f2b22;cursor:pointer}
button.alt{background:#34463a;color:#f3ead2}
</style></head><body><main><h1>🏡 AI Village</h1><p id="s"></p><div class="bar" id="bar"><i></i></div><p id="h"></p>
<pre id="log" hidden></pre><div id="btns" hidden><button onclick="pywebview.api.retry()">Попробовать ещё раз</button>
<button class="alt" onclick="pywebview.api.open_logs()">Открыть папку с журналом</button></div></main><script>
function say(s,h){document.getElementById('s').textContent=s;document.getElementById('h').textContent=h||'';
 document.getElementById('bar').hidden=false;document.getElementById('log').hidden=true;document.getElementById('btns').hidden=true}
function fail(s,log){say(s,'');document.getElementById('bar').hidden=true;const l=document.getElementById('log');
 l.textContent=log||'';l.hidden=!log;document.getElementById('btns').hidden=false}
const first=__FIRST__;if(first.fail)fail(first.text,first.log);else say(first.text,'');
</script></body></html>"""


def splash(text: str, log: str | None = None) -> str:
    first = {"text": text, "log": log or "", "fail": log is not None}
    return SPLASH.replace("__FIRST__", json.dumps(first, ensure_ascii=False).replace("</", "<\\/"))


class WindowUI:
    def __init__(self, window):
        self.window = window

    def say(self, text: str, hint: str = "") -> None:
        self.window.evaluate_js(f"say({json.dumps(text)}, {json.dumps(hint)})")

    def fail(self, text: str, log: str) -> None:
        self.window.load_html(splash(text, log))

    def open(self, url: str) -> None:
        self.window.load_url(url)


class ConsoleUI:
    def say(self, text: str, hint: str = "") -> None:
        print(text, hint, flush=True)

    def fail(self, text: str, log: str) -> None:
        print(f"FAILED: {text}\n{log}", flush=True)


class Api:
    """Buttons of the loading / error screen (window.pywebview.api)."""

    def __init__(self):
        self._shell: Shell | None = None
        self._run = None

    def retry(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def open_logs(self) -> None:
        open_folder(self._shell.home.logs)


def check(home: Home) -> int:
    """CI smoke test of the built app: everything but the window."""
    import webview  # noqa: F401  the window library is bundled
    if sys.platform == "darwin":
        import webview.platforms.cocoa  # noqa: F401
    shell = Shell(home, ConsoleUI())
    url = shell.start()
    print(shell.log_tail(60))
    shell.stop()
    print("OK" if url else "FAILED", url or "")
    return 0 if url else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AI Village desktop app")
    p.add_argument("--home", default=str(Path.home() / "AIVillage"), help="keys, runs and the game code")
    p.add_argument("--check", action="store_true", help="no window: update, start the game, wait for it, stop")
    a, _ = p.parse_known_args(argv)  # macOS may add its own arguments
    home = Home(Path(a.home))
    if a.check:
        return check(home)

    import webview

    bundle = app_bundle()
    if bundle:
        shutil.rmtree(bundle.with_name(bundle.name + ".old"), ignore_errors=True)
    api = Api()
    window = webview.create_window("AI Village", html=splash("Запускаю…"), js_api=api, width=1440, height=900,
                                   min_size=(900, 600), background_color="#1f2b22", maximized=True)
    shell = Shell(home, WindowUI(window))
    starting = threading.Lock()

    def run() -> None:
        if not starting.acquire(blocking=False):
            return
        try:
            if shell.game:
                shell.game.stop()
                shell.game = None
            url = shell.start()
            if url and not shell.closing:
                shell.ui.open(url)
        finally:
            starting.release()

    def boot() -> None:
        run()
        threading.Thread(target=shell.background, args=(bundle,), daemon=True).start()

    api._shell, api._run = shell, run
    def loaded() -> None:  # in the log, so a problem with the window itself can be told apart
        try:
            shell.log(f"window shows {window.get_current_url()} «{window.evaluate_js('document.title')}»")
        except Exception as e:
            shell.log(f"window loaded ({e!r})")

    window.events.loaded += loaded
    window.events.closed += shell.stop
    webview.settings["ALLOW_DOWNLOADS"] = True  # clips and logs saved from the game
    webview.start(boot, private_mode=False, storage_path=str(home.root / "webview"))
    shell.stop()
    if bundle:
        try:
            if apply_app_update(bundle):
                shell.log("app updated")
        except OSError as e:
            shell.log(f"app update failed: {e!r}")
    shell.log("closed")
    # Leave now: Python would otherwise wait for every thread still running (a download, a stuck call),
    # and an app without a window that does not quit looks frozen.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
