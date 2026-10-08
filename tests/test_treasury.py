"""A treasury worth holding (Danel 2026-10-08: first what money is for, then where it comes from): a polity's wage
law pays members for common building work, its holder can fund_project and buy from the passing merchant,
a small minted seed fills it each dawn; the merchant sells goods nobody makes (a fur cloak keeps a winter night
warmer, steel tools, medicine)."""

from aivillage import construction, engine, merchant, modes, ops, polity, works
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.run import bots_decider, replay, run

from test_neutrality import evaluative
from test_polity import QUIET, act, errors, found, step, until

RULER = {"form": "ruler", "leader": lambda n: "Anna", "name": "Dale", "coin": "shell"}


def town(**extra):
    """«С нуля» at the town stage: a town hall (so a polity) and the market square stand; 40 coins each."""
    extra["polity"] = {"income_per_member_per_day": 0, **extra.get("polity", {})}
    w = engine.new_world(modes.world_override("normal", {"seed": 5, **QUIET, "progress": {"start_stage": "town"},
                                                           **extra}))
    for a in w.agents.values():
        ops.mint_coins(w, a, 40 - a.coins)
    return w


def ruled(w, members=("Anna", "Boris", "Clara")):
    """The prebuilt hall's polity, `members` in it, Anna its ruler (and so the treasury holder)."""
    step(w)
    p = next(iter(w.polities.values()))
    for n in members:
        if n not in p["members"]:
            act(w, n, "join_polity", polity=p["id"])
    for n in members:
        for topic, choice in RULER.items():
            act(w, n, "polity_vote", topic=topic, choice=choice(n) if callable(choice) else choice)
    until(w, lambda: not p["ballot"])
    assert p["keeper"] == "Anna" and p["form"] == "ruler"
    return p


def law(w, p, name, value):
    act(w, p["keeper"], "polity_propose", law=name, value=value)
    assert p["laws"][name] == value


def test_seed_income_only_once_the_polity_has_a_form_and_two_members():
    w = town(polity={"income_per_member_per_day": 1})
    step(w)
    p = next(iter(w.polities.values()))
    until(w, lambda: w.day == 2)
    assert p["coins"] == 0  # no form yet
    p = ruled(w)
    day, before = w.day, p["coins"]
    until(w, lambda: w.day == day + 1)
    assert p["coins"] == before + 3
    obs = engine.observe(w, "Boris", consume_inbox=False)
    assert obs["polities"][0]["treasury_income_per_member_per_day"] == 1
    off = town()
    step(off)
    assert "treasury_income_per_member_per_day" not in engine.observe(off, "Anna", consume_inbox=False)["polities"][0]


def test_wage_law_pays_members_for_village_project_hours_from_the_treasury():
    w = town()
    p = ruled(w)
    ops.mint_coins(w, polity._Purse(p), 10)
    law(w, p, "wage", 3)
    for n in ("Boris", "Dmitri"):
        w.agents[n].location = works.SITE
    proj = works.open_project(engine_ctx(w), "well", 1, "Boris")
    coins = {n: w.agents[n].coins for n in ("Boris", "Dmitri")}
    act(w, "Boris", "build_work", project_id=proj.id)
    act(w, "Dmitri", "build_work", project_id=proj.id)  # not a member: no wage
    assert w.agents["Boris"].coins == coins["Boris"] + 3 and w.agents["Dmitri"].coins == coins["Dmitri"]
    assert p["coins"] == 7
    row = engine.observe(w, "Clara", consume_inbox=False)["polities"][0]
    assert row["wage_per_hour"] == 3 and row["treasury_spent_lately"] == [f"day {w.day}: wage to Boris, 3"]
    p["coins"] = 0  # an empty treasury pays nothing
    w.ledger["coins"] -= 7
    act(w, "Boris", "build_work", project_id=proj.id)
    assert w.agents["Boris"].coins == coins["Boris"] + 3
    check(w)


