"""Step 0 quick fixes after the villain run (2026-10-08): workshops, cooking hint, texts, providers, daily cap."""

import io
import json
import urllib.error

import pytest

from aivillage import budget, crafting, engine, governance, handbook, llm, ops
from aivillage.config import make_config
from aivillage.mapgen import _scale
from aivillage.ops import Ctx
from aivillage.registry import ACTIONS, ActionError

from test_crafting import CFG, act, add_shop, clear, give


@pytest.fixture
def w():
    return engine.new_world(CFG)


def test_carpenter_owner_makes_a_lock_at_own_smithy(w):
    a = w.agents["Anna"]
    a.profession = "carpenter"
    add_shop(w, "Anna", "smithy")
    a.location = a.home
    clear(w, "Anna")
    give(w, "Anna", ore=1, stone=1)
    act(w, "Anna", "craft", recipe="lock")
    assert a.inventory["lock"] == 1


def test_village_smithy_serves_every_trade(w):
    b = w.agents["Boris"]
    assert b.profession != "smith"
    b.location = "smithy"  # the village's own smithy in the classic map
    clear(w, "Boris")
    give(w, "Boris", ore=1, stone=1)
    act(w, "Boris", "craft", recipe="lock")
    assert b.inventory["lock"] == 1


def test_owner_rents_out_the_smithy(w):
    a, b = w.agents["Anna"], w.agents["Boris"]
    add_shop(w, "Anna", "smithy")
    b.location = a.home
    clear(w, "Boris")
    give(w, "Boris", ore=2, stone=2)
    with pytest.raises(ActionError, match="set_workshop_fee"):
        act(w, "Boris", "craft", recipe="lock")
    act(w, "Anna", "set_workshop_fee", workshop="smithy", fee=3)
    ops.move_coins(b, w.agents["Clara"], b.coins - 4)  # Boris keeps 4 coins
    with pytest.raises(ActionError, match="costs 6"):
        act(w, "Boris", "craft", recipe="lock", times=2)
    before = a.coins
    act(w, "Boris", "craft", recipe="lock")
    assert b.inventory["lock"] == 1 and b.coins == 1 and a.coins == before + 3
    seen = crafting.observe(w, "Boris")["workshops_here"]
    assert {"kind": "smithy", "owner": "Anna", "you_may_use": True, "fee_per_item": 3} in seen
    act(w, "Anna", "set_workshop_fee", workshop="smithy", fee=0)
    act(w, "Boris", "craft", recipe="lock")
    assert b.inventory["lock"] == 2 and b.coins == 1
    act(w, "Anna", "set_workshop_fee", workshop="smithy")  # no fee: closed again
    with pytest.raises(ActionError, match="belongs to Anna"):
        act(w, "Boris", "craft", recipe="lock")
    with pytest.raises(ActionError, match="you own no kiln"):
        act(w, "Anna", "set_workshop_fee", workshop="kiln", fee=1)


def test_fee_action_hidden_without_crafting():
    assert crafting.hidden_actions(make_config({"seed": 1})) == {"set_workshop_fee"}
    assert crafting.hidden_actions(make_config(CFG)) == frozenset()


def test_cooking_hint_counts_the_home_chest(w):
    d = w.agents["Dmitri"]
    clear(w, "Dmitri")
    chest = w.chests["chest_Dmitri"]
    ops.mint(w, chest.items, "flour", 2)
    ops.mint(w, chest.items, "wood", 2)
    hint = handbook.observe(w, "Dmitri")
    assert hint["can_craft_now"]["bread"]["times"] == 2
    assert "chest" in hint["can_craft_now"]["bread"]["take_first"]
    assert "in your chest" in hint["not_edible"]["flour"]
    assert d.inventory.get("flour", 0) == 0


def test_polity_hides_mayor_actions():
    cfg = make_config({"seed": 1, "polity": {"enabled": True}})
    for name in ("fund_project", "demand_debt", "rule_debt"):
        assert name in governance.REPLACED
    from aivillage import debts, works
    assert not debts.collection_on(cfg)
    assert "fund_project" not in works.facts(cfg)
    assert "no fine" in governance.facts(cfg)


def test_granary_says_it_does_nothing_without_spoilage():
    from aivillage import construction
    cfg = make_config({"seed": 1})
    rows = [k for k in ("granary", "smokehouse") if construction._row(cfg, k, 1).get("food_keeps_x")]
    for kind in rows:
        assert "changes nothing" in construction.effect_text(cfg, kind, 1)


def test_zero_regrowth_stays_zero():
    assert _scale({"start": 5, "max": 10, "regen": 0}, 2.0)["regen"] == 0
    assert _scale({"start": 5, "max": 10, "regen": 1}, 0.2)["regen"] == 1


def test_news_stamp_has_minutes(w):
    w.minute = 30
    ev = Ctx(w, engine.rng_for(w)).emit("say", "hello", to=["Anna"])
    assert w.agents["Anna"].inbox[-1].startswith(f"[day {ev.day} {ev.hour:02d}:30]")


def test_unknown_model_is_never_free():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
    assert llm.token_cost("anthropic/claude-haiku-5-5", usage) == pytest.approx(0.10)
    assert llm.token_cost("someone/new-model", usage) == pytest.approx(max(p[0] for p in llm.MODEL_PRICES.values()))


def test_openrouter_fails_fast_on_bad_key(monkeypatch):
    c = llm.OpenRouterClient("anthropic/claude-haiku-5.5", api_key="sk-or-x", retries=6)
    calls = []

    def boom(models, messages):
        calls.append(1)
        raise urllib.error.HTTPError(c.URL, 402, "Payment Required", {}, io.BytesIO(b'{"error": {"message": "no credit"}}'))
    monkeypatch.setattr(c, "_post", boom)
    with pytest.raises(llm.ProviderDown, match="402"):
        c.complete([{"role": "user", "content": "hi"}])
    assert len(calls) == 1


def test_openrouter_cost_from_tokens_when_missing(monkeypatch):
    c = llm.OpenRouterClient("anthropic/claude-haiku-5.5", api_key="sk-or-x")
    monkeypatch.setattr(c, "_post", lambda models, messages: ("{}", {"model": models[0], "prompt_tokens": 1_000_000}))
    assert c.complete([])[1]["cost"] == pytest.approx(0.10)


def test_daily_budget_pauses_until_the_next_day(tmp_path, monkeypatch):
    from aivillage.server import LiveSim
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    day = {"d": "2026-10-08"}
    monkeypatch.setattr(budget, "today", lambda: day["d"])
    budget.add(4.0)  # another village spent most of today's money already
    world = engine.new_world({"seed": 1})

    class Usage:
        cost_usd = 0.0

    class Ag:
        usage = Usage()

    decide = lambda name, obs: {"action": {"name": "wait"}}
    decide.agents = {"Anna": Ag()}
    sim = LiveSim(world, decide, 1, daily_budget=5.0)
    sim.budget_poll = 0.01
    published = []
    monkeypatch.setattr(sim, "_publish", published.append)
    sim._check_budget()
    assert not published  # under the cap
    Ag.usage.cost_usd = 1.5
    ticks = {"n": 0}

    def next_day(_):
        ticks["n"] += 1
        if ticks["n"] > 3:
            day["d"] = "2026-10-09"
    monkeypatch.setattr("aivillage.server.time.sleep", next_day)
    sim._check_budget()
    assert [r["type"] for r in published] == ["budget_pause", "budget_resume"]
    assert json.loads((tmp_path / "spend.json").read_text())["2026-10-08"] == pytest.approx(5.5)
    assert budget.spent_today() == 0.0 and not sim.budget_paused
