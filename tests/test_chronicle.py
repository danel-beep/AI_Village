"""Visible wealth and the weekly village chronicle (aivillage/chronicle.py)."""

import pytest

from aivillage import chronicle, engine, ops
from aivillage.invariants import check
from aivillage.llm import world_facts

CFG = {"seed": 1, "crises": {"enabled": False}, "labor": {"enabled": True}, "places": {"enabled": True},
       "chronicle": {"enabled": True}}


@pytest.fixture
def w():
    return engine.new_world(CFG)


def step(w, decisions=None):
    events = engine.step(w, {n: {"action": {"name": a, "args": args}} for n, (a, args) in (decisions or {}).items()})
    check(w)
    return events


def until_day(w, day):
    events = []
    while w.day < day:
        events += step(w)
    return events


def test_wealth_levels():
    cfg = engine.new_world(CFG).config
    assert chronicle.level(cfg, 0) == "poor" and chronicle.level(cfg, 50) == "modest"
    assert chronicle.level(cfg, 150) == "well-off" and chronicle.level(cfg, 400) == "rich"


def test_worth_includes_chest(w):
    before = chronicle.worth(w, "Anna")
    chest = w.chests["chest_Anna"]
    ops.mint_coins(w, chest, 30)
    ops.mint(w, chest.items, "tool", 1)
    assert chronicle.worth(w, "Anna") == before + 30 + w.config["items"]["tool"]["value"]
    assert engine.observe(w, "Boris")["wealth"]["Anna"] == chronicle.level(w.config, before + 30 + 20)


def test_weekly_report(w):
    chronicle.earned(w, w.agents["Anna"], 40)
    chronicle.earned(w, w.agents["Clara"], 90)
    chronicle.earned(w, w.agents["Dmitri"], 30)
    events = until_day(w, 8)
    reports = [e for e in events if e.kind == "chronicle"]
    assert len(reports) == 1 and reports[0].visibility == "public"
    text = reports[0].text
    assert "days 1-7" in text and "Lost their place:" in text and "Wealth:" in text
    assert "farmer 40 (1)" in text and "woodcutter 90 (1)" in text and "miner 30 (1)" in text
    assert not w.chronicle["earned"]
    assert engine.observe(w, "Clara")["last_chronicle"] == text
    assert not [e for e in until_day(w, 14) if e.kind == "chronicle"]
    assert [e for e in until_day(w, 15) if e.kind == "chronicle"]


def test_selling_counts_earnings(w):
    a = w.agents["Boris"]
    a.location = "market"
    ops.mint(w, a.inventory, "fish", 3)
    before = a.coins
    step(w, {"Boris": ("sell", {"item": "fish", "qty": 3})})
    assert w.chronicle["earned"]["fisher"]["Boris"] == a.coins - before > 0


def test_off_by_default():
    w = engine.new_world({"seed": 1})
    assert "wealth" not in engine.observe(w, "Anna")
    assert "village chronicle" not in world_facts(w.config)
    assert "village chronicle" in world_facts(engine.new_world(CFG).config)
