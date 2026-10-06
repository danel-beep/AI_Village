"""Building catalog and levels (survival plan task 10): workshops, pen, stone wall, crafted materials."""

import json
import random

from test_construction import act, errors, give, site_of, world
from test_neutrality import evaluative

from aivillage import construction, engine, llm, ops, progress, works
from aivillage.invariants import check
from aivillage.run import bots_decider, replay, run

CRAFT = {"crafting": {"enabled": True}}


def test_catalog_size_and_known_materials():
    w = world(CRAFT)
    cat = construction.catalog(w.config)
    assert len(cat) >= 17
    for kind in ("kiln", "mill", "tannery", "weaving_shed", "pen", "wall"):
        assert kind in cat
    known = set(w.config["items"])
    for kind, spec in cat.items():
        for row in spec["levels"]:
            assert set(row.get("items", {})) <= known, kind
    # every workshop a recipe needs can be built
    for rid, r in w.config["recipes"].items():
        for k in [r.get("building"), *r.get("more_at", {})]:
            assert k is None or k in cat or k in w.locations, (rid, k)


def test_crafted_materials_are_asked_raw_without_crafting():
    raw, crafted = world(), world(CRAFT)
    row = construction.catalog(raw.config)["house"]["levels"][1]
    assert construction.level_items(raw.config, row) == {"wood": 12, "stone": 10}
    assert construction.level_items(crafted.config, row) == {"plank": 6, "stone": 10}
    row = construction.catalog(raw.config)["kiln"]["levels"][0]
    assert construction.level_items(raw.config, row) == {"stone": 16}
    act(crafted, "Anna", "start_building", kind="house")
    assert site_of(crafted, "house")["needs"] == {"plank": 6, "stone": 10}


def test_higher_level_workshop_adds_to_each_batch():
    w = world(CRAFT)
    construction.place(w, "workbench", "home_Anna", 1)
    w.agents["Anna"].location = "home_Anna"
    give(w, "Anna", wood=4)
    assert not errors(act(w, "Anna", "craft", recipe="plank"))
    assert ops.count(w.agents["Anna"].inventory, "plank") == 3
    construction.place(w, "workbench", "home_Anna", 2)
    events = act(w, "Anna", "craft", recipe="plank")
    assert not errors(events) and any(e.kind == "workshop_bonus" for e in events)
    assert ops.count(w.agents["Anna"].inventory, "plank") == 3 + 4
    # someone else's workshop gives nothing to a stranger (and the recipe itself works by hand)
    w.agents["Boris"].location = "home_Anna"
    give(w, "Boris", wood=2)
    events = act(w, "Boris", "craft", recipe="plank")
    assert not any(e.kind == "workshop_bonus" for e in events)


def test_clothes_need_a_weaving_shed():
    w = world(CRAFT)
    w.agents["Anna"].location = "home_Anna"
    give(w, "Anna", leather=2)
    assert "weaving_shed" in errors(act(w, "Anna", "craft", recipe="clothes"))[0]
    construction.place(w, "weaving_shed", "home_Anna", 1)
    assert not errors(act(w, "Anna", "craft", recipe="clothes"))
    assert ops.count(w.agents["Anna"].inventory, "clothes") == 1


def test_pen_makes_food_when_fed_and_level_two_makes_more():
    w = world()
    construction.place(w, "pen", "home_Anna", 1)
    pen = next(b for b in w.plots["home_Anna"].buildings if b["kind"] == "pen")
    chest = w.chests["chest_Anna"]
    chest.items.pop("grain", None)
    ctx = ops.Ctx(w, random.Random(0))
    construction.after_night(ctx)
    assert pen["items"] == {} and any(e.kind == "hungry_animals" for e in ctx.events)
    ops.mint(w, chest.items, "grain", 5)
    construction.after_night(ctx)
    assert pen["items"] == {"egg": 2} and ops.count(chest.items, "grain") == 4
    construction.place(w, "pen", "home_Anna", 2)
    construction.after_night(ctx)
    assert pen["items"] == {"egg": 4, "milk": 3} and ops.count(chest.items, "grain") == 2
    check(w)
    w.agents["Anna"].location = "home_Anna"
    assert not errors(act(w, "Anna", "collect"))
    assert ops.count(w.agents["Anna"].inventory, "milk") >= 3


def test_wall_needs_a_stone_palisade_and_defends_more():
    w = world(progress={"enabled": True, "start_stage": "town"})
    assert not progress.unlocked(w, "building:wall")
    construction.place(w, "palisade", "square", 2)
    assert progress.unlocked(w, "building:wall")
    before = works.defense(w)
    construction.place(w, "wall", "square", 1)
    assert works.defense(w) == before + 3
    assert "defense +5" in construction.effect_text(w.config, "wall", 2)


def test_survival_mode_fuzz_and_replay(tmp_path):
    for seed in range(2):
        w = engine.new_world({**CRAFT, "seed": seed, "construction": {"enabled": True},
                              "progress": {"enabled": True, "start_stage": "village"},
                              "start_items": {"wood": 20, "stone": 20, "plank": 10, "brick": 10}})
        log = tmp_path / f"run{seed}.jsonl"
        bots = bots_decider(w, ["random", "worker", "random"], seed)
        found = set()

        def decide(name, obs, _bots=bots):
            found.update(evaluative(json.dumps(obs)))
            return _bots(name, obs)
        decide.bots = bots.bots
        run(w, decide, days=3, log_path=log)
        check(w)
        assert found == set()
        assert replay(log).hash() == w.hash()
    assert evaluative(llm.world_facts(w.config)) == []
