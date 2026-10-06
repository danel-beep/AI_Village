"""Division of labour (labor.py), villagers' own orders (post_order) and graves (graves.py)."""

import pytest

from aivillage import engine, labor, ops
from aivillage.config import make_config
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.modes import world_override

CRAFTS = {"seed": 1, "crises": {"enabled": False}, "labor": {"enabled": True}}


@pytest.fixture
def w():
    return engine.new_world(CRAFTS)


def put(w, name, loc):
    w.agents[name].location = loc


def gift(w, name, **items):
    for k, v in items.items():
        if k == "coins":
            ops.mint_coins(w, w.agents[name], v)
        else:
            ops.mint(w, w.agents[name].inventory, k, v)


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def until_morning(w):
    day = w.day
    while w.day == day:
        engine.step(w, {})
    check(w)


def test_only_the_trade_gathers_its_goods(w):
    put(w, "Anna", "river")  # farmer
    act(w, "Anna", "work", resource="fish")
    assert "only a fisher can gather fish" in w.agents["Anna"].last_error
    assert w.agents["Anna"].inventory.get("fish", 0) == 0
    put(w, "Boris", "river")
    act(w, "Boris", "work", resource="fish")
    assert w.agents["Boris"].inventory["fish"] == 3
    put(w, "Anna", "forest")  # berries are free for everyone; the default pick skips wood
    act(w, "Anna", "work")
    assert w.agents["Anna"].inventory["berries"] == 1 and "wood" not in w.agents["Anna"].inventory


def test_only_a_farmer_sows(w):
    gift(w, "Boris", grain=2, wood=1)
    put(w, "Boris", "home_Boris")
    act(w, "Boris", "build", kind="garden_bed")
    act(w, "Boris", "plant")
    assert "only a farmer can sow grain" in w.agents["Boris"].last_error


def test_work_hours_a_day_and_skill(w):
    b = w.agents["Boris"]
    put(w, "Boris", "river")
    got = []
    for _ in range(6):
        before = b.inventory.get("fish", 0)
        events = act(w, "Boris", "work", resource="fish")
        got.append(b.inventory["fish"] - before)
    assert got == [3] * 6
    assert any(e.kind == "skill_up" for e in events) and labor.level(w.config, b.skill_hours) == 1
    act(w, "Boris", "work", resource="fish")
    assert "most anyone can" in b.last_error and b.worked_today == 6
    until_morning(w)
    assert b.worked_today == 0
    act(w, "Boris", "work", resource="fish")
    assert b.inventory["fish"] == 18 + 4  # level 1: 3 + 1 per hour


def test_trader_buys_and_sells_a_limited_amount_a_day(w):
    cap = labor.quota(w.config, "wood", "buy")
    assert cap == 6
    gift(w, "Clara", wood=10, coins=100)
    put(w, "Clara", "market")
    act(w, "Clara", "sell", item="wood", qty=4)
    act(w, "Clara", "sell", item="wood", qty=4)
    assert "only 2 more wood" in w.agents["Clara"].last_error
    assert w.agents["Clara"].inventory["wood"] == 6
    act(w, "Clara", "buy", item="bread", qty=3)
    assert "only 2 more bread" in w.agents["Clara"].last_error
    act(w, "Clara", "buy", item="bread", qty=2)
    assert w.agents["Clara"].inventory["bread"] == 2
    obs = engine.observe(w, "Clara")
    assert obs["trader_today"]["will_buy"]["wood"] == 2 and obs["trader_today"]["has_for_sale"]["bread"] == 0
    until_morning(w)
    assert labor.trader_left(w, "wood", "buy") == 6


def test_post_order_holds_coins_and_carries_goods(w):
    c0, b0 = w.agents["Clara"].coins, w.agents["Boris"].coins
    gift(w, "Boris", fish=5)
    put(w, "Clara", "forest")
    act(w, "Clara", "post_order", needs={"fish": 3}, reward=12)
    o = next(o for o in w.orders.values() if o.by == "Clara")
    assert w.agents["Clara"].coins == c0 - 12 and o.status == "open"
    put(w, "Boris", "square")
    act(w, "Boris", "fulfill_order", order_id=o.id)
    assert o.status == "fulfilled" and w.agents["Boris"].coins == b0 + 12
    assert w.agents["Clara"].inventory["fish"] == 3 and w.agents["Boris"].inventory["fish"] == 2
    news = engine.observe(w, "Clara")["news"]
    assert any("delivered your order" in n for n in news)


