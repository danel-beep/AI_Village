"""Market board (market.py): sell listings, remote orders, cancel, and who was seen where."""

import pytest

from aivillage import clock, engine, ops
from aivillage.invariants import check
from aivillage.llm import compact_obs, world_facts


@pytest.fixture
def w():
    return engine.new_world({"seed": 1, "crises": {"enabled": False}})


def put(w, name, loc):
    w.agents[name].location = loc


def gift(w, name, **items):
    for k, v in items.items():
        ops.mint(w, w.agents[name].inventory, k, v)


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def test_sale_is_held_by_the_board_and_bought_from_afar(w):
    gift(w, "Boris", fish=5)
    put(w, "Boris", "river")
    b0, a0 = w.agents["Boris"].coins, w.agents["Anna"].coins
    act(w, "Boris", "post_sale", items={"fish": 3}, price=9)
    s = next(iter(w.sales.values()))
    assert w.agents["Boris"].inventory["fish"] == 2 and s.seller == "Boris"
    obs = engine.observe(w, "Anna")
    assert obs["for_sale"][0] == {"id": s.id, "seller": "Boris", "items": {"fish": 3}, "price": 9}
    assert "for_sale" not in engine.observe(w, "Boris") and engine.observe(w, "Boris")["your_sales"]
    put(w, "Anna", "home_Anna")  # far from Boris and from the square
    act(w, "Anna", "buy_sale", sale_id=s.id)
    assert w.agents["Anna"].inventory["fish"] == 3 and w.agents["Anna"].coins == a0 - 9
    assert w.agents["Boris"].coins == b0 + 9 and not w.sales


def test_failed_sales_change_nothing(w):
    gift(w, "Boris", fish=1)
    h = w.hash()
    for args in ({"items": {"fish": 2}, "price": 5}, {"items": {"coins": 2}, "price": 5},
                 {"items": {"fish": 1}, "price": 5, "hours": 500}):
        engine.step(w, {"Boris": {"action": {"name": "post_sale", "args": args}}})
        assert w.agents["Boris"].last_error and not w.sales
    act(w, "Boris", "post_sale", items={"fish": 1}, price=500)
    sid = next(iter(w.sales))
    act(w, "Anna", "buy_sale", sale_id=sid)  # too poor
    assert sid in w.sales and "costs 500" in w.agents["Anna"].last_error
    act(w, "Boris", "buy_sale", sale_id=sid)  # own listing
    assert sid in w.sales
    assert h  # world stayed consistent: check() ran after each act


def test_unsold_listing_comes_back_and_cancel_works(w):
    gift(w, "Boris", fish=4)
    act(w, "Boris", "post_sale", items={"fish": 2}, price=5, hours=2)
    act(w, "Boris", "post_sale", items={"fish": 2}, price=5)
    for _ in range(clock.hours(w.config, 3)):
        engine.step(w, {})
    check(w)
    assert len(w.sales) == 1 and w.agents["Boris"].inventory["fish"] == 2
    act(w, "Boris", "cancel_listing", listing_id=next(iter(w.sales)))
    assert not w.sales and w.agents["Boris"].inventory["fish"] == 4
    c0 = w.agents["Clara"].coins
    act(w, "Clara", "post_order", needs={"fish": 1}, reward=6)
    oid = next(o.id for o in w.orders.values() if o.by == "Clara")
    act(w, "Clara", "cancel_listing", listing_id=oid)
    assert w.orders[oid].status == "cancelled" and w.agents["Clara"].coins == c0


def test_villager_order_delivered_from_afar_council_order_at_square(w):
    gift(w, "Boris", fish=3)
    act(w, "Clara", "post_order", needs={"fish": 3}, reward=10)
    o = next(o for o in w.orders.values() if o.by == "Clara")
    put(w, "Boris", "river")
    act(w, "Boris", "fulfill_order", order_id=o.id)
    assert o.status == "fulfilled" and w.agents["Clara"].inventory["fish"] == 3
    w.config["market"]["remote"] = False
    gift(w, "Boris", fish=3)
    act(w, "Clara", "post_order", needs={"fish": 3}, reward=10)
    o2 = next(o for o in w.orders.values() if o.by == "Clara" and o.status == "open")
    act(w, "Boris", "fulfill_order", order_id=o2.id)
    assert o2.status == "open" and "square" in w.agents["Boris"].last_error


def test_last_seen_from_meeting_and_from_events(w):
    put(w, "Anna", "market")
    put(w, "Boris", "market")
    engine.step(w, {})
    put(w, "Boris", "river")
    for _ in range(clock.hours(w.config, 2)):
        engine.step(w, {})
    seen = engine.observe(w, "Anna")["last_seen"]
    assert seen["Boris"] == "market, 2 h ago"
    put(w, "Anna", "river")
    assert "Boris" not in engine.observe(w, "Anna").get("last_seen", {})  # here now: listed in here.people
    gift(w, "Dmitri", ore=2)
    put(w, "Elena", "market")
    put(w, "Dmitri", "market")
    w.agents["Elena"].asleep = True
    act(w, "Dmitri", "sell", item="ore", qty=1)  # a location event: awake people there see him
    assert "Dmitri" not in w.agents["Elena"].seen  # asleep: saw nothing
    assert w.agents["Anna"].seen.get("Dmitri") is None


def test_market_in_facts_and_off_switch(w):
    assert "Market board" in world_facts(w.config)
    compact_obs(engine.observe(w, "Anna"))
    off = engine.new_world({"seed": 1, "market": {"enabled": False}})
    gift(off, "Boris", fish=1)
    act(off, "Boris", "post_sale", items={"fish": 1}, price=3)
    assert not off.sales and "Market board" not in world_facts(off.config)
    assert "for_sale" not in engine.observe(off, "Anna")


def test_world_with_sales_round_trips(w):
    from aivillage.state import World
    gift(w, "Boris", fish=1)
    act(w, "Boris", "post_sale", items={"fish": 1}, price=3)
    w2 = World.from_dict(w.to_dict())
    assert w2.hash() == w.hash() and w2.sales.keys() == w.sales.keys()
