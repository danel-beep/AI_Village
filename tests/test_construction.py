"""Building with your own hands (aivillage/construction.py)."""

import json

from test_neutrality import evaluative

from aivillage import construction, engine, llm, ops, progress, spoilage, works
from aivillage.invariants import check
from aivillage.run import bots_decider, replay, run, view

ON = {"seed": 1, "construction": {"enabled": True}}


def world(extra=None, **kw):
    w = engine.new_world({**ON, **(extra or {}), **kw})
    for a in w.agents.values():
        a.busy_until = 0
    return w


def act(w, name, action, **args):
    a = w.agents[name]
    a.busy_until, a.task, a.asleep = w.tick, None, False
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def together(w, action, names, **args):
    for n in names:
        a = w.agents[n]
        a.busy_until, a.task, a.asleep = w.tick, None, False
    events = engine.step(w, {n: {"action": {"name": action, "args": args}} for n in names})
    check(w)
    return events


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def give(w, name, **items):
    for k, v in items.items():
        ops.mint(w, w.agents[name].inventory, k, v)


def site_of(w, kind):
    return next(s for s in construction.sites(w).values() if s["kind"] == kind)


def test_off_by_default():
    w = engine.new_world({"seed": 1})
    assert "building_sites" not in engine.observe(w, "Anna", consume_inbox=False)
    assert "start_building" not in engine.observe(w, "Anna", consume_inbox=False)["available_actions"]
    assert construction.view(w) == {} and w.construction == {}


def test_house_goes_up_by_materials_and_hours():
    w = world()
    plot = w.plots["home_Anna"]
    assert plot.house == 1
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert obs["can_start_building_here"]["house"]["level"] == 2
    assert "upgrade_house" not in obs["available_actions"]
    assert "upgrade_house" in errors(act(w, "Anna", "upgrade_house"))[0]
    assert not errors(act(w, "Anna", "start_building", kind="house"))
    s = site_of(w, "house")
    assert s["level"] == 2 and s["min_workers"] == 2 and s["owner"] == "Anna"
    assert s["needs"] == {"wood": 16, "stone": 16}  # no crafting here: 8 plank = 16 wood, 8 brick = 16 stone
    give(w, "Anna", wood=16, stone=16)
    assert not errors(act(w, "Anna", "bring_materials", site_id=s["id"], items={"wood": 20, "stone": 16}))
    assert construction.remaining(s) == {} and ops.count(w.agents["Anna"].inventory, "wood") == 0
    # alone it does not count; a neighbour joining within the hour makes both hours count, with the team bonus
    w.agents["Boris"].location = "home_Anna"
    act(w, "Anna", "construct", site_id=s["id"])
    assert s["work"] == 0 and len(s["pending"]) == 1
    engine.step(w, {})  # the next hour: Anna's lone hour is lost
    together(w, "construct", ["Anna", "Boris"], site_id=s["id"])
    assert s["work"] == 2.5 and s["workers"] == {"Anna": 1.25, "Boris": 1.25}
    for _ in range(3):
        together(w, "construct", ["Anna", "Boris"], site_id=s["id"])
    assert s["id"] not in construction.sites(w)
    assert plot.house == 2 and plot.cells == 6 + w.config["plots"]["house_bonus_cells"]
    assert progress.built(w)["house@2"] == 1


def test_work_alone_is_lost_after_the_window():
    w = world()
    w.agents["Anna"].location = "square"
    act(w, "Anna", "start_building", kind="market_square")
    s = site_of(w, "market_square")
    act(w, "Anna", "construct", site_id=s["id"])
    engine.step(w, {})
    engine.step(w, {})
    ev = act(w, "Anna", "construct", site_id=s["id"])
    assert any(e.kind == "site_work_lost" for e in ev) and s["work"] == 0 and len(s["pending"]) == 1


