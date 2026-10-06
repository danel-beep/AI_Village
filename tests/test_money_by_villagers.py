"""Money and taxes belong to the villagers (Danel 2026-10-06): in «С нуля» nobody has coins before the market
square, no world rule taxes anyone, each polity decides whether it taxes, how much and how often; god mode can
change one polity's tax (or the village-wide tax in «Обычный») during play."""

from aivillage import engine, governance, knobs, modes, polity, taxes
from aivillage.invariants import check
from aivillage.llm import world_facts

from test_neutrality import evaluative
from test_polity import act, errors, found, hall, names, step, until, world


def test_camp_start_has_no_coins_even_when_unfair():
    for unfair in (0.0, 1.0):
        w = engine.new_world(modes.world_override("survival", {"seed": 3, "start_coins": 80,
                                                               "map": {"unfairness": unfair}}))
        assert all(a.coins == 0 for a in w.agents.values())


def test_no_world_tax_with_polities_only_the_polity_laws():
    w = world()
    a, b, *_ = names(w)
    hall(w, builders=[a, b])
    obs = engine.observe(w, a, consume_inbox=False)
    assert "tax_bill" not in obs and "tax" not in obs["time"]  # the world's land tax was shown, never taken
    row = obs["polities"][0]
    assert row["tax_per_member"] == 0 and "your_tax_so_far" not in row and row["next_tax_day"] > w.day
    facts = world_facts(w.config)
    assert "income_tax" in facts and "has no tax until a law sets one" in facts and evaluative(facts) == []


def test_income_wealth_and_frequency_are_laws_of_the_polity():
    w = world()
    a, b, c, d, *_ = names(w)
    p = found(w, [a, b, c], name="North", coin="mark", form="ruler", leader=lambda n: a)
    assert errors(act(w, a, "polity_propose", law="wealth_tax", value=90), a)  # over the limit
    for law, value in (("income_tax", 50), ("wealth_tax", 10), ("tax_every", 2)):
        events = act(w, a, "polity_propose", law=law, value=value)
        assert any(e.kind == "polity_law_passed" for e in events)
    assert p["laws"] == {"tax": 0, "income_tax": 50, "wealth_tax": 10, "tax_every": 2}
    taxes.record_income(w, w.agents[b], 20)  # e.g. sold to the trader
    taxes.record_income(w, w.agents[d], 20)  # d is in no polity
    coins = {n: w.agents[n].coins for n in (a, b, c, d)}
    row = next(r for r in engine.observe(w, b, consume_inbox=False)["polities"] if r["id"] == p["id"])
    assert row["your_tax_so_far"] == {"total": 10 + coins[b] // 10, "income": 10, "wealth": coins[b] // 10}
    day = row["next_tax_day"]
    assert day <= w.day + 2
    until(w, lambda: w.day == day)
    assert w.agents[b].coins == coins[b] - 10 - coins[b] // 10
    assert w.agents[a].coins == coins[a] - coins[a] // 10 and w.agents[d].coins == coins[d]
    assert w.agents[b].earned_since_tax == 0 and w.agents[d].earned_since_tax == 20
    act(w, d, "join_polity", polity="North")
    assert w.agents[d].earned_since_tax == 0  # income from before joining is not taxed
    check(w)


def test_god_changes_one_polity_tax_and_villagers_see_the_law():
    w = world()
    a, b, c, d, e, *_ = names(w)
    p = found(w, [a, b], name="North", coin="mark", form="ruler", leader=lambda n: a)
    hall(w, location="market", builders=[c])
    q = next(x for x in w.polities.values() if x is not p)
    events = engine.step(w, {}, [{"name": "set_tax", "args": {"polity": "North", "tax": 7, "every_days": 3}}])
    check(w)
    assert p["laws"]["tax"] == 7 and p["laws"]["tax_every"] == 3 and q["laws"] == {"tax": 0}
    said = [ev for ev in events if ev.kind == "polity_tax_set"]
    assert said and said[0].visibility == "public" and "god" not in said[0].text.lower()
    events = engine.step(w, {}, [{"name": "set_tax", "args": {"tax": 5}}])  # no polity picked
    assert any(ev.kind == "god_error" for ev in events)


def test_god_changes_the_village_tax_in_ordinary_mode():
    w = engine.new_world(modes.world_override("crafts", {"seed": 2}))
    assert not governance.polity_on(w.config)
    engine.step(w, {}, [{"name": "set_tax", "args": {"tax": 3, "income_pct": 25, "wealth_pct": 0}}])
    check(w)
    assert governance.tax_amount(w) == 3 and taxes.rate(w, "sales_tax") == 25 and taxes.rate(w, "wealth_tax") == 0
    events = engine.step(w, {}, [{"name": "set_tax", "args": {"every_days": 2}}])
    assert any(ev.kind == "god_error" for ev in events)


def test_start_screen_hides_world_tax_rates_when_polities_decide():
    by = {k["key"]: k for k in knobs.active()}
    for key in ("tax_amount", "sales_pct", "wealth_pct", "burn_pct", "tax_every_days"):
        assert by[key]["hide_if"] == {"polities": [True]}
    assert knobs.mode_defaults("survival")["polities"] is True
    assert knobs.mode_defaults("crafts")["polities"] is False  # «Обычный» keeps its tax sliders
    assert by["start_coins"]["hide_if"] == {"mode": ["survival"], "start_stage": ["camp", "hamlet"]}
    for k in knobs.active():
        for key in k.get("hide_if", {}):
            assert key in by
