"""In-app start screen: knobs (aivillage/knobs.py) and the server's --setup mode."""

import json
import time

import pytest

from aivillage import knobs, modes
from aivillage.config import DEFAULT_CONFIG


def test_every_preset_has_a_slider_position_for_every_config_knob():
    for p in modes.PRESETS:
        d = knobs.preset_defaults(p)
        assert set(d) == {k["key"] for k in knobs.active() if "path" in k or "action" in k} | set(knobs.follow_keys())
    assert knobs.follow_keys() == ["food"]
    assert knobs.preset_defaults("normal")["unfairness"] == round(DEFAULT_CONFIG["map"]["unfairness"] * 10)
    assert knobs.preset_defaults("lawless")["steal_notice_chance"] == 5
    assert knobs.preset_defaults("normal")["steal_notice_chance"] == round(DEFAULT_CONFIG["steal_notice_chance"] * 100)
    assert knobs.preset_defaults("harsh")["food"] == "scarce" and knobs.preset_defaults("normal")["food"] == "normal"


def test_start_screen_layout_main_on_top_every_knob_placed_with_a_hint():
    s = knobs.schema()
    keys = [k["key"] for k in s["knobs"]]
    assert sorted(keys) == sorted(k["key"] for k in knobs.active() if k["key"] not in knobs.RETIRED)  # nothing lost or doubled
    main = [k["key"] for k in s["knobs"] if k["section"] == "main"]
    assert main == [k for k in knobs.MAIN if k in keys] and keys[:len(main)] == main
    titles = [sec["title"] for sec in s["sections"]]
    assert {k["section"] for k in s["knobs"]} - {"main"} == set(titles)
    assert all(k["hint"] for k in s["knobs"]), [k["key"] for k in s["knobs"] if not k["hint"]]
    listed = set(knobs.MAIN) | {key for _, _, ks in knobs.SECTIONS for key in ks}
    assert listed <= {k["key"] for k in knobs.KNOBS}  # no typos in the layout


def test_simple_view_and_retired_knobs():
    """«Простой» shows a handful of knobs; retired switches (older, dearer ways) are off the screen but still work."""
    s = knobs.schema()
    shown = {k["key"] for k in s["knobs"]}
    assert not knobs.RETIRED & shown and knobs.RETIRED <= {k["key"] for k in knobs.active()}
    assert [k["key"] for k in s["knobs"] if k["simple"]] and {k["key"] for k in s["knobs"] if k["simple"]} == set(knobs.SIMPLE)
    assert all(k["section"] != k["group"] for k in s["knobs"])  # every knob sits in a planned section
    o = knobs.to_run({"brains": "bots"})["override"]
    assert o["llm_memory"] == "day" and o["llm_obs"] == "changes" and o["map"]["procedural"] is True
    o = knobs.to_run({"brains": "bots", "llm_obs": "full", "fixed_map": True})["override"]  # an old saved form
    assert o["llm_obs"] == "full" and o["map"]["procedural"] is False


def test_a_knob_missing_from_the_layout_falls_back_to_its_group():
    extra = {"key": "x", "group": "Новое", "type": "toggle", "label": "X"}
    ordered, sections = knobs.layout(knobs.active() + [extra])
    assert ordered[-1]["key"] == "x" and ordered[-1]["section"] == "Новое" and sections[-1]["title"] == "Новое"


def test_to_run_defaults_follow_the_preset_and_answers_win():
    r = knobs.to_run({"preset": "village"})
    assert r["llm"] and r["days"] == 3 and r["override"]["population"] == {"size": 5, "always": ["Boris"]}
    assert r["override"]["progress"]["start_stage"] == "village" and r["override"]["preset"] == "village"
    r = knobs.to_run({"preset": "lawless", "brains": "bots", "start_coins": 7, "steal_notice_chance": 25,
                      "unfairness": 10, "seasons": False, "fixed_map": True, "villagers": 999})
    o = r["override"]
    assert o["start_coins"] == 7 and o["steal_notice_chance"] == 0.25 and o["map"]["unfairness"] == 1.0
    assert o["seasons"]["enabled"] is False and o["map"]["procedural"] is False
    assert o["population"]["size"] == 60  # clamped to the slider
    assert set(o["disabled_actions"]) == set(modes.disabled("lawless"))
    assert not r["llm"] and r["bots"] == knobs.BOT_MIXES["mixed"]


def test_bad_answers_are_refused():
    with pytest.raises(ValueError):
        knobs.to_run({"no_such_knob": 1})
    with pytest.raises(ValueError):
        knobs.to_run({"preset": "chaos"})
    with pytest.raises(ValueError):
        knobs.to_run({"seed": "abc"})