def test_wage_for_counted_hours_on_a_common_building():
    w = town()
    p = ruled(w)
    ops.mint_coins(w, polity._Purse(p), 20)
    law(w, p, "wage", 2)
    ctx = engine_ctx(w)
    for n in ("Anna", "Boris", "Clara", "Dmitri"):
        w.agents[n].location = "square"
    act(w, "Anna", "start_building", kind="tavern")
    site = next(s for s in construction.sites(w).values() if s["kind"] == "tavern" and s["owner"] is None)
    site.update(needs={}, hours=50, min_workers=2)  # materials and length are not what this test is about
    workers = ["Boris", "Clara"]
    act(w, "Dmitri", "construct", site_id=site["id"])  # not a member: works unpaid
    coins = {n: w.agents[n].coins for n in workers}
    for n in workers:
        act(w, n, "construct", site_id=site["id"])
    for n in workers:
        assert w.agents[n].coins == coins[n] + 2, n
    assert w.agents["Dmitri"].coins == 40 and p["coins"] == 16
    assert ctx is not None
    check(w)


def engine_ctx(w):
    from aivillage.engine import rng_for
    return ops.Ctx(w, rng_for(w, "test"))


def test_holder_funds_a_village_project_from_the_polity_treasury():
    w = town()
    p = ruled(w)
    ops.mint_coins(w, polity._Purse(p), 15)
    proj = works.open_project(engine_ctx(w), "well", 1, "Anna")
    errs = errors(act(w, "Boris", "fund_project", project_id=proj.id, coins=5), "Boris")
    assert errs and "treasury holder" in errs[0]
    ev = act(w, "Anna", "fund_project", project_id=proj.id, coins=10)
    done = [e for e in ev if e.kind == "fund_project"]
    assert done and done[0].visibility == "public" and "treasury of Dale" in done[0].text
    assert p["coins"] == 5 and proj.contributed["coins"] == 10
    assert any("fund_project by Anna" in x["what"] for x in p["spent"])
    check(w)


def test_holder_fund_project_keeps_embezzlement_books_honest():
    w = town()
    p = ruled(w)
    ops.mint_coins(w, polity._Purse(p), 20)
    act(w, "Anna", "polity_embezzle", coins=12)
    proj = works.open_project(engine_ctx(w), "well", 1, "Anna")
    act(w, "Anna", "fund_project", project_id=proj.id, coins=20)
    assert p["coins"] == 0 and proj.contributed["coins"] == 8 and polity.books(p) == 12
    check(w)


def merchant_here(w):
    until(w, lambda: merchant.here(w) is not None, limit=4000)
    return merchant.here(w)


def test_merchant_comes_sells_and_leaves():
    w = town()
    h = merchant_here(w)
    assert h["place"] == "market" and h["goods"]["fur_cloak"]["left"] >= 1
    obs = engine.observe(w, "Boris", consume_inbox=False)
    assert obs["merchant"]["sells"]["fur_cloak"]["price"] == 30
    b = w.agents["Boris"]
    b.location = "market"
    assert "buy_from_merchant" in engine.observe(w, "Boris", consume_inbox=False)["available_actions"]
    left, coins = h["goods"]["fur_cloak"]["left"], b.coins
    act(w, "Boris", "buy_from_merchant", item="fur_cloak")
    assert b.inventory.get("fur_cloak") == 1 and b.coins == coins - 30 and h["goods"]["fur_cloak"]["left"] == left - 1
    errs = errors(act(w, "Boris", "buy_from_merchant", item="fur_cloak", qty=20), "Boris")
    assert errs
    errs = errors(act(w, "Boris", "buy", item="fur_cloak", qty=1), "Boris")  # the trader does not deal in it
    assert errs and "does not deal" in errs[0]
    errs = errors(act(w, "Boris", "buy_from_merchant", item="medicine", from_treasury=True), "Boris")
    assert errs and "hold no treasury" in errs[0]
    until(w, lambda: merchant.here(w) is None, limit=4000)
    assert w.merchant["next_day"] > w.day
    check(w)


