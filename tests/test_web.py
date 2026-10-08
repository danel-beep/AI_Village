"""The public website (aivillage/web.py): password, one game server per browser, keys only in memory,
the MCP connector open without the password and nothing else."""

import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from aivillage import keys, web  # noqa: E402
from aivillage.tunnel import Tunnel  # noqa: E402

PW = "derevnya"
OR = "sk-or-v1-zyxwvutsrqponm9876"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-hostkeymustneverleak00")  # the hosting's own key
    s = web.Site(tmp_path, PW, public_url="https://village.example")
    yield s
    s.shutdown()


@pytest.fixture
def c(site):
    with TestClient(web.create_app(site)) as client:
        yield client


def login(c, password=PW):
    """A fresh browser (no cookies) logs in."""
    c.cookies.clear()
    return c.post("/login", data={"password": password, "next": "/"}, follow_redirects=False)


def test_password_required(site, c):
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert c.get("/api/settings").status_code == 401
    assert "пароль" in c.get("/login").text
    bad = login(c, "wrong")
    assert bad.status_code == 401 and "не подошёл" in bad.text
    assert c.get("/healthz").json() == {"ok": True, "playing": 0, "games": 0}
    with pytest.raises(Exception):
        with c.websocket_connect("/ws") as ws:
            ws.receive_text()
    assert not site.games  # nothing started for a stranger


def test_each_browser_own_game_keys_in_memory(site, c, tmp_path):
    assert login(c).status_code == 303
    assert "/setup.js" in c.get("/").text  # the start screen, served by this browser's own game server
    s = c.get("/api/settings").json()
    assert s["hosted"] and not s["openrouter_key"]["set"]  # the hosting's key is not handed to players
    assert c.post("/api/settings", json={"openrouter_key": OR}).json()["openrouter_key"]["set"]
    assert c.get("/api/setup").json()["has_key"]
    for f in tmp_path.rglob("*"):
        assert not f.is_file() or OR.encode() not in f.read_bytes()  # never written to disk
    remote = c.get("/api/remote").json()
    assert remote["tunnel"]["state"] == "on" and remote["tunnel"]["url"].startswith("https://village.example/p/")
    assert not c.get("/api/busy").json()["busy"]
    rid = next(iter(site.games))

    login(c)  # another browser: another workspace, no key
    assert not c.get("/api/settings").json()["openrouter_key"]["set"]
    assert len(site.games) == 2

    # without the password: the MCP connector of a running workspace only
    c.cookies.clear()
    for path in ("/api/settings", "/api/remote", "/", "/api/busy"):
        assert c.get(f"/p/{rid}{path}").status_code == 404
    assert c.get(f"/p/{rid}/mcp/nosuchseat").status_code in (404, 405)
    assert c.get("/p/unknown/mcp/x").status_code == 404


def test_idle_game_servers_stop(site, c):
    login(c)
    c.get("/api/setup")
    g = next(iter(site.games.values()))
    g.last -= 3600
    c.portal.call(site.reap)
    assert not site.games and g.proc.poll() is not None


def test_child_env_hides_host_keys(site, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-host")
    monkeypatch.setenv("AIVILLAGE_SITE_PASSWORD", PW)
    env = site.env("abc", "https://x")
    assert "OPENAI_API_KEY" not in env and "OPENROUTER_API_KEY" not in env and "AIVILLAGE_SITE_PASSWORD" not in env
    assert env["AIVILLAGE_KEYS_IN_MEMORY"] == "1" and env["AIVILLAGE_PUBLIC_URL"] == "https://x/p/abc"


def test_no_password_no_site(tmp_path):
    with pytest.raises(ValueError):
        web.Site(tmp_path, "")


def test_keys_in_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVILLAGE_KEYS_IN_MEMORY", "1")
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env-1234567")
    monkeypatch.setattr(keys, "_memory", {})
    assert keys.get("openai_key") is None  # environment keys are ignored
    keys.save({"openrouter_key": OR, "model": "x/y"})
    assert keys.get("openrouter_key") == OR and keys.get("model") == "x/y"
    assert not os.listdir(tmp_path)
    keys.save({"openrouter_key": ""})
    assert not keys.has_any_key()


def test_fixed_tunnel():
    t = Tunnel("https://site/p/abc/")
    t.start(1234)
    t.stop()
    assert t.status() == {"state": "on", "url": "https://site/p/abc", "error": ""}
    assert Tunnel("").status()["state"] == "off"
