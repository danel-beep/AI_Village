"""The desktop app shell (desktop/aivillage_app.py): code updates, rollback, the game process."""

import importlib.util
import io
import sys
import tarfile
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aivillage_app", ROOT / "desktop" / "aivillage_app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def fake_fetch(calls):
    def fetch(sha, dest):
        calls.append(sha)
        dest.mkdir(parents=True)
        (dest / app.VERSION_FILE).write_text(sha)
    return fetch


def test_first_start_downloads_then_keeps_previous_version(tmp_path):
    home, calls = app.Home(tmp_path), []
    assert app.update_code(home, "a" * 40, fake_fetch(calls))
    assert app.version_of(home.app) == "a" * 40 and not home.prev.exists()
    assert not app.update_code(home, "a" * 40, fake_fetch(calls))  # same version: nothing downloaded
    assert app.update_code(home, "b" * 40, fake_fetch(calls))
    assert app.version_of(home.app) == "b" * 40 and app.version_of(home.prev) == "a" * 40
    assert calls == ["a" * 40, "b" * 40]


def test_offline_runs_what_is_there_and_fails_only_without_code(tmp_path):
    home = app.Home(tmp_path)
    with pytest.raises(RuntimeError):
        app.update_code(home, None, fake_fetch([]))
    app.update_code(home, "a" * 40, fake_fetch([]))

    def broken(sha, dest):
        dest.mkdir()
        raise OSError("connection reset")
    assert not app.update_code(home, None, broken)
    assert not app.update_code(home, "b" * 40, broken)  # a failed download keeps the old version
    assert app.version_of(home.app) == "a" * 40 and not (tmp_path / "app.download").exists()


def test_old_launcher_install_without_version_is_replaced(tmp_path):
    home = app.Home(tmp_path)
    (home.app / "aivillage").mkdir(parents=True)  # what scripts/start.sh left
    assert app.update_code(home, "a" * 40, fake_fetch([]))
    assert app.version_of(home.app) == "a" * 40 and (home.prev / "aivillage").is_dir()


def test_rollback_skips_the_broken_version_until_stable_moves(tmp_path):
    home, calls = app.Home(tmp_path), []
    app.update_code(home, "a" * 40, fake_fetch(calls))
    app.update_code(home, "b" * 40, fake_fetch(calls))
    assert app.rollback(home)
    assert app.version_of(home.app) == "a" * 40 and home.bad_version() == "b" * 40
    assert not app.update_code(home, "b" * 40, fake_fetch(calls))  # not taken again
    assert app.update_code(home, "c" * 40, fake_fetch(calls))      # a newer stable is
    assert calls == ["a" * 40, "b" * 40, "c" * 40]
    assert not app.rollback(app.Home(tmp_path / "empty"))


def test_background_download_is_used_at_next_start(tmp_path):
    home, calls = app.Home(tmp_path), []
    app.update_code(home, "a" * 40, fake_fetch(calls))
    assert app.prefetch(home, "b" * 40, fake_fetch(calls))
    assert not app.prefetch(home, "b" * 40, fake_fetch(calls))  # already waiting
    assert app.version_of(home.app) == "a" * 40  # the running game is not touched
    assert app.update_code(home, "b" * 40, fake_fetch(calls))  # next start, no second download
    assert app.version_of(home.app) == "b" * 40 and not home.next.exists()
    assert calls == ["a" * 40, "b" * 40]


