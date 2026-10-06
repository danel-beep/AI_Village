"""Taxes by income and wealth, the treasury loop and council orders paid per delivery (aivillage/taxes.py)."""

import random

import pytest

from aivillage import engine, ops, taxes, works
from aivillage.invariants import check
from aivillage.llm import world_facts

NAMES = ["Anna", "Boris", "Clara", "Dmitri", "Elena"]
CFG = {"seed": 1, "crises": {"enabled": False}, "tax_amount": 10,
       "taxes": {"enabled": True}, "council_orders": {"enabled": True}}


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


def gift(w, name, **items):
    for k, v in items.items():
        if k == "coins":
            ops.mint_coins(w, w.agents[name], v)
        else:
            ops.mint(w, w.agents[name].inventory, k, v)


def set_coins(w, name, n):
    a = w.agents[name]
    if a.coins > n:
        ops.burn_coins(w, a, a.coins - n)
    else:
        ops.mint_coins(w, a, n - a.coins)


def test_bill_is_land_plus_sales_plus_wealth(w):
    a = w.agents["Anna"]
    set_coins(w, "Anna", 300)
    a.earned_since_tax = 120
    assert taxes.bill(w, a) == {"total": 10 + 12 + 10, "land": 10, "sales": 12, "wealth": 10}
    set_coins(w, "Boris", 30)
    assert taxes.bill(w, w.agents["Boris"])["total"] == 10


def test_selling_to_the_trader_counts_as_income(w):
    a = w.agents["Anna"]
    a.location = "market"
    gift(w, "Anna", fish=4)
    before = a.coins
    assert not errors(act(w, "Anna", "sell", item="fish", qty=4))
    assert a.earned_since_tax == a.coins - before > 0


