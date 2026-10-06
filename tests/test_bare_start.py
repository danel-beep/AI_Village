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
