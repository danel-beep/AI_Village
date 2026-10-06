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
    give(w, "Anna", wood=12, stone=10)
    assert not errors(act(w, "Anna", "bring_materials", site_id=s["id"], items={"wood": 20, "stone": 10}))
    assert construction.remaining(s) == {} and ops.count(w.agents["Anna"].inventory, "wood") == 0
    # alone it does not count yet; a neighbour working on it later that day makes both hours count, with the bonus
    w.agents["Boris"].location = "home_Anna"
    act(w, "Anna", "construct", site_id=s["id"])
    assert s["work"] == 0 and len(s["pending"]) == 1
    for _ in range(3):  # hours later, the same day
        engine.step(w, {})
    act(w, "Boris", "construct", site_id=s["id"])
    assert s["work"] == 2.5 and s["workers"] == {"Anna": 1.25, "Boris": 1.25}
    for _ in range(3):
        together(w, "construct", ["Anna", "Boris"], site_id=s["id"])
    assert s["id"] not in construction.sites(w)
    assert plot.house == 2 and plot.cells == 6 + w.config["plots"]["house_bonus_cells"]
    assert progress.built(w)["house@2"] == 1


def next_day(w):
    day = w.day
    while w.day == day:
        engine.step(w, {})


def test_work_alone_is_lost_when_nobody_joins_that_day():
    w = world()
    w.agents["Anna"].location = "square"
    act(w, "Anna", "start_building", kind="market_square")
    s = site_of(w, "market_square")
    act(w, "Anna", "construct", site_id=s["id"])
    engine.step(w, {})
    engine.step(w, {})
    ev = act(w, "Anna", "construct", site_id=s["id"])
    assert not any(e.kind == "site_work_lost" for e in ev) and s["work"] == 0 and len(s["pending"]) == 2
    next_day(w)
    w.agents["Anna"].location = "square"
    ev = act(w, "Anna", "construct", site_id=s["id"])
    lost = next(e for e in ev if e.kind == "site_work_lost")
    assert lost.text.startswith("2 hour(s)") and s["work"] == 0 and len(s["pending"]) == 1


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


def test_team_site_shows_who_worked_on_it_today():
    w = world()
    w.agents["Anna"].location = "square"
    act(w, "Anna", "start_building", kind="market_square")
    s = site_of(w, "market_square")
    obs_site = lambda: next(x for x in engine.observe(w, "Boris", consume_inbox=False)["building_sites"]  # noqa: E731
                            if x["id"] == s["id"])
    assert "worked_on_it_today" not in obs_site() and obs_site()["people_needed_on_the_same_day"] == 2
    act(w, "Anna", "construct", site_id=s["id"])
    for _ in range(5):
        engine.step(w, {})
    assert obs_site()["worked_on_it_today"] == ["Anna"]
    next_day(w)  # a new day: nobody's hour is waiting any more
    assert "worked_on_it_today" not in obs_site()


def test_upgrade_house_left_out_of_the_handbook_with_construction():
    from aivillage.run import llm_agents
    w = world()
    agent = llm_agents(w, {"Anna": "stub"})["Anna"]
    system = agent.messages(engine.observe(w, "Anna", consume_inbox=False))[0]["content"]
    assert "upgrade_house(" not in system and "start_building(" in system
    w = engine.new_world({"seed": 1})  # houses upgraded at once: the action stays
    agent = llm_agents(w, {"Anna": "stub"})["Anna"]
    assert "upgrade_house(" in agent.messages(engine.observe(w, "Anna", consume_inbox=False))[0]["content"]


def test_catalog_says_what_a_building_opens_only_with_stages():
    on = world(progress={"enabled": True})
    assert construction.effect_text(on.config, "market_square", 1).startswith("opens the trader at the market")
    assert "opens" in construction.effect_text(on.config, "town_hall", 1)
    assert "market_square (square; L1: " in construction.facts(on.config)
    assert "-> opens the trader" in construction.facts(on.config)
    off = world()  # everything is open from the start: nothing to announce
    assert construction.effect_text(off.config, "market_square", 1) == ""
    assert "opens" not in construction.effect_text(off.config, "town_hall", 1)


def test_help_on_someone_elses_site_counts_as_help():
    w = world()
    assert not errors(act(w, "Anna", "start_building", kind="house"))
    s = site_of(w, "house")
    give(w, "Boris", wood=2)
    w.agents["Boris"].location = "home_Anna"
    assert not errors(act(w, "Boris", "bring_materials", site_id=s["id"], items={"wood": 2}))
    feel = w.kin.feelings["Anna"]["Boris"]
    assert feel == w.config["family"]["on_event"]["site_supplied"][1]
    act(w, "Boris", "construct", site_id=s["id"])
    assert w.kin.feelings["Anna"]["Boris"] > feel
    assert w.agents["Anna"].reputation["Boris"]["score"] == 2
    # one's own site is not help: nobody's tally of Anna moves
    give(w, "Anna", wood=2)
    act(w, "Anna", "bring_materials", site_id=s["id"], items={"wood": 2})
    act(w, "Anna", "construct", site_id=s["id"])
    assert "Anna" not in w.agents["Boris"].reputation and "Anna" not in w.kin.feelings.get("Boris", {})
