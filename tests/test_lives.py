"""Lives: with death_mode "hospital" the collapse number `lives` is death (runs default to 2)."""

from aivillage import engine, graves, llm, modes
from aivillage.invariants import check

NO_RANDOM = {"seed": 1, "crises": {"enabled": False}, "illness": {"per_day": 0.0}}


def collapse(w, name):
    w.agents[name].health = 0
    events = engine.step(w, {})
    check(w)
    return events


def discharge(w, name):
    while w.agents[name].status == "hospital":
        engine.step(w, {})
    check(w)


def test_runs_default_to_two_lives_and_the_engine_to_none():
    assert engine.new_world({"seed": 1}).config["lives"] == 0
    for mode in modes.MODES:
        assert engine.new_world(modes.world_override(mode, {"seed": 1})).config["lives"] == 2


def test_second_collapse_is_death():
    w = engine.new_world({**NO_RANDOM, "lives": 2})
    obs = engine.observe(w, "Anna", consume_inbox=False)["you"]
    assert obs["hospital_stays"] == 0 and obs["hospital_stays_left"] == 1
    ev = collapse(w, "Anna")
    assert w.agents["Anna"].status == "hospital" and w.agents["Anna"].hospital_stays == 1
    assert any(e.kind == "hospital" for e in ev)
    discharge(w, "Anna")
    obs = engine.observe(w, "Anna", consume_inbox=False)["you"]
    assert obs["hospital_stays"] == 1 and obs["hospital_stays_left"] == 0
    ev = collapse(w, "Anna")
    assert w.agents["Anna"].status == "dead" and any(e.kind == "death" for e in ev)
    assert [g["name"] for g in w.graves] == ["Anna"]
    for _ in range(40):  # the dead stay out of the game
        engine.step(w, {})
    assert w.agents["Anna"].status == "dead"


def test_three_lives_and_unlimited():
    w = engine.new_world({**NO_RANDOM, "lives": 3})
    for _ in range(2):
        collapse(w, "Anna")
        discharge(w, "Anna")
    collapse(w, "Anna")
    assert w.agents["Anna"].status == "dead"
    w = engine.new_world({**NO_RANDOM, "lives": 0})
    for _ in range(3):
        collapse(w, "Anna")
        discharge(w, "Anna")
    assert w.agents["Anna"].hospital_stays == 3 and "hospital_stays" not in engine.observe(w, "Anna")["you"]


def test_without_an_heir_the_land_is_nobodys():
    w = engine.new_world({**NO_RANDOM, "death_mode": "death"})
    land = [h for h, p in w.plots.items() if p.owner == "Anna"]
    chest = w.chests["chest_Anna"].coins
    ev = collapse(w, "Anna")
    assert land and all(w.plots[h].owner == "" for h in land)
    assert any(e.kind == "land_freed" for e in ev)
    assert w.chests["chest_Anna"].coins == chest  # the chest stays where it is


def test_the_rule_is_a_world_fact():
    cfg = engine.new_world({**NO_RANDOM, "lives": 2}).config
    text = graves.facts(cfg)
    assert "hospital" in text and "once" in text and "die for good" in text and text in llm.world_facts(cfg)
    assert graves.facts({**cfg, "lives": 0}) == ""
