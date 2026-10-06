"""Crafting chains, workshops and tools (aivillage/crafting.py)."""

import json

import pytest

from aivillage import crafting, engine, ops, progress
from aivillage.config import make_config
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.registry import ACTIONS, ActionError
from aivillage.ops import Ctx
from aivillage.run import bots_decider, replay, run

from test_neutrality import evaluative

SHOPS = {k: {"cells": 1, "coins": 0, "items": {}} for k in ("workbench", "smithy", "kiln", "mill", "tannery", "smokehouse", "campfire")}
CFG = {"seed": 1, "crises": {"enabled": False}, "crafting": {"enabled": True},
       "plots": {"buildings": SHOPS}}


@pytest.fixture
def w():
    return engine.new_world(CFG)


def act(w, name, action, **args):
    ACTIONS.run(Ctx(w, engine.rng_for(w)), w.agents[name], action, args)
    check(w)


def give(w, name, **items):
    for k, n in items.items():
        ops.mint(w, w.agents[name].inventory, k, n)


def clear(w, name):
    inv = w.agents[name].inventory
    for k in list(inv):
        ops.burn(w, inv, k, inv[k])


def add_shop(w, owner, kind):
    plot = w.plots[w.agents[owner].home]
    plot.buildings.append({"id": f"{kind}1", "kind": kind, "built_day": 1, "items": {}})


def test_off_changes_nothing():
    base = make_config({"seed": 1})
    assert "plank" not in base["recipes"] and base["recipes"]["bread"]["inputs"].get("grain")
    w = engine.new_world({"seed": 1})
    assert crafting.observe(w, "Anna") == {}
    assert "Craft by hand" not in world_facts(w.config)


def test_resolve_merges_once():
    cfg = make_config(CFG)
    r = cfg["recipes"]
    assert r["bread"]["inputs"] == {"flour": 1, "wood": 1} and r["bread"]["where"] == "home"
    assert r["brick"]["building"] == "kiln" and r["brick"]["where"] == "kiln"
    assert r["tool"]["building"] == "smithy"  # legacy "made at the smithy"
    assert r["plank"]["where"] == "anywhere" and "iron_pick" in cfg["items"]
    assert "potter" in cfg["professions"]
    again = make_config(cfg)  # a replayed log header goes through make_config again
    assert again["recipes"] == r


def test_hand_recipe_and_workshop_bonus(w):
    a = w.agents["Anna"]
    clear(w, "Anna")
    give(w, "Anna", wood=4)
    act(w, "Anna", "craft", recipe="plank")
    assert a.inventory.get("plank") == 1
    add_shop(w, "Anna", "workbench")
    a.location = a.home
    act(w, "Anna", "craft", recipe="plank")
    assert a.inventory.get("plank") == 4  # 1 by hand + 3 at a workbench


def test_workshop_needed_and_private(w):
    clear(w, "Boris")
    b = w.agents["Boris"]
    give(w, "Boris", clay=2, wood=1)
    with pytest.raises(ActionError, match="no kiln here"):
        act(w, "Boris", "craft", recipe="brick")
    add_shop(w, "Anna", "kiln")
    b.location = w.agents["Anna"].home
    with pytest.raises(ActionError, match="belongs to Anna"):
        act(w, "Boris", "craft", recipe="brick")
    b.location = b.home
    add_shop(w, "Boris", "kiln")
    act(w, "Boris", "craft", recipe="brick")
    assert b.inventory.get("brick") == 2 and not b.inventory.get("clay")


def test_multi_hour_batch_keeps_crafter_busy(w):
    e = w.agents["Elena"]  # a smith; the smithy is a village location in the classic map
    clear(w, "Elena")
    e.location = "smithy"
    give(w, "Elena", ore=4, wood=2)
    act(w, "Elena", "craft", recipe="iron", times=2)
    assert e.inventory["iron"] == 2 and e.task == {"kind": "craft", "recipe": "iron", "hours_left": 3}
    for _ in range(3):
        crafting.continue_task(Ctx(w, engine.rng_for(w)), e)
    assert e.task is None


def test_campfire_counts_as_home_for_cooking(w):
    clear(w, "Boris")
    b = w.agents["Boris"]
    give(w, "Boris", flour=1, wood=1)
    b.location = "square"
    with pytest.raises(ActionError, match="at your home or by a campfire"):
        act(w, "Boris", "craft", recipe="bread")
    add_shop(w, "Anna", "campfire")
    w.plots[w.agents["Anna"].home].owner = "Anna"
    b.location = w.agents["Boris"].home
    act(w, "Boris", "craft", recipe="bread")
    assert b.inventory["bread"] == 1