def test_download_code_unpacks_the_github_tarball(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"print('hi')\n"
        info = tarfile.TarInfo("ai_village-abc/aivillage/launcher.py")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    sha = "c" * 40
    app.download_code(sha, tmp_path / "app", get=lambda url, timeout=0: buf.getvalue())
    assert (tmp_path / "app" / "aivillage" / "launcher.py").read_bytes() == data
    assert app.version_of(tmp_path / "app") == sha
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app"]


def test_stable_commit_reads_git_refs():
    lightweight = "001e# service=git-upload-pack\n003f" + "1" * 40 + " refs/heads/main\n" + "2" * 40 + " refs/tags/stable\n"
    assert app.stable_commit(lambda url: lightweight.encode()) == "2" * 40
    annotated = lightweight + "3" * 40 + " refs/tags/stable^{}\n" + "4" * 40 + " refs/tags/stable2\n"
    assert app.stable_commit(lambda url: annotated.encode()) == "3" * 40

    def offline(url):
        raise OSError("no network")
    assert app.stable_commit(offline) is None


def test_game_command_uses_pinned_packages(tmp_path):
    home = app.Home(tmp_path)
    home.app.mkdir()
    assert "--frozen" not in app.game_command(home, "uv")
    (home.app / "uv.lock").write_text("")
    cmd = app.game_command(home, "uv")
    assert cmd[:3] == ["uv", "run", "--quiet"] and "--frozen" in cmd
    assert cmd[-5:] == ["-m", "aivillage.launcher", "--home", str(tmp_path), "--no-browser"]


def test_launcher_prints_the_address_the_app_waits_for(monkeypatch, tmp_path, capsys):
    """The only contract with the game code: the launcher prints http://127.0.0.1:<port>."""
    from aivillage import launcher, server
    seen = {}
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))  # the launcher sets it; restored after the test
    monkeypatch.setattr(server, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    launcher.main(["--home", str(tmp_path), "--no-browser"])
    port = seen["argv"][seen["argv"].index("--port") + 1]
    assert app.find_url(capsys.readouterr().out) == f"http://127.0.0.1:{port}"


def fake_server(tmp_path, body):
    script = tmp_path / "fake_launcher.py"
    script.write_text(textwrap.dedent(body))
    return [sys.executable, "-u", str(script)]


def test_game_waits_for_an_answer_and_stops(tmp_path):
    home = app.Home(tmp_path)
    home.app.mkdir()
    home.logs.mkdir()
    cmd = fake_server(tmp_path, """
        import http.server, socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        print(f"Игра открывается в браузере: http://127.0.0.1:{port}", flush=True)
        http.server.HTTPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler).serve_forever()
    """)
    lines = []
    game = app.Game(home, cmd, lines.append)
    url = game.wait_ready(timeout=30)
    assert url and url.startswith("http://127.0.0.1:")
    game.stop()
    assert game.proc.poll() is not None and not (home.logs / "server.pid").exists()


def test_game_that_dies_is_not_ready(tmp_path):
    home = app.Home(tmp_path)
    home.app.mkdir()
    home.logs.mkdir()
    lines = []
    game = app.Game(home, fake_server(tmp_path, "raise SystemExit('ModuleNotFoundError: boom')"), lines.append)
    assert game.wait_ready(timeout=30) is None
    game.stop()
    assert any("boom" in line for line in lines)


class RecordingUI:
    def __init__(self):
        self.said, self.failed = [], []

    def say(self, text, hint=""):
        self.said.append(text)

    def fail(self, text, log):
        self.failed.append(text)


def test_shell_rolls_back_a_new_version_that_does_not_start(tmp_path, monkeypatch):
    home = app.Home(tmp_path)
    ok = [sys.executable, "-u", "-c", textwrap.dedent("""
        import http.server, socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        print(f"http://127.0.0.1:{port}", flush=True)
        http.server.HTTPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler).serve_forever()
    """)]
    broken = [sys.executable, "-c", "raise SystemExit(1)"]

    def fetch(sha, dest):
        dest.mkdir(parents=True)
        (dest / app.VERSION_FILE).write_text(sha)
    app.update_code(home, "a" * 40, fetch)
    monkeypatch.setattr(app, "stable_commit", lambda: "b" * 40)
    monkeypatch.setattr(app, "download_code", fetch)
    monkeypatch.setattr(app, "find_uv", lambda install=True: "uv")
    monkeypatch.setattr(app, "stop_leftover", lambda home: None)
    monkeypatch.setattr(app, "game_command",
                        lambda home, uv: broken if app.version_of(home.app) == "b" * 40 else ok)
    ui = RecordingUI()
    shell = app.Shell(home, ui)
    url = shell.start()
    try:
        assert url and not ui.failed
        assert "Новая версия не запустилась, запускаю прошлую…" in ui.said
        assert app.version_of(home.app) == "a" * 40 and home.bad_version() == "b" * 40
    finally:
        shell.stop()


def test_splash_escapes_the_log():
    html = app.splash("Игра не запустилась.", "</script><b>x</b>")
    assert "</script><b>" not in html and "Игра не запустилась." in html


def test_background_updater_ends_as_soon_as_the_window_closes(tmp_path):
    """It slept for half an hour between checks, and the app waited for it after the window closed:
    the closed app hung (Danel, 2026-10-08)."""
    import threading
    import time
    shell = app.Shell(app.Home(tmp_path), RecordingUI())
    t = threading.Thread(target=shell.background, args=(None,))
    t.start()
    time.sleep(0.2)
    started = time.monotonic()
    shell.stop()
    t.join(5)
    assert not t.is_alive() and time.monotonic() - started < 2

