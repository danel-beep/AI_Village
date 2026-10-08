"""Trader prices that follow his stock (pricing.py), worn tools, multi-trade dishes and gold's uses."""

import pytest

from aivillage import engine, knobs, ops, plots
from aivillage.config import make_config
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.modes import trades_override


def crafts_world(**extra):
    return engine.new_world({**trades_override(), "seed": 1, "crises": {"enabled": False}, **extra})


@pytest.fixture
def w():
    return crafts_world()


def gift(w, name, **items):
    for k, v in items.items():
        ops.mint(w, w.agents[name].inventory, k, v)


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def price(w, item, side):
    return engine.observe(w, "Anna")["board"]["trader_prices"][item][side]


def until_morning(w):
    day = w.day
    while w.day == day:
        engine.step(w, {})
    check(w)


def test_trader_pays_less_the_more_he_holds(w):
    dmitri = w.agents["Dmitri"]
    dmitri.location = "market"
    gift(w, "Dmitri", stone=10)
    first = price(w, "stone", "sell")
    before = price(w, "gold", "sell")
    act(w, "Dmitri", "sell", item="stone", qty=5)
    assert w.trader_stock["stone"] == 5
    assert price(w, "gold", "sell") == before  # other goods keep their price
    later = engine.observe(w, "Anna")["board"]["trader_prices"]["stone"]
    assert later["buy"] < make_config(trades_override())["items"]["stone"]["value"] * 1.5
    # the glut wears off overnight
    until_morning(w)
    assert w.trader_stock["stone"] == 2
    until_morning(w)
    until_morning(w)
    assert "stone" not in w.trader_stock
    assert price(w, "stone", "sell") == first


def test_gold_glut_and_floor(w):
    gift(w, "Dmitri", gold=4)
    w.agents["Dmitri"].location = "market"
    full = price(w, "gold", "sell")
    assert full == 6  # crafts: gold is worth 12, the trader pays half
    act(w, "Dmitri", "sell", item="gold", qty=2)
    assert price(w, "gold", "sell") < full
    w.trader_stock["gold"] = 1000
    assert price(w, "gold", "sell") == round(12 * 0.5 * 0.3)  # never below the floor (nearest coin)
    # buying from him takes it out of his stock
    w.agents["Anna"].location = "market"
    ops.mint_coins(w, w.agents["Anna"], 50)
    w.trader_stock["gold"] = 1
    act(w, "Anna", "buy", item="gold", qty=1)
    assert "gold" not in w.trader_stock


def test_stock_prices_off_outside_crafts():
    w = engine.new_world({"seed": 1, "crises": {"enabled": False}})
    w.agents["Dmitri"].location = "market"
    gift(w, "Dmitri", stone=6)
    first = price(w, "stone", "sell")
    act(w, "Dmitri", "sell", item="stone", qty=6)
    assert w.trader_stock == {} and price(w, "stone", "sell") == first
    assert all("tool" not in a.inventory for a in w.agents.values())


def test_everyone_starts_with_a_tool_that_wears_out(w):
    assert all(a.inventory.get("tool") == 1 for a in w.agents.values())
    boris = w.agents["Boris"]
    boris.location = "river"
    hours = 0
    while "tool" in boris.inventory:
        boris.worked_today = 0
        act(w, "Boris", "work", resource="fish", hours=1)
        hours += 1
    assert hours == 14


def test_dishes_from_several_trades(w):
    anna = w.agents["Anna"]
    gift(w, "Anna", fish=1, grain=4, wood=1, egg=1, milk=1, honey=1)
    act(w, "Anna", "craft", recipe="stew")
    act(w, "Anna", "craft", recipe="pancakes")
    act(w, "Anna", "craft", recipe="honey_cake")
    assert {k: anna.inventory.get(k) for k in ("stew", "pancakes", "honey_cake")} == \
        {"stew": 1, "pancakes": 1, "honey_cake": 1}
    satiety = anna.satiety = 10
    act(w, "Anna", "eat", item="stew")
    assert anna.satiety >= satiety + 75 - 5


def test_gold_has_uses(w):
    elena = w.agents["Elena"]
    elena.location = "smithy"
    gift(w, "Elena", gold=1)
    act(w, "Elena", "craft", recipe="ring")
    assert elena.inventory.get("ring") == 1
    cost = plots.upgrade_cost(w.config, w.plots["home_Anna"])  # level 1 -> 2: no gold
    assert "gold" not in cost["items"]
    w.plots["home_Anna"].house = 2
    assert plots.upgrade_cost(w.config, w.plots["home_Anna"])["items"]["gold"] == 2