def test_tax_day_splits_between_fire_and_treasury(w):
    set_coins(w, "Anna", 300)  # wealth 10% of 200 at 5% = 10, land 10 -> 20; 25% burned
    for n in NAMES[1:]:
        set_coins(w, n, 50)    # land only
    w.agents["Anna"].earned_since_tax = 40  # sales 4
    events = until_day(w, 8)
    paid = [e for e in events if e.kind == "tax" and e.to == ["Anna"]]
    assert paid and "land 10, sales 4, wealth 10" in paid[0].text
    total = 24 + 4 * 10
    assert w.governance.coins == total - sum(t * 25 // 100 for t in [24, 10, 10, 10, 10])
    assert w.agents["Anna"].earned_since_tax == 0


def test_flat_tax_unchanged_when_off():
    w = engine.new_world({"seed": 1, "crises": {"enabled": False}})
    a = w.agents["Anna"]
    a.earned_since_tax = 500
    assert taxes.bill(w, a) == {"total": w.config["tax_amount"]}
    assert taxes.observe(w, "Anna") == {}
    assert "- Tax: 20 coins every 7 days" in world_facts(w.config)


def test_council_order_reward_and_part_deliveries(w):
    cfg = w.config
    tpl = {"needs": {"bread": 2, "wood": 4}, "reward": 999}
    reward = taxes.council_reward(cfg, tpl)
    assert reward == round(1.6 * (2 * cfg["items"]["bread"]["value"] + 4 * cfg["items"]["wood"]["value"]))
    o = engine.Order("order_x", dict(tpl["needs"]), reward, w.day + 3)
    w.orders[o.id] = o
    for n in ("Anna", "Boris"):
        w.agents[n].location = "square"
    gift(w, "Anna", wood=4)
    gift(w, "Boris", bread=3)
    a0, b0 = w.agents["Anna"].coins, w.agents["Boris"].coins
    ev = act(w, "Anna", "fulfill_order", order_id="order_x")
    assert not errors(ev) and o.status == "open"
    assert any(e.kind == "order_part" and "still needs 2 bread" in e.text for e in ev)
    anna_got = w.agents["Anna"].coins - a0
    assert anna_got == reward * 8 // value_of(cfg, o.needs)
    assert not errors(act(w, "Boris", "fulfill_order", order_id="order_x"))
    assert o.status == "fulfilled" and o.paid == reward
    assert w.agents["Boris"].coins - b0 == reward - anna_got
    assert w.agents["Boris"].inventory.get("bread") == 1  # only what the order still needed
    assert "no open order" in errors(act(w, "Anna", "fulfill_order", order_id="order_x"))[0]


def value_of(cfg, items):
    return taxes.value(cfg, items)


def make_mayor(w, name="Anna"):
    w.governance.mayor = name


def open_well(w):
    ctx = ops.Ctx(w, random.Random(0))
    return works.open_project(ctx, "well", 1, "council")


def test_treasury_order_pays_from_treasury_and_builds(w):
    make_mayor(w)
    p = open_well(w)
    ops.mint_coins(w, w.governance, 100)
    w.agents["Anna"].location = "square"
    need = {"wood": works.remaining(p)["wood"]}
    base = taxes.value(w.config, need)
    assert "between" in errors(act(w, "Anna", "treasury_order", project_id=p.id, needs=need, reward=base * 3))[0]
    assert "needs only" in errors(act(w, "Anna", "treasury_order", project_id=p.id, needs={"fish": 1}, reward=3))[0]
    assert not errors(act(w, "Anna", "treasury_order", project_id=p.id, needs=need, reward=base))
    assert w.governance.coins == 100 - base and w.governance.last_spent_day == w.day
    o = next(o for o in w.orders.values() if o.payer == taxes.TREASURY)
    w.agents["Clara"].location = "square"
    gift(w, "Clara", wood=2)
    c0 = w.agents["Clara"].coins
    assert not errors(act(w, "Clara", "fulfill_order", order_id=o.id))
    assert w.agents["Clara"].coins - c0 == o.paid == base * 2 // need["wood"]
    assert p.contributed["wood"] == 2 and p.contributors["Clara"] == 2
    assert w.agents["Clara"].earned_since_tax == 0  # paid by the village, not from outside
    # Nobody brings the rest: the unpaid coins go back to the treasury when it closes
    left = o.reward - o.paid
    treasury = w.governance.coins
    until_day(w, o.expires_day + 1)
    assert o.status == "expired" and w.governance.coins == treasury + left


def test_only_the_mayor_orders_for_the_village(w):
    make_mayor(w, "Boris")
    p = open_well(w)
    ops.mint_coins(w, w.governance, 100)
    w.agents["Anna"].location = "square"
    err = errors(act(w, "Anna", "treasury_order", project_id=p.id, needs={"wood": 1}, reward=2))
    assert err and "only the mayor" in err[0]


def test_surplus_goes_to_builders(w):
    from aivillage.ops import Ctx
    ops.mint_coins(w, w.governance, 40 * 5 + 50)
    w.governance.work_hours = {"Boris": 3, "Clara": 1}
    w.day = 9
    before = {n: w.agents[n].coins for n in NAMES}
    ctx = Ctx(w, random.Random(0))
    taxes.after_night(ctx)
    got = {n: w.agents[n].coins - before[n] for n in NAMES}
    assert got["Boris"] == 37 and got["Clara"] == 12 and got["Anna"] == 0
    assert w.governance.work_hours == {} and w.governance.last_spent_day == 9
    assert any(e.kind == "treasury_surplus" for e in ctx.events)
    # Spent recently: nothing happens
    ops.mint_coins(w, w.governance, 100)
    coins = w.governance.coins
    taxes.after_night(ctx)
    assert w.governance.coins == coins


def test_tax_rate_laws(w):
    make_mayor(w)
    err = errors(act(w, "Anna", "propose_law", law="sales_tax", value=50))
    assert err and "between 0 and 30" in err[0]
    assert not errors(act(w, "Anna", "propose_law", law="wealth_tax", value=10))
    step(w, {n: ("vote_law", {"proposal_id": next(iter(w.governance.proposals)), "vote": "yes"}) for n in NAMES})
    assert taxes.rate(w, "wealth_tax") == 10
    off = engine.new_world({"seed": 1, "crises": {"enabled": False}})
    off.governance.mayor = "Anna"
    assert "no sales_tax" in errors(act(off, "Anna", "propose_law", law="sales_tax", value=5))[0]


def test_crafts_mode_turns_taxes_on():
    from aivillage.modes import world_override
    w = engine.new_world({"seed": 1, **world_override("crafts")})
    assert taxes.enabled(w.config) and taxes.council_on(w.config) and w.config["tax_amount"] == 10
    facts = world_facts(w.config)
    assert "sales_tax" in facts and "Council orders pay 1.0x" in facts


@pytest.mark.parametrize("seed", range(3))
def test_fuzz_crafts_mode_with_taxes(seed):
    from aivillage.modes import world_override
    from aivillage.run import bots_decider, run
    w = engine.new_world({"seed": seed, **world_override("crafts")})
    run(w, bots_decider(w, ["random", "worker", "random"], seed), days=15)  # invariants every tick
    check(w)
    assert w.day == 16
