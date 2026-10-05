"""In-app start screen: knobs (aivillage/knobs.py) and the server's --setup mode."""

import time

import pytest

from aivillage import knobs, modes
from aivillage.config import DEFAULT_CONFIG


def test_every_mode_has_a_slider_position_for_every_config_knob():
    for m in modes.MODES:
        d = knobs.mode_defaults(m)
        assert set(d) == {k["key"] for k in knobs.active() if "path" in k}
    assert knobs.mode_defaults("peaceful")["start_coins"] == 40
    assert knobs.mode_defaults("peaceful")["unfairness"] == 1  # 0.1 on a 0..10 slider
    assert knobs.mode_defaults("standard")["steal_notice_chance"] == round(DEFAULT_CONFIG["steal_notice_chance"] * 100)


def test_to_run_defaults_follow_the_mode_and_answers_win():
    r = knobs.to_run({"mode": "peaceful"})
    assert r["llm"] and r["days"] == 3 and r["override"]["population"] == {"size": 5}
    assert r["override"]["start_coins"] == 40 and r["override"]["map"] == {"unfairness": 0.1, "procedural": True}
    r = knobs.to_run({"mode": "lawless", "brains": "bots", "start_coins": 7, "steal_notice_chance": 25,
                      "unfairness": 10, "seasons": False, "fixed_map": True, "villagers": 999})
    o = r["override"]
    assert o["start_coins"] == 7 and o["steal_notice_chance"] == 0.25 and o["map"]["unfairness"] == 1.0
    assert o["seasons"]["enabled"] is False and o["map"]["procedural"] is False
    assert o["population"]["size"] == 60  # clamped to the slider
    assert o["disabled_actions"] == modes.disabled("lawless")
    assert not r["llm"] and r["bots"] == knobs.BOT_MIXES["mixed"]


def test_bad_answers_are_refused():
    with pytest.raises(ValueError):
        knobs.to_run({"no_such_knob": 1})
    with pytest.raises(ValueError):
        knobs.to_run({"mode": "chaos"})
    with pytest.raises(ValueError):
        knobs.to_run({"seed": "abc"})


def test_knobs_for_features_not_in_config_are_hidden(monkeypatch):
    extra = {"key": "future", "path": "no_such.setting", "group": "x", "type": "toggle", "label": "x"}
    monkeypatch.setattr(knobs, "KNOBS", knobs.KNOBS + [extra])
    assert "future" not in {k["key"] for k in knobs.active()}


def test_world_from_start_screen_has_the_settings():
    from aivillage import engine
    r = knobs.to_run({"brains": "bots", "villagers": 7, "start_coins": 55, "tax_amount": 5})
    w = engine.new_world({**r["override"], "seed": 4})
    assert len(w.agents) == 7 and w.config["tax_amount"] == 5 and w.config["start_coins"] == 55


pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from aivillage.server import Host, create_app  # noqa: E402


def wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_setup_mode_start_stop_and_past_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    host = Host(None, str(tmp_path / "runs"), str(tmp_path / "reports"), setup=True)
    c = TestClient(create_app(host=host))

    page = c.get("/").text
    assert "src=\"/setup.js\"" in page and "src=\"/live.js\"" not in page
    info = c.get("/api/setup").json()
    assert not info["running"] and info["can_restart"] and not info["has_key"]
    assert c.get("/api/status").status_code == 409
    assert c.post("/api/start", json={"brains": "llm"}).status_code == 400  # no key yet
    assert c.post("/api/start", json={"brains": "bots", "mode": "nope"}).status_code == 400
    assert c.get("/api/runs").json()["runs"] == []

    r = c.post("/api/start", json={"brains": "bots", "villagers": 3, "days": 1, "pace": 0, "seed": 9,
                                   "start_coins": 33})
    assert r.status_code == 200, r.text
    sim = host.sim
    wait(lambda: sim.finished)
    assert sim.header["config"]["start_coins"] == 33 and len(sim.world.agents) == 3
    page = c.get("/").text
    assert "src=\"/live.js\"" in page and "src=\"/setup.js\"" in page  # the "new village" button
    assert c.get("/api/setup").json()["last"]["start_coins"] == 33

    assert c.post("/api/stop").json()["ok"] and host.sim is None
    runs = c.get("/api/runs").json()["runs"]
    assert len(runs) == 1
    rep = c.post("/api/report-last", json={"note": "всё стоит"}).json()
    assert rep["ok"] and rep["name"].endswith(".zip")
    assert c.get("/replay/..%2Fx").status_code == 404


def test_plain_server_cannot_be_stopped_from_the_page(tmp_path):
    from aivillage import engine
    from aivillage.run import bots_decider
    from aivillage.server import LiveSim
    world = engine.new_world({"seed": 3})
    sim = LiveSim(world, bots_decider(world, ["worker"], 3), 1, str(tmp_path / "l.jsonl"), 0.0)
    c = TestClient(create_app(sim))
    assert "src=\"/setup.js\"" not in c.get("/").text
    assert c.post("/api/stop").status_code == 400