def test_knobs_for_features_not_in_config_are_hidden(monkeypatch):
    extra = {"key": "future", "path": "no_such.setting", "group": "x", "type": "toggle", "label": "x"}
    monkeypatch.setattr(knobs, "KNOBS", knobs.KNOBS + [extra])
    assert "future" not in {k["key"] for k in knobs.active()}


def test_world_from_start_screen_has_the_settings():
    from aivillage import engine
    r = knobs.to_run({"brains": "bots", "preset": "village", "villagers": 7, "start_coins": 55, "tax_amount": 5,
                      "polities": False})
    w = engine.new_world({**r["override"], "seed": 4})
    assert len(w.agents) == 7 and w.config["tax_amount"] == 5 and w.config["start_coins"] == 55



def test_little_food_keeps_the_camp_start():
    """«Еды в мире: мало» on «С нуля»: still an empty camp, with little food (Danel's run 2026-10-06)."""
    from aivillage import engine
    base = knobs.to_run({"brains": "bots", "preset": "normal", "start_stage": "camp"})["override"]
    r = knobs.to_run({"brains": "bots", "preset": "normal", "start_stage": "camp", "food": "scarce"})
    o = r["override"]
    assert o["food_supply"] == "scarce" and o["progress"]["start_stage"] == "camp"
    assert o["plots"]["buildings"]["garden_bed"]["yield"] == base["plots"]["buildings"]["garden_bed"]["yield"] // 2
    w = engine.new_world({**o, "seed": 3})
    assert modes.camp_start(w.config) and all(a.coins == 0 for a in w.agents.values())
    assert w.config["satiety_start"] == 50 and w.config["npc_sell_ratio"] == 2.5
    full = engine.new_world({**base, "seed": 3}).config["locations"]
    for loc in ("river", "forest"):
        for res, v in w.config["locations"][loc]["resources"].items():
            if res in modes.WILD_FOOD:
                assert v["max"] == max(1, full[loc]["resources"][res]["max"] // 2)
    # «Суровый» has little food already: saying so again changes nothing
    assert knobs.to_run({"preset": "harsh", "food": "scarce"})["override"] == knobs.to_run({"preset": "harsh"})["override"]

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
    assert c.post("/api/start", json={"brains": "bots", "preset": "nope"}).status_code == 400
    assert c.get("/api/runs").json()["runs"] == []

    r = c.post("/api/start", json={"brains": "bots", "villagers": 3, "days": 1, "pace": 0, "seed": 9,
                                   "preset": "village", "start_coins": 33})
    assert r.status_code == 200, r.text
    sim = host.sim
    wait(lambda: sim.finished)
    with open(sim.log_path, encoding="utf-8") as f:
        head = json.loads(f.readline())
    assert head["config"]["preset"] == "village" and head["start_knobs"]["start_coins"] == 33  # for comparisons
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
    ro = c.post("/api/roster", json={"n": 7, "existing": [{"name": "Ваня", "profession": "farmer"}]}).json()["roster"]
    assert len(ro) == 7 and ro[0]["name"] == "Ваня"
    assert c.post("/api/roster", json={"n": 2, "existing": [{"name": "", "profession": "x"}]}).status_code == 400


def test_plain_server_cannot_be_stopped_from_the_page(tmp_path):
    from aivillage import engine
    from aivillage.run import bots_decider
    from aivillage.server import LiveSim
    world = engine.new_world({"seed": 3})
    sim = LiveSim(world, bots_decider(world, ["worker"], 3), 1, str(tmp_path / "l.jsonl"), 0.0)
    c = TestClient(create_app(sim))
    assert "src=\"/setup.js\"" not in c.get("/").text
    assert c.post("/api/stop").status_code == 400


def test_villagers_one_by_one():
    from aivillage import engine
    rows = [{"name": "  Ваня ", "profession": "farmer", "character": "sly"},
            {"name": "Петя", "profession": "smith", "character": "You love songs."},
            {"name": "Lost", "profession": "miner", "character": "default"}]
    r = knobs.to_run({"brains": "llm", "villagers": 2, "characters": "random", "roster": rows})
    assert r["override"]["agents"] == [{"name": "Ваня", "profession": "farmer", "character": "sly"},
                                       {"name": "Петя", "profession": "smith", "character": "You love songs."}]
    assert r["override"]["characters"] == "random"
    w = engine.new_world({**knobs.to_run({"brains": "bots", "villagers": 4, "roster": rows})["override"], "seed": 1})
    assert [a["name"] for a in w.config["agents"]][:3] == ["Ваня", "Петя", "Lost"] and len(w.agents) == 4
    for bad in ([{"name": "", "profession": "farmer"}], [{"name": "A", "profession": "pirate"}],
                [{"name": "A", "profession": "farmer"}, {"name": "a", "profession": "smith"}]):
        with pytest.raises(ValueError):
            knobs.to_run({"roster": bad})
    assert len(knobs.roster(8, 5)) == 8


def test_tick_minutes_from_start_screen(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    host = Host(None, str(tmp_path / "runs"), setup=True)
    host.start({"brains": "bots", "villagers": 2, "days": 1, "pace": 0, "tick_minutes": 30})
    assert host.sim.world.config["tick_minutes"] == 30
    host.stop()
    host.start({"brains": "bots", "villagers": 2, "days": 1, "pace": 0})
    assert host.sim.world.config["tick_minutes"] == 15
    host.stop()


def test_villager_look_from_the_editor():
    rows = [{"name": "Вера", "profession": "farmer", "look": 13}, {"name": "Петя", "profession": "smith", "look": 99},
            {"name": "Лев", "profession": "miner", "look": True}]
    agents = knobs.to_run({"villagers": 3, "roster": rows})["override"]["agents"]
    assert [a.get("look") for a in agents] == [13, None, None]
    assert knobs.roster(3, 1, [{"name": "Вера", "profession": "farmer", "look": 13}])[0]["look"] == 13


def test_arson_fights_land_and_gold_knobs():
    from aivillage import engine
    r = knobs.to_run({"brains": "bots", "allow_arson": False, "combat": False, "gold": 50, "land_price": 12})
    o = r["override"]
    assert "set_fire" in o["disabled_actions"] and o["combat"]["enabled"] is False
    assert o["land"]["price_per_cell"] == 12
    gold = engine.new_world({**o, "seed": 2}).config["locations"]["mine"]["resources"]["gold"]
    assert gold["start"] == gold["max"] and 35 <= gold["start"] <= 70  # the map's unfairness nudges resources
    assert "set_fire" not in knobs.to_run({})["override"].get("disabled_actions", [])
    assert knobs.preset_defaults("normal")["allow_arson"] is True


def test_app_village_always_has_boris_on_a_random_seat():
    from aivillage import engine
    seats, profs = set(), set()
    for seed in range(1, 21):
        run = knobs.to_run({"seed": seed, "preset": "village", "no_professions": False})  # professions on, no camp start
        w = engine.new_world({**run["override"], "seed": seed})
        names = list(w.agents)
        assert names.count("Boris") == 1
        seats.add(names.index("Boris"))
        profs.add(w.agents["Boris"].profession)
    assert len(seats) > 2 and len(profs) > 2  # nothing else about him is fixed
    assert "Boris" in [a["name"] for a in knobs.roster(5, 4)]
    assert "Boris" not in [a["name"] for a in knobs.roster(2, 4, [{"name": "Вера", "profession": "farmer"},
                                                                  {"name": "Ян", "profession": "smith"}])]


def test_luna_and_haiku_half_each_from_the_start_screen(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from aivillage import llm, remote, server
    from aivillage.run import brains_of, llm_agents
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    mix = knobs.MODEL_MIXES["luna_haiku"]
    assert knobs.to_run({})["models"] is None and knobs.to_run({"models": "luna_haiku"})["models"] == mix
    assert "models" in knobs.SIMPLE and "models" in knobs.MAIN

    c = TestClient(create_app(host=Host(None, str(tmp_path / "runs"), setup=True)))
    r = c.post("/api/start", json={"brains": "llm", "models": "luna_haiku"})
    assert r.status_code == 400 and "OpenRouter" in r.json()["detail"]  # Haiku only goes through OpenRouter
    assert not c.get("/api/setup").json()["has_openrouter"]

    got = {}
    monkeypatch.setattr(server, "make_sim", lambda world, **kw: got.update(world=world, **kw) or MagicMock())
    monkeypatch.setattr(llm, "check", lambda *a, **k: {"ok": True})
    Host(None, str(tmp_path / "runs"), setup=True).start({"brains": "llm", "models": "luna_haiku", "villagers": 6})
    assert got["models"] == mix
    w = got["world"]
    # Luna goes straight to OpenAI (normal tier), Haiku to OpenRouter, by the "auto" provider
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    agents = llm_agents(w, got["models"])
    decide = type("Decide", (), {"agents": agents})()
    per_villager = brains_of(decide)  # the log header's "brains": each villager's model
    assert sorted(per_villager.values()) == sorted(mix * 3)
    luna = next(a.client for a in agents.values() if a.client.model == mix[0])
    assert isinstance(luna, llm.FallbackClient) and luna.primary.tier() == "default"
    assert all(isinstance(a.client, llm.OpenRouterClient) for a in agents.values() if a.client.model == mix[1])
    # own-AI seats keep "mcp", the rest share the mix evenly
    w.config["own_ai"] = {"seats": 2}
    own = remote.models_for(w.config, mix)
    assert list(own.values()).count("mcp") == 2
    assert sorted(m for m in own.values() if m != "mcp") == sorted(mix * 2)
