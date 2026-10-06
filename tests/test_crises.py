"""World crises (crises.py): when they come, what they do, that they end, and that loners survive them."""

from collections import Counter

from aivillage import crises, engine, modes, ops, plots
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.ops import Ctx
from aivillage.run import bots_decider, replay, run


def world(**crisis_cfg):
    return engine.new_world({"seed": 3, "crises": crisis_cfg})


def start(w, kind, days=2):
    c = crises.start(Ctx(w, engine.rng_for(w, "test")), engine.rng_for(w, "test"), kind, days)
    check(w)
    return c


def next_day(w):
    day = w.day
    events = []
    while w.day == day:
        events += engine.step(w, {})
    check(w)
    return events


def test_crises_come_and_go():
    w = world()
    log = Counter()
    for _ in range(20):
        for e in next_day(w):
            log[e.kind] += 1
        assert len(crises.active(w)) <= w.config["crises"]["max_active"]
    assert log["crisis"] >= 4, log
    assert log["crisis_over"] >= 3, log
    assert len(w.crises) <= crises.KEEP_FINISHED + 1


def test_disabled_means_no_crises():
    w = world(enabled=False)
    for _ in range(10):
        assert not [e for e in next_day(w) if e.kind == "crisis"]
    assert w.crises == []


def test_crop_failure_stops_regrowth_then_ends():
    # the default village has no common field (grain grows in private gardens); an old-style one is added back
    from aivillage.config import DEFAULT_CONFIG
    w = engine.new_world({"seed": 3, "crises": {"enabled": False}, "locations": {
        "square": {"neighbors": DEFAULT_CONFIG["locations"]["square"]["neighbors"] + ["field"]},
        "field": {"name": "Field", "neighbors": ["square"],
                  "resources": {"grain": {"start": 40, "max": 40, "regen": 10, "slots": 8}}}}})
    field = w.locations["field"]
    before = field.resources["grain"]
    c = start(w, "crop_failure", days=2)
    assert field.resources["grain"] < before
    assert "field" in c["frozen"]
    low = field.resources["grain"]
    next_day(w)
    assert field.resources["grain"] == low  # no regrowth while it lasts
    events = next_day(w)
    assert any(e.kind == "crisis_over" for e in events)
    assert not crises.active(w)
    assert field.resources["grain"] > low  # grows again


def test_crop_failure_without_a_field_hits_gardens():
    w = world(enabled=False)
    w.config["crises"]["kinds"]["crop_failure"]["garden_share"] = 1.0
    bed = w.plots["home_Anna"].buildings[0]  # the farmer starts with sown beds
    assert crises._possible(w, "crop_failure", w.config["crises"]["kinds"]["crop_failure"])
    c = start(w, "crop_failure")
    assert bed["crop"] is None and "gardens" in c["text"]


def test_crop_failure_kills_sown_garden_beds():
    w = world(enabled=False)
    w.config["crises"]["kinds"]["crop_failure"]["garden_share"] = 1.0
    plot = next(iter(w.plots.values()))
    bed = plots._add_building(w, plot, "garden_bed", w.day)
    bed["crop"], bed["ripe_day"] = "grain", w.day + 2
    start(w, "crop_failure")
    assert bed["crop"] is None


def test_rats_eat_from_some_chests():
    w = world(enabled=False)
    for c in w.chests.values():
        ops.mint(w, c.items, "fish", 10)
    c = start(w, "rats")
    left = {ch.owner: ops.count(ch.items, "fish") for ch in w.chests.values()}
    assert {left[v] for v in c["victims"]} == {4}  # ate 60%
    assert any(n == 10 for n in left.values())  # not everyone is hit
    assert set(c["victims"]) < set(left)


def test_shortage_raises_trader_price():
    w = world(enabled=False)
    name = next(iter(w.agents))
    normal = engine.observe(w, name)["board"]["trader_prices"]
    c = start(w, "shortage")
    item = next(iter(c["prices"]))
    obs = engine.observe(w, name)
    assert obs["board"]["trader_prices"][item]["buy"] >= 2 * normal[item]["buy"]
    assert obs["crises"][0]["what"] == c["text"]
    a = w.agents[name]
    a.location = "market"
    ops.mint_coins(w, a, 100)
    coins = a.coins
    engine.step(w, {name: {"action": {"name": "buy", "args": {"item": item, "qty": 1}}}})
    check(w)
    assert coins - a.coins == obs["board"]["trader_prices"][item]["buy"]


def test_caravan_pays_more_but_never_more_than_trader_sells():
    w = world(enabled=False)
    name = next(iter(w.agents))
    normal = engine.observe(w, name)["board"]["trader_prices"]
    c = start(w, "caravan")
    item = next(iter(c["prices"]))
    prices = engine.observe(w, name)["board"]["trader_prices"]
    assert prices[item]["sell"] > normal[item]["sell"] or normal[item]["sell"] == prices[item]["buy"]
    for p in prices.values():  # no buy-low-sell-high loop with the trader himself
        assert p["sell"] <= p["buy"]


def test_god_can_start_a_crisis():
    w = world(enabled=False)
    w.config["crises"]["enabled"] = True
    events = engine.step(w, {}, [{"name": "crisis", "args": {"kind": "drought", "days": 3}}])
    check(w)
    assert any(e.kind == "crisis" for e in events)
    assert crises.active(w)[0]["kind"] == "drought"


def test_villagers_are_told():
    w = world()
    assert "Hard times" in world_facts(w.config)
    assert "Hard times" not in world_facts(world(enabled=False).config)
    assert "crises" not in engine.observe(w, next(iter(w.agents)))


def test_every_mode_has_valid_crises():
    for mode in modes.MODES:
        w = engine.new_world({"seed": 2, **modes.world_override(mode)})
        s = w.config["crises"]
        assert set(s["kinds"]) == set(crises.STARTERS)
        for _ in range(6):
            next_day(w)


def test_replay_with_crises(tmp_path):
    w = engine.new_world({"seed": 5, "crises": {"chance_per_day": 1.0, "gap_days": 0}})
    log = tmp_path / "run.jsonl"
    stats = run(w, bots_decider(w, ["worker", "thief", "random"], 5), days=5, log_path=log)
    assert stats.get("crisis", 0) >= 2, stats
    assert replay(log).hash() == w.hash()


def test_loners_survive_a_year_of_crises():
    """Crises bring need, not ruin: villagers who never trade with each other still get through."""
    for seed in range(2):
        w = engine.new_world({"seed": seed})
        days = w.config["seasons"]["length_days"] * len(w.config["seasons"]["order"])
        stats = run(w, bots_decider(w, ["loner"], seed), days=days, check_every_tick=False)
        assert stats.get("crisis", 0) >= 5, stats
        assert stats.get("hospital", 0) == 0 and stats.get("evicted", 0) == 0, stats