def test_tools_speed_up_and_wear_out(w):
    c = w.agents["Clara"]  # woodcutter: 3 wood an hour by hand
    clear(w, "Clara")
    c.location = "forest"
    act(w, "Clara", "work", resource="wood")
    assert c.inventory["wood"] == 3
    give(w, "Clara", stone_axe=1)
    act(w, "Clara", "work", resource="wood")
    assert c.inventory["wood"] == 3 + 5  # x1.5, rounded half up
    give(w, "Clara", iron_axe=1)
    act(w, "Clara", "work", resource="wood")
    assert c.inventory["wood"] == 8 + 8  # the best tool is used: x2.5
    assert c.tool_wear_by == {"stone_axe": 1, "iron_axe": 1}
    c.tool_wear_by["iron_axe"] = crafting.durability(w.config, "iron_axe") - 1
    c.worked_today = 0
    act(w, "Clara", "work", resource="wood")
    assert "iron_axe" not in c.inventory and "iron_axe" not in c.tool_wear_by


def test_ore_needs_a_pick(w):
    d = w.agents["Dmitri"]
    clear(w, "Dmitri")
    d.location = "mine" if "mine" in w.locations and "ore" in w.locations["mine"].resources else \
        next(l for l, loc in w.locations.items() if "ore" in loc.resources)
    with pytest.raises(ActionError, match="not gathered by hand"):
        act(w, "Dmitri", "work", resource="ore")
    give(w, "Dmitri", wood=1, stone=2)
    act(w, "Dmitri", "craft", recipe="stone_pick")
    act(w, "Dmitri", "work", resource="ore")
    assert d.inventory.get("ore", 0) > 0


def test_owner_takes_the_trade(w):
    a = w.agents["Anna"]
    a.profession = "laborer"
    add_shop(w, "Anna", "smithy")
    w.agents["Boris"].profession = "fisher"
    add_shop(w, "Boris", "kiln")
    ctx = Ctx(w, engine.rng_for(w))
    crafting.end_of_hour(ctx)
    assert a.profession == "smith" and w.agents["Boris"].profession == "fisher"
    assert any(e.kind == "trade_changed" and e.actor == "Anna" for e in ctx.events)


def test_progress_locks_workshop_recipes():
    w = engine.new_world({**CFG, "progress": {"enabled": True}})
    assert not progress.unlocked(w, "recipe:iron_pick") and progress.unlocked(w, "recipe:stone_axe")
    e = w.agents["Elena"]
    e.location = "smithy"
    give(w, "Elena", plank=1, iron=2)
    with pytest.raises(ActionError, match="nobody in the village can make iron_pick yet"):
        act(w, "Elena", "craft", recipe="iron_pick")


def test_observation_and_facts(w):
    give(w, "Elena", stone_pick=1)
    w.agents["Elena"].location = "smithy"
    obs = engine.observe(w, "Elena", consume_inbox=False)
    assert "stone_pick" in obs["tools"]
    assert obs["workshops_here"][0]["kind"] == "smithy" and "iron" in obs["crafts_here"]
    facts = world_facts(w.config)
    assert "Craft at a workshop" in facts and "brick" in facts
    assert evaluative(facts + json.dumps(obs)) == []


def test_bots_run_with_crafting_is_exact_and_neutral(tmp_path):
    w = engine.new_world({**CFG, "seed": 3})
    bots = bots_decider(w, ["random", "worker"], 3)
    found = set()

    def decide(name, obs, _bots=bots):
        found.update(evaluative(json.dumps(obs)))
        return _bots(name, obs)
    decide.bots = bots.bots
    log = tmp_path / "run.jsonl"
    run(w, decide, days=3, log_path=log)
    assert found == set()
    assert replay(log).hash() == w.hash()


def test_constructed_workshops_count(w):
    w.construction = {"buildings": [{"id": "b1", "kind": "kiln", "level": 1, "location": "square", "owner": "Boris",
                                     "built_day": 1}]}
    here = crafting.workshops_at(w, "square")
    assert here == [{"kind": "kiln", "owner": "Boris", "level": 1, "users": ["Boris"]}]
    assert ("Boris", "kiln") in crafting.owned_workshops(w)