def test_shelter_roof_and_progress_lock():
    w = world(progress={"enabled": True})
    w.plots["home_Anna"].house = 0
    assert not construction.has_roof(w, "Anna")
    here = construction.startable(w, w.agents["Anna"])
    assert "shelter" in here and "granary" not in here and "smithy" not in here  # camp
    act(w, "Anna", "start_building", kind="shelter")
    s = site_of(w, "shelter")
    give(w, "Anna", wood=4)
    act(w, "Anna", "bring_materials", site_id=s["id"], items={"wood": 4})
    act(w, "Anna", "construct", site_id=s["id"])
    ev = act(w, "Anna", "construct", site_id=s["id"])
    assert any(e.kind == "building_done" and "Anna (2h of work + 4 materials)" in e.text for e in ev)
    assert construction.has_roof(w, "Anna") and construction.has_building(w, "shelter", name="Anna") == 1
    w.agents["Boris"].location = "square"
    assert "town_hall" not in construction.startable(w, w.agents["Boris"])
    assert "needs the village being a village" in errors(act(w, "Boris", "start_building", kind="town_hall"))[0]


def test_common_buildings_count_for_progress_and_effects():
    w = world(progress={"enabled": True}, spoilage={"enabled": True})
    for kind in ("market_square", "palisade"):
        construction.place(w, kind, "square", 2, builders=["Anna"])
    construction.place(w, "granary", "home_Anna", 1)
    construction.place(w, "smokehouse", "home_Boris", 1)
    assert progress.built(w)["market_square@2"] == 1
    assert works.defense(w) == 2 and abs(works.sell_factor(w, "sell") - 1.1) < 1e-9
    assert spoilage.storage_factor(w, "Anna", "bread") == 2 and spoilage.storage_factor(w, "Clara", "bread") == 1
    assert spoilage.storage_factor(w, "Boris", "fish") == 3 and spoilage.storage_factor(w, "Boris", "bread") == 1
    assert construction.has_building(w, "palisade", location="square") == 2
    v = view(w)
    assert v["buildings"][0]["kind"] == "market_square" and v["sites"] == []


def test_view_sites_format_and_save_roundtrip():
    w = world()
    w.agents["Anna"].location = w.agents["Boris"].location = "square"
    act(w, "Anna", "start_building", kind="campfire")
    s = site_of(w, "campfire")
    give(w, "Anna", wood=3)
    act(w, "Anna", "bring_materials", site_id=s["id"], items={"wood": 3})
    site = construction.view(w)["sites"][0]
    assert set(site) == {"id", "kind", "level", "location", "done", "workers"}
    assert site["kind"] == "campfire" and site["location"] == "square" and 0 < site["done"] < 1
    w2 = engine.World.from_dict(json.loads(json.dumps(w.to_dict())))
    assert w2.hash() == w.hash() and construction.sites(w2)[s["id"]]["given"] == {"wood": 3}


def test_fuzz_and_replay_with_construction_and_progress(tmp_path):
    for seed in range(3):
        w = engine.new_world({**ON, "seed": seed, "progress": {"enabled": True, "start_stage": "hamlet"},
                              "start_items": {"wood": 20, "stone": 20}})
        log = tmp_path / f"run{seed}.jsonl"
        bots = bots_decider(w, ["random", "worker", "random"], seed)
        found = set()

        def decide(name, obs, _bots=bots):
            found.update(evaluative(json.dumps(obs)))
            return _bots(name, obs)
        decide.bots = bots.bots
        run(w, decide, days=4, log_path=log)
        check(w)
        assert found == set()
        assert replay(log).hash() == w.hash()
    assert evaluative(llm.world_facts(w.config)) == []


def test_crafted_materials_with_crafting_on():
    w = world(crafting={"enabled": True})
    assert construction.cost(w.config, w.config["construction"]["catalog"]["house"]["levels"][1]) == \
        {"plank": 8, "brick": 8}
    act(w, "Anna", "start_building", kind="kiln")
    assert site_of(w, "kiln")["needs"] == {"stone": 12, "clay": 6}
