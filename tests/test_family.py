"""Friendship, marriage, divorce and inheritance (aivillage/family.py)."""

import pytest

from aivillage import engine, family, ops
from aivillage.invariants import check
from aivillage.run import bots_decider, replay, run


@pytest.fixture
def w():
    w = engine.new_world({"seed": 1})
    for a in w.agents.values():
        a.location = "square"
    return w


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def marry(w, a="Anna", b="Boris"):
    w.kin.feelings = {a: {b: 30}, b: {a: 30}}
    assert not errors(act(w, a, "propose", person=b))
    ev = act(w, b, "answer_proposal", person=a, accept=True)
    assert not errors(ev) and any(e.kind == "wedding" for e in ev)


def test_feelings_grow_from_gifts_and_are_directed(w):
    ops.mint(w, w.agents["Anna"].inventory, "fish", 1)
    act(w, "Anna", "give", to="Boris", items={"fish": 1})
    assert family.feeling(w, "Boris", "Anna") == 5
    assert family.feeling(w, "Anna", "Boris") == 0  # directed
    engine.step(w, {})
    assert family.feeling(w, "Boris", "Anna") == 5  # counted once


def test_hang_out_once_a_day_and_both_ways(w):
    assert not errors(act(w, "Anna", "hang_out", person="Boris"))
    assert family.feeling(w, "Anna", "Boris") == family.feeling(w, "Boris", "Anna") == 4
    assert errors(act(w, "Boris", "hang_out", person="Anna"))
    obs = engine.observe(w, "Anna")
    assert obs["relations"]["feelings"]["Boris"] == {"score": 4, "label": "liked"}


def test_propose_needs_closeness(w):
    ev = act(w, "Anna", "propose", person="Boris")
    assert "close enough" in errors(ev)[0]
    assert not w.kin.proposals


def test_wedding_shares_house_and_chests(w):
    marry(w)
    assert family.spouse_of(w, "Boris") == "Anna"
    assert w.agents["Boris"].home == "home_Anna"
    assert "Boris" in w.chests["chest_Anna"].shared_with and "Anna" in w.chests["chest_Boris"].shared_with
    obs = engine.observe(w, "Boris")
    assert obs["relations"]["spouse"] == "Anna" and obs["relations"]["family_home"] == "home_Anna"
    assert errors(act(w, "Clara", "propose", person="Anna"))


def test_refusal_and_divorce(w):
    w.kin.feelings = {"Anna": {"Boris": 30}}
    act(w, "Anna", "propose", person="Boris")
    act(w, "Boris", "answer_proposal", person="Anna", accept=False)
    assert not w.kin.proposals and not w.kin.marriages
    marry(w)
    act(w, "Boris", "divorce")
    assert not w.kin.marriages and w.agents["Boris"].home == "home_Boris"
    assert not w.chests["chest_Anna"].shared_with
    assert family.feeling(w, "Anna", "Boris") < 30


def test_spouse_inherits_on_death(w):
    w.config["death_mode"] = "death"
    marry(w)
    anna = w.agents["Anna"]
    ops.mint(w, anna.inventory, "ore", 2)
    ops.mint(w, w.chests["chest_Anna"].items, "wood", 3)
    total = anna.coins + w.chests["chest_Anna"].coins + w.chests["chest_Boris"].coins
    anna.health = 0
    ev = engine.step(w, {})
    check(w)
    assert any(e.kind == "inheritance" for e in ev)
    boris_chest = w.chests["chest_Boris"]
    assert boris_chest.items == {"ore": 2, "wood": 3} and boris_chest.coins == total
    assert not anna.inventory and anna.coins == 0 and not w.kin.marriages
    assert w.agents["Boris"].home == "home_Boris"


def test_secret_wedding_is_known_only_to_the_couple(w):
    w.kin.feelings = {"Anna": {"Boris": 30}, "Boris": {"Anna": 30}}
    ev = act(w, "Anna", "propose", person="Boris", public=False)
    assert [e.visibility for e in ev if e.kind == "proposal"] == ["private"]
    ev = act(w, "Boris", "answer_proposal", person="Anna", accept=True)
    (wed,) = [e for e in ev if e.kind == "wedding"]
    assert wed.visibility == "private" and set(wed.to) | {wed.actor} == {"Anna", "Boris"}
    assert family.spouse_of(w, "Boris") == "Anna" and not next(iter(w.kin.marriages.values())).public


