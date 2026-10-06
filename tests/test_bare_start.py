"""«С нуля» mode, empty start (modes.bare_start): camp = nothing, hamlet and later = the ready village."""

import json

from aivillage import construction, engine, knobs, modes, ops, progress
from aivillage.invariants import check


def world(stage="camp", **extra):
    return engine.new_world(modes.world_override("survival", {"seed": 3, "progress": {"start_stage": stage}, **extra}))


def step(w, decisions):
    engine.step(w, {n: {"action": {"name": a, "args": args}} for n, (a, args) in decisions.items()})
    check(w)


def test_camp_start_is_empty():
    w = world(map={"procedural": True, "unfairness": 1.0})
    assert progress.stage(w) == "camp"
    for a in w.agents.values():
        assert a.profession == "laborer" and a.coins == 0 and not any(a.inventory.values())
    homes = [p for p in w.plots.values() if p.kind == "home"]
    assert homes and all(p.house == 0 and not p.buildings for p in homes)
    assert not w.config["places"]["enabled"] and not w.config["labor"]["own_trade_only"]


def test_hamlet_start_is_the_ready_village():
    w = world("hamlet")
    assert progress.stage(w) == "hamlet"
    assert any(a.profession != "laborer" for a in w.agents.values())
    assert all(a.inventory.get("tool") == 1 for a in w.agents.values())
    assert all(p.house >= 1 for p in w.plots.values() if p.kind == "home" and p.owner)
    assert all(a.coins == 0 for a in w.agents.values())  # no market square yet, so no coins


def test_village_start_has_coins():
    w = world("village", map={"procedural": True, "unfairness": 1.0})
    assert progress.stage(w) == "village" and sum(a.coins for a in w.agents.values()) > 0


def test_other_modes_untouched():
    w = engine.new_world(modes.world_override("crafts", {"seed": 3}))
    assert not progress.enabled(w.config) and "applied" not in w.config["bare_start"]
    assert all(a.profession != "laborer" for a in w.agents.values())


def test_camp_laborer_gathers_anything_and_builds_a_house():
    w = world()
    a = w.agents["Anna"]
    a.location = "river"
    step(w, {"Anna": ("work", {"resource": "fish"})})
    assert a.inventory.get("fish", 0) > 0  # no trade rule in a camp
    step(w, {"Anna": ("sell", {"item": "fish", "qty": 1})})
    assert a.coins == 0 and a.inventory.get("fish", 0) > 0  # no market yet
    a.location = a.home
    step(w, {"Anna": ("start_building", {"kind": "house"})})
    assert not construction.sites(w)  # a spot at the camp has no yard: a house site first (settle.py)
    a.location, a.busy_until, a.task = "river", w.tick, None
    step(w, {"Anna": ("settle", {})})
    assert w.locations[a.home].neighbors == ["river"] and a.home in w.locations["river"].neighbors
    a.location = a.home
    ops.mint(w, a.inventory, "wood", 10)
    ops.mint(w, a.inventory, "stone", 4)
    a.busy_until, a.task = w.tick, None
    step(w, {"Anna": ("start_building", {"kind": "house"})})  # houses go up on a site (construction.py)
    site = next(iter(construction.sites(w)))
    for name, args in [("bring_materials", {"site_id": site, "items": {"wood": 10, "stone": 4}})] + \
            [("construct", {"site_id": site})] * 6:
        a.busy_until, a.task, a.asleep = w.tick, None, False
        step(w, {"Anna": (name, args)})
    assert w.plots[a.home].house == 1


def test_camp_replays_exactly():
    w = world(map={"procedural": True})
    again = engine.new_world(json.loads(json.dumps(w.config)))
    assert again.hash() == w.hash()


def test_start_stage_knob_only_in_survival():
    k = next(k for k in knobs.active() if k["key"] == "start_stage")
    assert k["mode"] == "survival" and [o[0] for o in k["options"]] == progress.stage_ids(knobs.DEFAULT_CONFIG)
    r = knobs.to_run({"mode": "survival", "start_stage": "village"})
    assert r["override"]["progress"] == {"enabled": True, "start_stage": "village"}
    assert progress.stage(engine.new_world(r["override"])) == "village"


def test_camp_has_clay_near_and_no_village_projects():
    w = world()
    assert "clay" in w.locations["mine"].resources and not w.projects
    assert {"contribute", "build_work"} <= set(progress.locked_actions(w))
    t = world("town")
    assert t.projects and "contribute" not in progress.locked_actions(t)


def test_camp_has_wild_grain_and_shows_the_site_price_of_a_house():
    # final run 2026-10-06: no grain anywhere before the market square, and the plot showed the old
    # upgrade_house price (6 wood) while a house site needs the catalog's 8
    from aivillage import plots
    for kw in ({}, {"map": {"procedural": True}}):
        w = world(**kw)
        assert "grain" in w.locations["forest"].resources
    a = w.agents["Anna"]
    a.location = "forest"
    step(w, {"Anna": ("work", {"resource": "grain"})})
    assert a.inventory.get("grain", 0) > 0
    assert plots.observe(w, "Anna")["plot"]["upgrade_house"] is None


def test_map_smithy_is_no_free_forge_in_an_empty_start():
    """Once a yard smithy opened the smith's recipes, the map's Smithy place served everyone for free."""
    from aivillage import crafting
    w = world()
    construction.place(w, "smithy", "home_Boris")
    step(w, {})
    assert progress.unlocked(w, "recipe:iron")
    assert crafting.workshops_at(w, "smithy") == []
    assert crafting.workshops_at(w, "home_Boris")[0]["owner"] == "Boris"
    assert crafting.workshops_at(world("village"), "smithy")[0]["kind"] == "smithy"  # a ready village keeps it
