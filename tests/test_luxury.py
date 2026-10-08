"""Feasts and goods on view (aivillage/luxury.py)."""

import pytest

from aivillage import engine, family, luxury, modes, ops
from aivillage.invariants import check


@pytest.fixture
def w():
    w = engine.new_world({"seed": 1, "luxury": {"enabled": True}})
    for a in w.agents.values():
        a.location, a.asleep, a.satiety = "square", False, 40
    return w


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def test_feast_shares_food_and_warms_guests(w):
    host = w.agents["Anna"]
    ops.mint(w, host.inventory, "bread", 3)
    guests = [o for o in w.agents.values() if o.name != "Anna"]
    ev = act(w, "Anna", "host_feast", items={"bread": 3})
    assert not errors(ev)
    each = 3 * w.config["items"]["bread"]["food"] // len(w.agents)
    assert ops.count(host.inventory, "bread") == 0 and host.feast_day == w.day
    assert len({o.satiety for o in guests}) == 1 and guests[0].satiety > 40  # minus the hour's hunger
    assert all(family.feeling(w, o.name, "Anna") == w.config["family"]["on_event"]["feast"][1] for o in guests)
    feast = next(e for e in ev if e.kind == "feast")
    assert feast.visibility == "public" and set(feast.to) == {o.name for o in guests}
    assert f"+{each} satiety each" in feast.text
    ops.mint(w, host.inventory, "bread", 3)
    assert "already hosted a feast today" in errors(act(w, "Anna", "host_feast", items={"bread": 3}))[0]


def test_feast_rules_and_failures_change_nothing(w):
    host = w.agents["Anna"]
    ops.mint(w, host.inventory, "bread", 1)
    ops.mint(w, host.inventory, "berries", 1)
    ops.mint(w, host.inventory, "wood", 2)
    assert "not food" in errors(act(w, "Anna", "host_feast", items={"wood": 2}))[0]
    assert "satiety each" in errors(act(w, "Anna", "host_feast", items={"berries": 1}))[0]
    for o in w.agents.values():
        if o.name != "Anna":
            o.location = "market"
    assert "at least 2 awake people" in errors(act(w, "Anna", "host_feast", items={"bread": 1}))[0]
    assert ops.count(host.inventory, "bread") == 1 and host.feast_day == 0


def test_goods_on_view_and_only_where_enabled(w):
    ops.mint(w, w.agents["Boris"].inventory, "ring", 1)
    people = {p["name"]: p for p in engine.observe(w, "Anna", consume_inbox=False)["here"]["people"]}
    assert people["Boris"]["carries"] == {"ring": 1}
    off = engine.new_world({"seed": 1})
    assert "host_feast" not in engine.observe(off, "Anna", consume_inbox=False)["available_actions"]
    assert modes.trades_override()["luxury"]["enabled"] and luxury.facts(w.config)
