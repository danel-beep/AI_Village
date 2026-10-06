"""Food that goes bad (aivillage/spoilage.py)."""

import pytest

from aivillage import engine, ops, spoilage
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.state import World

CFG = {"seed": 1, "crises": {"enabled": False}, "spoilage": {"enabled": True}}


@pytest.fixture
def w():
    w = engine.new_world(CFG)
    for c in [w.agents["Anna"].inventory] + [c.items for c in w.chests.values() if c.owner == "Anna"]:
        for item in list(c):
            if item in w.config["spoilage"]["days"]:
                ops.burn(w, c, item, c[item])
    return w


def until_day(w, day):
    events = []
    while w.day < day:
        for a in w.agents.values():  # nobody gets hungry enough to eat what we count
            a.satiety, a.health = 100, 100
        events += engine.step(w, {})
        check(w)
    return events


def held(w, name, item):
    return sum(ops.count(s, item) for s in spoilage._stores(w, name))


def test_reconcile_oldest_first():
    assert spoilage.reconcile([[3, 2], [4, 5]], 4, 6) == [[4, 4]]
    assert spoilage.reconcile([[3, 2]], 5, 6) == [[3, 2], [6, 3]]
    assert spoilage.reconcile([], 0, 6) == []


def test_fish_keeps_two_days_grain_longer(w):
    ops.mint(w, w.agents["Anna"].inventory, "fish", 4)
    ops.mint(w, w.agents["Anna"].inventory, "grain", 4)
    until_day(w, 2)
    assert held(w, "Anna", "fish") == 4
    assert engine.observe(w, "Anna")["spoils_next_dawn"] == {"fish": 4}
    assert w.spoilage["Anna"]["fish"] == [[3, 4]]
    assert World.from_dict(w.to_dict()).hash() == w.hash()  # saves and replay keep the batches
    events = until_day(w, 3)
    assert held(w, "Anna", "fish") == 0 and held(w, "Anna", "grain") == 4
    bad = [e for e in events if e.kind == "spoiled"]
    assert bad and bad[0].to == ["Anna"] and bad[0].data["items"] == {"fish": 4}
    assert "fish" not in engine.observe(w, "Anna")["spoils_next_dawn"]


def test_chest_does_not_refresh(w):
    a = w.agents["Anna"]
    chest = next(c for c in w.chests.values() if c.owner == "Anna")
    ops.mint(w, a.inventory, "fish", 3)
    until_day(w, 2)
    ops.move_items(a.inventory, chest.items, {"fish": 3})  # same store: age kept
    ops.mint(w, a.inventory, "fish", 1)  # new today: keeps its own days
    until_day(w, 3)
    assert held(w, "Anna", "fish") == 1 and ops.count(chest.items, "fish") == 0


def test_used_food_leaves_oldest_first(w):
    a = w.agents["Anna"]
    ops.mint(w, a.inventory, "fish", 3)
    until_day(w, 2)
    ops.mint(w, a.inventory, "fish", 2)
    hour = w.hour
    while w.hour == hour:
        engine.step(w, {})
    ops.burn(w, a.inventory, "fish", 2)  # ate two an hour later: the old ones go first
    until_day(w, 3)
    assert held(w, "Anna", "fish") == 2  # one old spoiled, the two from day 2 are left
    until_day(w, 4)
    assert held(w, "Anna", "fish") == 0


def test_off_by_default_and_facts():
    w = engine.new_world({"seed": 1, "crises": {"enabled": False}})
    ops.mint(w, w.agents["Anna"].inventory, "fish", 2)
    until_day(w, 5)
    assert ops.count(w.agents["Anna"].inventory, "fish") == 2
    assert "spoils_next_dawn" not in engine.observe(w, "Anna")
    assert "goes bad" not in world_facts(w.config)
    assert "goes bad" in world_facts(engine.new_world(CFG).config)


def test_texts_are_neutral(w):
    from tests.test_neutrality import evaluative
    ops.mint(w, w.agents["Anna"].inventory, "fish", 2)
    events = until_day(w, 3)
    texts = [world_facts(w.config)] + [e.text for e in events if e.kind == "spoiled"]
    assert len(texts) == 2 and all(evaluative(t) == [] for t in texts)
