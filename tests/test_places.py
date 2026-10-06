"""Trade places, change_trade and losing a place (aivillage/places.py)."""

import pytest

from aivillage import engine, ops, places
from aivillage.invariants import check
from aivillage.llm import world_facts

CFG = {"seed": 1, "crises": {"enabled": False}, "labor": {"enabled": True}, "places": {"enabled": True}}


@pytest.fixture
def w():
    return engine.new_world(CFG)


def step(w, decisions=None):
    events = engine.step(w, {n: {"action": {"name": a, "args": args}} for n, (a, args) in (decisions or {}).items()})
    check(w)
    return events


def act(w, name, action, **args):
    return step(w, {name: (action, args)})


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def until_day(w, day):
    events = []
    while w.day < day:
        events += step(w)
    return events


def test_capacity_scales_with_population():
    big = engine.new_world({**CFG, "population": {"size": 20}})
    caps = {p: places.capacity(big.config, p) for p in places.trades(big.config)}
    assert caps == {"farmer": 6, "fisher": 6, "woodcutter": 5, "miner": 5, "smith": 3}
    small = engine.new_world(CFG)
    assert places.capacity(small.config, "smith") == 1 and places.capacity(small.config, "farmer") == 2


def test_change_trade_takes_a_free_place(w):
    a = w.agents["Anna"]  # farmer
    a.location = "square"
    a.skill_hours = 20
    assert not errors(act(w, "Anna", "change_trade", profession="fisher"))
    assert a.profession == "fisher" and a.skill_hours == 0 and a.trade_since_day == w.day
    err = errors(act(w, "Anna", "change_trade", profession="woodcutter"))
    assert err and "you can change it from day" in err[0]
    w.agents["Boris"].location = "square"  # fisher: the 2 fisher places are Boris and Anna now
    w.agents["Clara"].location = "square"
    err = errors(act(w, "Clara", "change_trade", profession="fisher"))
    assert err and "places are taken" in err[0]
    assert "no such trade" in errors(act(w, "Clara", "change_trade", profession="king"))[0]


def test_idle_villager_loses_place(w):
    events = until_day(w, 5)  # nobody works: on the dawn of day 5 everyone has been idle for 4 days
    lost = [e for e in events if e.kind == "place_lost"]
    assert {e.data["person"] for e in lost} == set(w.agents)
    assert all(a.profession == places.LABORER for a in w.agents.values())
    a = w.agents["Boris"]
    a.location = "river"
    err = errors(act(w, "Boris", "work", hours=1, resource="fish"))
    assert err and "only a fisher" in err[0]
    a.location = "square"
    assert not errors(act(w, "Boris", "change_trade", profession="fisher"))  # a laborer has no cooldown


def test_work_at_the_trade_keeps_the_place(w):
    b = w.agents["Boris"]
    for day in range(2, 7):
        until_day(w, day)
        b.trade_day = w.day
    assert b.profession == "fisher"
    assert w.agents["Anna"].profession == places.LABORER


def test_gathering_and_crafting_count_as_work(w):
    b = w.agents["Boris"]
    b.location = "river"
    assert not errors(act(w, "Boris", "work", hours=1, resource="fish"))
    assert b.trade_day == w.day
    smith = next(a for a in w.agents.values() if a.profession == "smith")
    smith.location = "smithy"
    ops.mint(w, smith.inventory, "wood", 2)
    ops.mint(w, smith.inventory, "ore", 1)
    until_day(w, 2)
    assert not errors(act(w, smith.name, "craft", recipe="tool"))
    assert smith.trade_day == 2


def test_revoke_place_law(w):
    w.governance.mayor = "Anna"
    assert not errors(act(w, "Anna", "propose_law", law="revoke_place", person="Boris"))
    pid = next(iter(w.governance.proposals))
    events = step(w, {n: ("vote_law", {"proposal_id": pid, "vote": "yes"}) for n in w.agents})
    assert w.agents["Boris"].profession == places.LABORER
    assert any(e.kind == "place_lost" and "taken by law" in e.text for e in events)


def test_facts_and_observation(w):
    assert "Trade places" in world_facts(w.config)
    obs = engine.observe(w, "Anna")
    assert obs["trade_places"]["farmer"] == {"places": 2, "taken": 1}
    assert obs["your_place"]["trade"] == "farmer"
    off = engine.new_world({"seed": 1})
    assert "Trade places" not in world_facts(off.config)
    w.governance.mayor = "Anna"
    off.governance.mayor = "Anna"
    assert "no places" in errors(act(off, "Anna", "propose_law", law="revoke_place", person="Boris"))[0]