def test_unclaimed_order_gives_the_coins_back(w):
    c0 = w.agents["Clara"].coins
    act(w, "Clara", "post_order", needs={"ore": 1}, reward=10, days=1)
    assert w.agents["Clara"].coins == c0 - 10
    until_morning(w)
    until_morning(w)
    assert w.agents["Clara"].coins == c0


def test_offers_are_accepted_from_anywhere(w):
    gift(w, "Clara", wood=4)
    gift(w, "Boris", fish=3)
    put(w, "Clara", "forest")
    put(w, "Boris", "river")
    act(w, "Clara", "offer", to="Boris", give={"wood": 4}, want={"fish": 3})
    oid = next(iter(w.offers))
    act(w, "Boris", "accept", offer_id=oid)
    assert w.agents["Boris"].inventory["wood"] == 4 and w.agents["Clara"].inventory["fish"] == 3
    near = engine.new_world({**CRAFTS, "labor": {"enabled": True, "trade_anywhere": False}})
    gift(near, "Clara", wood=4)
    put(near, "Clara", "forest")
    act(near, "Clara", "offer", to="Boris", give={"wood": 4}, want={})
    act(near, "Boris", "accept", offer_id=next(iter(near.offers)))
    assert "must be here" in near.agents["Boris"].last_error


def test_crafts_mode_needs_firewood_and_states_the_rules():
    cfg = make_config(world_override("crafts"))
    assert cfg["recipes"]["bread"]["inputs"] == {"grain": 2, "wood": 1}
    assert cfg["professions"]["farmer"] == ["grain", "berries"]
    facts = world_facts(cfg)
    assert "only a villager of that profession" in facts and "trader_today" in facts


# ---------- graves ----------

def starve(w, name):
    a = w.agents[name]
    a.satiety, a.health = 0, 5
    engine.step(w, {})
    check(w)


def test_death_leaves_a_grave_everyone_knows():
    w = engine.new_world({"seed": 1, "death_mode": "death", "crises": {"enabled": False}})
    put(w, "Anna", "forest")
    starve(w, "Anna")
    assert w.agents["Anna"].status == "dead"
    assert w.graves == [{"name": "Anna", "profession": "farmer", "day": 1, "hour": w.graves[0]["hour"],
                         "cause": "hunger", "died_at": "forest", "home": "home_Anna"}]
    obs = engine.observe(w, "Boris")
    assert any("Anna the farmer died of hunger" in n for n in obs["news"])
    assert obs["graves"][0]["name"] == "Anna" and obs["graves"][0]["cause"] == "hunger"
    put(w, "Boris", "home_Anna")
    obs = engine.observe(w, "Boris")
    assert obs["graves_here"] == ["Anna"] and "pay_respects" in obs["available_actions"]
    events = act(w, "Boris", "pay_respects", person="Anna")
    assert any(e.kind == "pay_respects" for e in events)
    act(w, "Boris", "pay_respects", person="Clara")
    assert "no grave of Clara" in w.agents["Boris"].last_error


def test_death_wakes_the_village():
    w = engine.new_world({"seed": 1, "death_mode": "death", "crises": {"enabled": False}})
    put(w, "Boris", "river")
    act(w, "Boris", "work", hours=4, resource="fish")
    assert w.agents["Boris"].task
    starve(w, "Anna")
    assert w.agents["Boris"].task is None


def test_god_lightning():
    w = engine.new_world({"seed": 1, "death_mode": "death", "crises": {"enabled": False}})
    engine.step(w, {}, [{"name": "lightning", "args": {"person": "Clara"}}])
    check(w)
    assert w.agents["Clara"].status == "dead" and w.graves[0]["cause"] == "lightning"
    h = engine.new_world({"seed": 1, "crises": {"enabled": False}})  # hospital mode: no grave
    engine.step(h, {}, [{"name": "lightning", "args": {"person": "Clara"}}])
    assert h.agents["Clara"].status == "hospital" and not h.graves and h.agents["Clara"].harm == ""
