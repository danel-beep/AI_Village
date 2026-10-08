import json
import time
import zipfile

import pytest

from aivillage import engine, modes, session
from aivillage.run import bots_decider, replay, run

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from aivillage.server import Host, create_app  # noqa: E402


def wait(cond, timeout=20.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def bot_log(tmp_path, days=2, name="2026-10-06_10-00-00.jsonl"):
    world = engine.new_world({"seed": 5})
    log = tmp_path / name
    run(world, bots_decider(world, ["worker", "thief", "random"], 4), days, log_path=str(log))
    return log


def test_build_from_a_log_alone(tmp_path):
    log = bot_log(tmp_path)
    s = session.save(log, ended_by=None)  # no session yet: the window was closed
    assert s["ended_by"] == "closed" and s["days_played"] == 2 and s["villagers_n"] == len(s["villagers"]) == 5
    assert s["started"] == "2026-10-06T10:00:00" and s["minutes"] is not None
    assert [d["day"] for d in s["days"]] == [1, 2]
    assert all(d["highlights"] for d in s["days"])  # picked by rules: no highlights sidecar, no model
    assert s["stories"] and len(s["stories"]) <= session.STORIES
    p = session.paths(log)
    assert all(f.is_file() for f in p.values())
    md = p["md"].read_text(encoding="utf-8")
    assert "## День 2" in md and "## По жителям" in md
    assert "Сводка сессии" in p["html"].read_text(encoding="utf-8")
    replay(log)  # the summary only reads the log


def test_note_survives_rebuilds_and_ensure_rebuilds_a_grown_log(tmp_path):
    log = bot_log(tmp_path, days=1)
    session.save(log, ended_by="button", days_planned=3)
    session.set_note(log, "  Борис ничего не делал  ")
    s = session.save(log)
    assert s["note"] == "Борис ничего не делал" and s["ended_by"] == "button" and s["days_planned"] == 3
    assert "Комментарий игрока" in session.paths(log)["md"].read_text(encoding="utf-8")
    assert session.ensure(log) == session.load(log)
    b = session.brief(log)
    assert b["summary"] and b["note"] and b["days"] == 1
    other = bot_log(tmp_path, days=1, name="cli.jsonl")
    assert session.brief(other) == {"name": "cli", "summary": False, "started": None, "villagers": 5,
                                    "mode": modes.title({})}


def test_end_session_button_and_past_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    host = Host(None, str(tmp_path / "runs"), str(tmp_path / "reports"), setup=True)
    c = TestClient(create_app(host=host))
    assert c.post("/api/end").status_code == 409  # nothing running yet

    r = c.post("/api/start", json={"brains": "bots", "villagers": 3, "days": 5, "pace": 2, "seed": 9})
    assert r.status_code == 200, r.text
    sim = host.sim
    assert 'src="/session.js"' in c.get("/").text
    wait(lambda: len(sim.ticks) >= 3)
    r = c.post("/api/end")
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    assert r.json()["url"] == f"/session/{name}" and host.sim is None and sim.finished
    s = c.get(f"/api/sessions/{name}").json()
    assert s["ended_by"] == "button" and s["days_planned"] == 5 and s["days_played"] == 1
    page = c.get(f"/session/{name}").text
    assert "Сводка сессии" in page and "Файл для Claude" in page and f"/replay/{name}" in page
    assert c.get("/session/..%2Fsecret").status_code == 404 and c.get("/session/nope").status_code == 404

    assert c.post(f"/api/sessions/{name}/note", json={"note": "мало сделок"}).json()["ok"]
    z = c.post(f"/api/sessions/{name}/zip", json={"note": "мало сделок!"}).json()
    assert z["name"].startswith("session_") and z["name"].endswith(".zip")
    with zipfile.ZipFile(z["path"]) as f:
        assert {"report.json", "run.jsonl", "session.md", "session.json"} <= set(f.namelist())
        assert json.loads(f.read("report.json"))["note"] == "мало сделок!"

    lst = c.get("/api/sessions").json()["sessions"]
    assert [x["name"] for x in lst] == [name] and lst[0]["note"]
    assert name in c.get("/sessions").text

    # "Новая деревня" saves the session too; a run that plays all its days saves it by itself.
    c.post("/api/start", json={"brains": "bots", "villagers": 3, "days": 5, "pace": 2, "seed": 4})
    wait(lambda: len(host.sim.ticks) >= 2)
    second = host.sim
    assert c.post("/api/stop").json()["ok"]
    assert second.session and second.session["ended_by"] == "new_village"
    time.sleep(1.1)  # logs are named by the second they started
    c.post("/api/start", json={"brains": "bots", "villagers": 3, "days": 1, "pace": 0, "seed": 4})
    third = host.sim
    wait(lambda: third.session is not None)
    assert third.session["ended_by"] == "finished" and third.session["days_played"] == 1
    assert len(c.get("/api/sessions").json()["sessions"]) == 3
    replay(third.log_path)