def test_holder_buys_from_the_merchant_with_treasury_coins_in_public():
    w = town()
    p = ruled(w)
    ops.mint_coins(w, polity._Purse(p), 30)
    merchant_here(w)
    w.agents["Anna"].location = "market"
    coins = w.agents["Anna"].coins
    ev = act(w, "Anna", "buy_from_merchant", item="medicine", qty=2, from_treasury=True)
    sale = [e for e in ev if e.kind == "merchant_sale"]
    assert sale and sale[0].visibility == "public" and sale[0].data["treasury"]
    assert p["coins"] == 6 and w.agents["Anna"].coins == coins and w.agents["Anna"].inventory["medicine"] == 2
    assert any("from the merchant" in x["what"] for x in p["spent"])
    check(w)


def test_no_merchant_before_the_trader_or_when_off():
    w = engine.new_world(modes.world_override("normal", {"seed": 5, **QUIET}))  # camp start: no market yet
    until(w, lambda: w.day == 12, limit=4000)
    assert merchant.here(w) is None and not w.merchant
    w = town(merchant={"enabled": False})
    until(w, lambda: w.day == 12, limit=4000)
    assert not w.merchant and "merchant" not in world_facts(w.config)


def test_a_fur_cloak_keeps_a_winter_night_warmer():
    from aivillage import seasons
    w = town()
    cfg = w.config
    winter = next(d for d in range(1, 40) if seasons.season_of(cfg, d) == "winter")
    assert seasons.night_hunger(cfg, winter) == 10
    assert seasons.night_hunger(cfg, winter, {"fur_cloak": 1}) == 2
    assert seasons.night_hunger(cfg, winter, {"clothes": 1, "fur_cloak": 1}) == 2
    assert seasons.night_hunger(cfg, winter, {"clothes": 1}) == 5
    assert seasons.night_hunger(cfg, winter - 7, {"fur_cloak": 1}) == 0
    assert "fur_cloak -8" in world_facts(cfg)


def test_merchant_goods_have_uses():
    w = town()
    cfg = w.config
    assert cfg["crafting"]["tools"]["steel_axe"]["multiplier"] > cfg["crafting"]["tools"]["iron_axe"]["multiplier"]
    assert "medicine" in cfg["illness"]["cure_items"]
    assert all(not cfg["items"][i].get("tradable", True) for i in merchant.goods(cfg))


def test_facts_are_neutral_and_say_the_rules():
    w = town(polity={"income_per_member_per_day": 1})
    facts = world_facts(w.config)
    assert "wage (coins from the treasury" in facts and "1 new coin(s) per member" in facts
    assert "A merchant from afar" in facts and "buy from_treasury" in facts
    assert "fund_project" in facts
    assert evaluative(facts) == []


def test_random_bots_with_merchant_and_treasury_replay(tmp_path):
    w = engine.new_world(modes.world_override("normal", {"seed": 9, **QUIET, "progress": {"start_stage": "town"},
                                                           "merchant": {"first_gap_days": [1, 1]}}))
    log = tmp_path / "fuzz.jsonl"
    run(w, bots_decider(w, ["random"], 3), days=6, log_path=log)
    assert w.merchant.get("visits") and replay(log).hash() == w.hash()


def test_scenario_polity_edit_and_the_treasury_scenario_builds():
    from aivillage import scenario
    w = scenario.start_world(scenario.load("treasury_uses"))
    p = next(iter(w.polities.values()))
    assert p["form"] == "ruler" and p["keeper"] == "Boris" and p["rulers"] == ["Boris"] and p["coins"] == 40
    assert sorted(p["members"]) == sorted(w.agents) and not p["ballot"]
    check(w)
