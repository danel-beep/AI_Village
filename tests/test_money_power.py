"""Money and power come with buildings (survival plan task 12): the trader with a market square, elections,
taxes and council orders with a town hall, random raids at the town stage. «Обычный» is unchanged."""

from contextlib import contextmanager

from aivillage import engine, modes, ops, progress
from aivillage.invariants import check
from aivillage.llm import world_facts

QUIET = {"crises": {"enabled": False}, "illness": {"per_day": 0.0}}
RAIDY = {"threats": {"first_day": 1, "max_active": 1,
                     "kinds": {"raid": {"per_day": 1.0}, "beast": {"per_day": 0.0},
                               "traveler": {"per_day": 1.0, "scout_chance": 1.0}}}}


def world(stage="camp", mode="survival", **extra):
    return engine.new_world(modes.world_override(mode, {"seed": 3, **QUIET, "progress": {"start_stage": stage},
                                                        **extra}))


def step(w):
    events = engine.step(w, {})
    check(w)
    return events


def until_day(w, day):
    events = []
    while w.day < day:
        events += step(w)
    return events


def kinds(events):
    return {e.kind for e in events}


@contextmanager
def standing(*kinds_):
    """Pretend these buildings stand (as construction.py would report them)."""
    src = lambda world: {k: 1 for k in kinds_}  # noqa: E731
    progress.BUILT_SOURCES.append(src)
    try:
        yield
    finally:
        progress.BUILT_SOURCES.remove(src)


def test_camp_has_no_trader_tax_or_government():
    w = world()
    name = next(iter(w.agents))
    obs = engine.observe(w, name, consume_inbox=False)
    assert obs["board"]["trader_prices"] == {} and "trader_today" not in obs
    assert "tax" not in obs["time"] and "next_tax_day" not in obs["time"] and "tax_bill" not in obs
    assert obs["government"]["mayor"] is None
    assert "town_hall" in obs["government"]["not_yet"] and "next_election_day" not in obs["government"]


def test_camp_days_pass_without_tax_elections_orders_or_raids():
    w = world(**RAIDY)
    events = until_day(w, w.config["tax_every_days"] + 2)
    assert not kinds(events) & {"tax", "tax_bills", "evicted", "election", "election_day", "election_soon", "order"}
    assert not w.orders
    assert w.threats and all(t["kind"] == "traveler" and not t["scout"] for t in w.threats)


def test_market_square_brings_the_trader():
    w = world()
    name = next(iter(w.agents))
    with standing("market_square"):
        step(w)
        obs = engine.observe(w, name, consume_inbox=False)
    assert obs["board"]["trader_prices"] and "trader_today" in obs
    assert "tax" not in obs["time"] and "not_yet" in obs["government"]  # still no town hall


def test_town_hall_opens_tax_elections_and_council_orders():
    w = world(polity={"enabled": False})  # with polities each polity taxes and governs itself (test_polity.py)
    for a in w.agents.values():
        ops.mint_coins(w, a, 50)
    with standing("market_square", "town_hall"):
        step(w)
        name = next(iter(w.agents))
        obs = engine.observe(w, name, consume_inbox=False)
        assert obs["time"]["tax"] > 0 and "next_election_day" in obs["government"]
        events = until_day(w, w.config["tax_every_days"] + 2)
    assert kinds(events) >= {"tax", "election_day", "order"}


def test_voluntary_laws_write_no_bills_before_the_town_hall():
    w = world(laws={"enforcement": "voluntary"})
    events = until_day(w, w.config["tax_every_days"] + 2)
    assert "tax_bills" not in kinds(events) and not w.debts


def test_raids_come_by_themselves_at_the_town_stage():
    w = world("town", **RAIDY)
    until_day(w, 4)
    assert any(t["kind"] == "raid" for t in w.threats)


def test_prompt_says_when_each_opens():
    facts = world_facts(world().config)
    assert "Tax (once a town_hall stands in the village):" in facts
    assert "Polities (once a town_hall stands in the village):" in facts
    assert "Government (once a town_hall stands in the village):" in world_facts(world(polity={"enabled": False}).config)
    assert "The trader (once a market_square stands in the village)" in facts
    assert "bandits (once the village is a town)" in facts
    plain = world_facts(world(mode="crafts").config)
    assert "(once " not in plain


def test_ordinary_mode_unchanged():
    w = world(mode="crafts")
    name = next(iter(w.agents))
    obs = engine.observe(w, name, consume_inbox=False)
    assert obs["board"]["trader_prices"] and "trader_today" in obs
    assert obs["time"]["tax"] > 0 and "next_election_day" in obs["government"]
