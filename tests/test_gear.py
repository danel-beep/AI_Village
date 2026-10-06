"""Weapon tiers, armor and wear (combat.gear in aivillage/conflict.py, «С нуля» plan task 9)."""

import json

import pytest

from aivillage import animals, conflict, engine, modes, ops, runconfig, threats
from aivillage.config import make_config
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.ops import Ctx
from aivillage.registry import ACTIONS
from aivillage.run import bots_decider, replay, run

from test_neutrality import evaluative

CFG = {"seed": 1, "crises": {"enabled": False}, "crafting": {"enabled": True}}


@pytest.fixture
def w():
    return engine.new_world(CFG)


def ctx(w):
    return Ctx(w, engine.rng_for(w))


def give(w, name, **items):
    for k, n in items.items():
        ops.mint(w, w.agents[name].inventory, k, n)


def test_off_without_crafting_changes_nothing():
    base = make_config({"seed": 1})
    assert not conflict.gear_on(base)
    assert conflict.weapons(base) == base["combat"]["weapons"]
    assert "bow" not in base["items"] and base["recipes"]["spear"]["inputs"] == {"wood": 2, "ore": 1}
    w = engine.new_world({"seed": 1})
    give(w, "Anna", club=1)
    assert conflict.observe(w, "Anna") == {} and conflict.seen_gear(w.config, w.agents["Anna"]) == {}
    assert conflict.gear_facts(w.config) == [] and "Armor" not in world_facts(w.config)
    obs = engine.observe(w, "Boris")
    assert all("gear" not in p for p in obs["here"]["people"])


def test_survival_mode_has_gear_and_recipes():
    cfg = make_config(runconfig.RunConfig(mode="survival").world_override())
    assert conflict.gear_on(cfg)
    r = cfg["recipes"]
    assert r["spear"]["building"] == "workbench" and r["spear"]["profession"] is None
    assert r["bow"]["building"] == "workbench" and r["leather_armor"]["building"] == "workbench"
    assert r["sword"]["building"] == "smithy" and r["iron_armor"]["building"] == "smithy"
    assert {"bow", "sword", "leather_armor", "iron_armor"} <= set(cfg["items"])
    assert not conflict.gear_on(make_config(modes.world_override("crafts")))


def test_weapon_tiers(w):
    a = w.agents["Anna"]
    for item in ("club", "spear", "sword"):
        give(w, "Anna", **{item: 1})
        assert conflict.weapon(w.config, a)[0] == item
    give(w, "Boris", spear=1, bow=1)
    b = w.agents["Boris"]
    assert conflict.weapon(w.config, b)[0] == "spear"       # in a fight the spear hits harder
    item, atk, dmg = conflict.hunt_weapon(w.config, b)    # on a hunt the bow aims better
    assert (item, atk, dmg) == ("bow", 6, 3)


def test_armor_blocks_and_wears_out(w):
    c = ctx(w)
    a = w.agents["Anna"]
    give(w, "Anna", leather_armor=1, iron_armor=1)
    assert conflict.armor(w.config, a) == ("iron_armor", 4)
    assert conflict.soak(c, a, 7) == 3 and conflict.soak(c, a, 2) == 1 and conflict.soak(c, a, 0) == 0
    assert a.tool_wear_by["iron_armor"] == 2
    for _ in range(28):
        conflict.soak(c, a, 5)
    assert ops.count(a.inventory, "iron_armor") == 0 and "iron_armor" not in a.tool_wear_by
    assert any(e.kind == "gear_broke" and e.data["item"] == "iron_armor" for e in c.events)
    assert conflict.armor(w.config, a) == ("leather_armor", 2)
    check(w)


def test_fight_uses_gear_and_shows_it(w):
    a, b = w.agents["Anna"], w.agents["Boris"]
    b.location = a.location
    give(w, "Anna", sword=1)
    give(w, "Boris", club=1, iron_armor=1)
    obs = engine.observe(w, "Anna")
    seen = {p["name"]: p.get("gear") for p in obs["here"]["people"]}
    assert seen["Boris"] == {"weapon": "club", "armor": "iron_armor"}
    assert obs["your_gear"] == {"weapon": "sword (30 of 30 uses left)"}
    c = ctx(w)
    ACTIONS.run(c, a, "attack", {"target": "Boris"})
    fight = next(e for e in c.events if e.kind == "fight")
    assert fight.data["weapons"] == {"Anna": "sword", "Boris": "club"}
    assert fight.data["armor"] == {"Anna": None, "Boris": "iron_armor"}
    assert "in iron_armor" in fight.text
    assert a.tool_wear_by["sword"] == 1 and b.tool_wear_by["club"] == 1
    hits_on_boris = sum(1 for r in fight.data["rounds"] if r["by"] == "Anna" and r["hit"])
    assert b.tool_wear_by.get("iron_armor", 0) == hits_on_boris
    check(w)


def test_defend_uses_armor_and_weapon(w):
    a = w.agents["Anna"]
    give(w, "Anna", spear=1, leather_armor=1)
    c = ctx(w)
    w.threats.append({"id": "t1", "kind": "beast", "name": "beast", "state": "here", "warned": False, "cause": "god",
                      "arrive_tick": 0, "arrive_day": 1, "arrive_hour": 8, "target": a.home, "location": a.location,
                      "route": [], "hp": 500, "max_hp": 500, "hours_left": 5, "fought": False, "fighters": {},
                      "loot": {}, "loot_coins": 0, "scout": False, "fed": {}})
    ACTIONS.run(c, a, "defend", {})
    assert a.tool_wear_by["spear"] == 1


def test_facts_are_neutral():
    cfg = make_config(runconfig.RunConfig(mode="survival").world_override())
    lines = conflict.gear_facts(cfg)
    assert len(lines) == 3 and "bow +5" in lines[0] and "iron_armor -4" in lines[1]
    assert evaluative("\n".join(lines)) == []
    assert "sword +3 to hit/+7 damage" in conflict.facts(cfg)


def test_hunters_and_thieves_with_gear_replay_exactly(tmp_path):
    cfg = {**CFG, "seed": 5, "animals": {"enabled": True},
           "start_items": {**make_config({})["start_items"], "bow": 1, "spear": 1, "leather_armor": 1, "plank": 2,
                           "hide": 2}}
    w = engine.new_world(cfg)
    bots = bots_decider(w, ["hunter", "hunter", "hunter", "thief", "worker"], 5)
    found = set()

    def decide(name, obs, _bots=bots):
        found.update(evaluative(json.dumps(obs)))
        return _bots(name, obs)
    decide.bots = bots.bots
    log = tmp_path / "run.jsonl"
    run(w, decide, days=3, log_path=log)
    assert found == set()
    assert replay(log).hash() == w.hash()
    seen = log.read_text()
    assert '"hunt_' in seen and ('"bow"' in seen or '"spear"' in seen)