def test_facts_and_knobs():
    facts = world_facts(make_config(trades_override()))
    assert "trader's prices follow his stock" in facts and "wears out after 14 hours" in facts
    d = knobs.preset_defaults("normal")
    assert d["stock_prices"] is True and d["tool_hours"] == 14 and d["start_tool"] == 1 and d["gold_value"] == 12


def test_save_keeps_trader_stock(w):
    from aivillage.state import World
    w.trader_stock = {"gold": 3}
    assert World.from_dict(w.to_dict()).trader_stock == {"gold": 3}


def test_prices_round_to_the_nearest_coin(w):
    # crafts: fish is worth 3 and the trader pays half, 1.5 -> 2 (cut down, as the old modes still do, it was 1)
    assert price(w, "fish", "sell") == 2 and price(w, "ore", "sell") == 3 and price(w, "berries", "buy") == 2
    old = engine.new_world({"seed": 1, "crises": {"enabled": False}})
    assert engine.observe(old, "Anna")["board"]["trader_prices"]["fish"]["sell"] == 1


def test_one_big_sale_slides_like_small_ones(w):
    small = crafts_world()
    for x in (w, small):
        x.agents["Dmitri"].location = "market"
        gift(x, "Dmitri", ore=4)
    first = price(w, "ore", "sell")
    coins = w.agents["Dmitri"].coins
    act(w, "Dmitri", "sell", item="ore", qty=4)
    lot = w.agents["Dmitri"].coins - coins
    assert lot < 4 * first  # each unit he takes lowers the price of the next, inside one lot too
    coins = small.agents["Dmitri"].coins
    for _ in range(2):
        act(small, "Dmitri", "sell", item="ore", qty=2)
    assert small.agents["Dmitri"].coins - coins == lot  # the same ore in two lots pays exactly the same
    assert w.trader_stock["ore"] == small.trader_stock["ore"] == 4
    # buying a lot back walks the price up again as his stock shrinks
    w.agents["Anna"].location = "market"
    ops.mint_coins(w, w.agents["Anna"], 100)
    unit = price(w, "ore", "buy")
    coins = w.agents["Anna"].coins
    act(w, "Anna", "buy", item="ore", qty=2)  # the trader sells 2 a day here
    assert coins - w.agents["Anna"].coins >= 2 * unit and price(w, "ore", "buy") > unit


def test_buying_a_lot_and_selling_it_back_unit_by_unit_makes_nothing(w):
    """Audit B-5: with 7 berries in the trader's stock a lot of 2 cost 1 coin and each berry sold back fetched 1."""
    anna = w.agents["Anna"]
    anna.location = "market"
    w.trader_stock["berries"] = 7
    coins = anna.coins
    act(w, "Anna", "buy", item="berries", qty=2)
    act(w, "Anna", "sell", item="berries", qty=1)
    act(w, "Anna", "sell", item="berries", qty=1)
    assert w.trader_stock["berries"] == 7 and anna.inventory.get("berries", 0) == 0
    assert anna.coins <= coins


@pytest.mark.parametrize("ratios", [None, (1.5, 2.0)])  # (2.0, 1.5): a bridge or crisis paying above his asking price
def test_no_split_or_round_trip_of_a_trade_makes_coins(ratios):
    from aivillage import pricing
    w = crafts_world()
    if ratios:
        w.config["npc_sell_ratio"], w.config["npc_buy_ratio"] = ratios
    for item, v in w.config["items"].items():
        if not v.get("tradable", True):
            continue
        for held in range(0, 16):
            for qty in range(1, 6):
                for side, step in (("sell", 1), ("buy", -1)):
                    w.trader_stock = {item: held} if held else {}
                    lot = pricing.total(w, item, side, qty)
                    one_by_one = 0
                    for _ in range(qty):
                        one_by_one += pricing.price(w, item, side)
                        n = w.trader_stock.get(item, 0) + step
                        w.trader_stock = {item: n} if n > 0 else {}
                    assert lot == one_by_one, (item, held, qty, side)
                w.trader_stock = {item: held} if held else {}
                paid = pricing.total(w, item, "buy", qty)
                w.trader_stock = {item: max(0, held - qty)} if held > qty else {}
                back = pricing.total(w, item, "sell", qty)
                assert back <= paid, (item, held, qty)
