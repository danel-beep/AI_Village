"""Night, cold and winter (aivillage/warmth.py)."""

from aivillage import engine, warmth
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.registry import ACTIONS
from aivillage.run import bots_decider, llm_agents, replay, run
from aivillage.state import World
from test_neutrality import evaluative

WARM = {"enabled": True, "short_health": 6, "short_satiety": 3, "sick_chance": 0.0}


def world(season="summer", **warm):
    return engine.new_world({"seed": 1, "crises": {"enabled": False}, "illness": {"spread_chance": 0.0},
                             "seasons": {"start": season, "length_days": 7},
                             "warmth": {**WARM, **warm}})


def night(w):
    """Run the hours to the next dawn with nobody acting; satiety kept full so only the cold counts."""
    day, events = w.day, []
    while w.day == day:
        for a in w.agents.values():
            a.satiety = 100
        events += engine.step(w, {})
        check(w)
    return events


def test_off_by_default_changes_nothing():
    w = engine.new_world({"seed": 1})
    assert not warmth.enabled(w.config)
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert "warmth" not in obs and "stoke" not in obs["available_actions"]
    assert "stoke" in warmth.hidden(w.config)
    assert next(iter(llm_agents(w, {"Anna": "stub"}).values())).disabled_actions >= {"stoke"}
    assert "Night and cold" not in world_facts(w.config)


def test_summer_roof_is_enough_outdoors_costs_health():
    w = world("summer")
    w.agents["Boris"].location = "square"
    hp = {n: a.health for n, a in w.agents.items()}
    events = night(w)
    cold = [e for e in events if e.kind == "cold_night"]
    assert [e.data["person"] for e in cold] == ["Boris"]
    assert "no roof, no fire" in cold[0].text
    assert w.agents["Boris"].health == hp["Boris"] - 6
    assert w.agents["Anna"].health >= hp["Anna"]


def test_winter_hearth_needs_wood_and_stoke_fills_it():
    w = world("winter")
    anna, boris = w.agents["Anna"], w.agents["Boris"]
    anna.inventory["wood"] = anna.inventory.get("wood", 0) + 5
    w.ledger["wood"] = w.ledger.get("wood", 0) + 5
    ctx = engine.Ctx(w, engine.rng_for(w))
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert obs["warmth"] == {"night_warmth_needed": 2, "wood_a_fire_burns_tonight": 2,
                             "here": {"roof": True, "fireplace": True, "fire_wood": 0}}
    assert "stoke" in obs["available_actions"]
    ACTIONS.run(ctx, anna, "stoke", {"wood": 3})
    assert w.warmth["fuel"][anna.home] == 3 and w.ledger["wood"] == sum(
        a.inventory.get("wood", 0) for a in w.agents.values()) + sum(c.items.get("wood", 0) for c in w.chests.values())
    check(w)
    events = night(w)
    cold = {e.data["person"]: e for e in events if e.kind == "cold_night"}
    assert "Anna" not in cold  # roof + a fire with wood
    assert "the fire had too little wood" in cold["Boris"].text and cold["Boris"].data["short"] == 1
    assert w.warmth["fuel"][anna.home] == 1  # 2 burned
    events = night(w)  # 1 wood left: not enough for a winter night
    assert "Anna" in {e.data["person"] for e in events if e.kind == "cold_night"}
    assert anna.home not in w.warmth["fuel"] or w.warmth["fuel"][anna.home] == 1
    assert boris.status == "active"


def test_stoke_refused_without_fireplace_or_wood():
    w = world("winter")
    a = w.agents["Anna"]
    ctx = engine.Ctx(w, engine.rng_for(w))
    a.inventory.pop("wood", None)
    assert "stoke" not in engine.observe(w, "Anna", consume_inbox=False)["available_actions"]
    a.location = "square"
    a.inventory["wood"] = 2
    w.ledger["wood"] = w.ledger.get("wood", 0) + 2
    try:
        ACTIONS.run(ctx, a, "stoke", {"wood": 1})
        raise AssertionError("stoked without a fireplace")
    except Exception as e:
        assert "no fireplace" in str(e)


def test_shared_campfire_warms_everyone_whoever_stoked():
    w = world("winter", campfires=["square"])
    for n in ("Anna", "Boris"):
        w.agents[n].location = "square"
    w.agents["Anna"].inventory["wood"] = 2
    w.ledger["wood"] = w.ledger.get("wood", 0) + 2
    ACTIONS.run(engine.Ctx(w, engine.rng_for(w)), w.agents["Anna"], "stoke", {"wood": 2})
    cold = {e.data["person"]: e.data["short"] for e in night(w) if e.kind == "cold_night"}
    assert cold.get("Anna") == 1 and cold.get("Boris") == 1  # fire, but no roof


def test_cold_winter_night_can_make_ill():
    w = world("winter", sick_chance=1.0)
    w.agents["Boris"].location = "square"
    events = night(w)
    assert any(e.kind == "sick" and e.data.get("cause") == "cold" and e.data["person"] == "Boris" for e in events)


def test_facts_and_bots_keep_invariants_and_replay(tmp_path):
    w = engine.new_world({"seed": 2, "seasons": {"start": "autumn", "length_days": 2}, "warmth": {"enabled": True}})
    facts = world_facts(w.config)
    assert "Night and cold" in facts and "stoke" in facts
    assert evaluative(facts) == []
    kinds, texts = [], []
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["worker", "trader", "random"], 2), days=4, log_path=log,
        on_tick=lambda world, ev: (check(world), kinds.extend(e.kind for e in ev), texts.extend(e.text for e in ev)))
    assert "stoke" in kinds and "cold_night" in kinds
    assert evaluative(" ".join(texts)) == []
    assert replay(log).hash() == w.hash()
    assert World.from_dict(w.to_dict()).hash() == w.hash()