def test_estate_pays_debts_then_passes_houses(w):
    from aivillage.state import Debt
    w.config["death_mode"] = "death"
    marry(w)
    w.debts["d1"] = Debt("d1", "Clara", "Anna", 15, 5)
    clara, total = w.agents["Clara"].coins, w.agents["Anna"].coins + w.chests["chest_Boris"].coins
    houses = [h for h, p in w.plots.items() if p.owner == "Anna"]
    w.agents["Anna"].health = 0
    ev = engine.step(w, {})
    check(w)
    assert any(e.kind == "estate_debt" for e in ev) and w.debts["d1"].status == "repaid"
    assert w.agents["Clara"].coins == clara + 15 and w.chests["chest_Boris"].coins == total - 15
    assert houses and all(w.plots[h].owner == "Boris" for h in houses)


def test_best_friend_inherits_without_spouse(w):
    w.config["death_mode"] = "death"
    w.kin.feelings = {"Anna": {"Clara": 50, "Boris": 35, "Elena": -40}}
    w.agents["Anna"].health = 0
    engine.step(w, {})
    check(w)
    assert w.chests["chest_Clara"].coins == 20


def test_feelings_decay_at_night_except_spouses(w):
    marry(w)
    w.kin.feelings["Clara"] = {"Dmitri": 1}
    for _ in range(20):
        if w.day > 1:
            break
        engine.step(w, {})
    assert "Clara" not in w.kin.feelings
    assert family.feeling(w, "Anna", "Boris") >= 46


@pytest.mark.parametrize("seed", range(3))
def test_fuzz_courtship_replay(tmp_path, seed):
    """Random bots (never hungry) that meet at the square and court whoever is there:
    invariants hold every tick, weddings happen, replay is exact."""
    w = engine.new_world({"seed": seed, "satiety_loss_per_hour": 0, "satiety_loss_asleep_per_hour": 0,
                          "satiety_loss_night": 0, "family": {"propose_min": 10, "on_event": {}},
                          "disabled_actions": ["attack", "set_fire"]})  # random violence would sour every courtship
    rnd = bots_decider(w, ["random"], seed)

    def decide(name, obs):
        rel, here = obs["relations"], obs["here"]
        acts = obs["available_actions"]
        others = [p["name"] for p in here["people"] if not p["asleep"]]
        if rel["proposals_to_you"] and "answer_proposal" in acts:
            return {"action": {"name": "answer_proposal",
                               "args": {"person": rel["proposals_to_you"][0]["from"], "accept": True}}}
        if obs["time"]["hour"] % 3 == 0:
            return rnd(name, obs)
        if here["id"] != "square":
            return {"action": {"name": "move", "args": {"to": "square"}}}
        if others:
            who = others[obs["time"]["hour"] % len(others)]
            close = rel["feelings"].get(who, {}).get("score", 0) >= 10
            act = "propose" if close and "propose" in acts else "hang_out"
            return {"action": {"name": act, "args": {"person": who}}}
        return rnd(name, obs)

    seen = set()
    path = tmp_path / "f.jsonl"
    run(w, decide, days=20, log_path=path, on_tick=lambda w2, evs: seen.update(e.kind for e in evs))
    assert {"hang_out", "proposal", "wedding"} <= seen
    assert replay(path).hash() == w.hash()


def test_unpaid_debt_hurts_the_lender(w):
    act(w, "Anna", "lend", to="Boris", coins=5, repay_coins=6, due_day=2)
    act(w, "Boris", "accept", offer_id=[*w.offers][-1])  # a loan starts when the borrower accepts
    assert family.feeling(w, "Boris", "Anna") == 4
    while w.day < 4:
        engine.step(w, {})
    assert family.feeling(w, "Anna", "Boris") < -10
