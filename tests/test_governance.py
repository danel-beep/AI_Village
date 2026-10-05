"""Mayor elections, laws, treasury (aivillage/governance.py)."""

import pytest

from aivillage import engine, ops

from aivillage.invariants import check
from aivillage.registry import ACTIONS
from aivillage.run import bots_decider, run

NAMES = ["Anna", "Boris", "Clara", "Dmitri", "Elena"]


@pytest.fixture
def w():
    return engine.new_world({"seed": 1})


def step(w, decisions=None):
    events = engine.step(w, {n: {"action": {"name": a, "args": args}} for n, (a, args) in (decisions or {}).items()})
    check(w)
    return events


def act(w, name, action, **args):
    return step(w, {name: (action, args)})


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def kinds(events):
    return [e.kind for e in events]


def until_day(w, day):
    events = []
    while w.day < day:
        events += step(w)
    return events


def elect(w, mayor):
    act(w, mayor, "run_for_mayor", pitch="order and bread")
    until_day(w, 2)
    step(w, {n: ("vote", {"candidate": mayor}) for n in NAMES})
    events = until_day(w, 3)
    assert w.governance.mayor == mayor
    return events


def test_weekly_tax_goes_to_treasury(w):
    until_day(w, 8)
    assert w.governance.coins == 5 * w.config["tax_amount"]
    assert all(a.coins == 0 for a in w.agents.values())


def test_without_government_tax_is_burned():
    w = engine.new_world({"seed": 1, "governance": {"enabled": False}})
    until_day(w, 8)
    assert w.governance.coins == 0 and w.ledger["coins"] == 0
    assert "government" not in engine.observe(w, "Anna")
    assert errors(act(w, "Anna", "run_for_mayor", pitch="x"))


def test_election_picks_the_most_voted(w):
    act(w, "Anna", "run_for_mayor", pitch="lower taxes")
    act(w, "Boris", "run_for_mayor", pitch="free fish")
    assert errors(act(w, "Clara", "vote", candidate="Anna"))  # not election day yet
    assert set(engine.observe(w, "Clara")["government"]["candidates"]) == {"Anna", "Boris"}
    until_day(w, 2)
    assert engine.observe(w, "Clara")["government"]["election_today"]
    assert errors(act(w, "Clara", "vote", candidate="Dmitri"))  # not a candidate
    step(w, {"Anna": ("vote", {"candidate": "Anna"}), "Boris": ("vote", {"candidate": "Boris"}),
             "Clara": ("vote", {"candidate": "Boris"})})
    act(w, "Clara", "vote", candidate="Anna")  # changed her mind
    act(w, "Dmitri", "vote", candidate="Anna")
    events = until_day(w, 3)
    assert w.governance.mayor == "Anna"
    assert "elected" in kinds(events)
    assert not w.governance.candidates and not w.governance.votes
    obs = engine.observe(w, "Anna")["government"]
    assert obs["you_are_mayor"] and obs["next_election_day"] == 7


def test_election_without_votes_keeps_nobody(w):
    act(w, "Anna", "run_for_mayor", pitch="me")
    events = until_day(w, 3)
    assert w.governance.mayor is None
    assert any(e.kind == "election" and "Nobody voted" in e.text for e in events)


def test_only_mayor_proposes_and_majority_passes(w):
    elect(w, "Anna")
    assert errors(act(w, "Boris", "propose_law", law="tax", value=5))
    assert "propose_law" not in ACTIONS.available(engine.Ctx(w, engine.rng_for(w)), w.agents["Boris"])
    assert errors(act(w, "Anna", "propose_law", law="tax", value=500))  # out of limits
    events = act(w, "Anna", "propose_law", law="tax", value=5)
    pid = next(e.data["law"] for e in events if e.kind == "law_proposed")
    act(w, "Boris", "vote_law", proposal_id=pid, vote="yes")
    assert w.governance.laws == {}  # 2 of 5 is not a majority
    events = act(w, "Clara", "vote_law", proposal_id=pid, vote="yes")
    assert "law_passed" in kinds(events) and w.governance.laws["tax"] == 5
    assert engine.observe(w, "Boris")["time"]["tax"] == 5
    until_day(w, 8)
    assert w.governance.coins == 5 * 5


def test_law_fails_on_no_majority_and_on_timeout(w):
    elect(w, "Anna")
    act(w, "Anna", "propose_law", law="mayor_salary", value=20)
    pid = next(iter(w.governance.proposals))
    step(w, {n: ("vote_law", {"proposal_id": pid, "vote": "no"}) for n in ["Boris", "Clara", "Dmitri"]})
    assert not w.governance.proposals and "mayor_salary" not in w.governance.laws
    act(w, "Anna", "propose_law", law="theft_fine", value=10)
    events = []
    for _ in range(w.config["governance"]["law_vote_hours"]):
        events += step(w)
    assert "law_failed" in kinds(events) and not w.governance.proposals


def test_exile_bans_market_and_votes(w):
    elect(w, "Anna")
    act(w, "Anna", "propose_law", law="exile", person="Boris")
    pid = next(iter(w.governance.proposals))
    step(w, {"Clara": ("vote_law", {"proposal_id": pid, "vote": "yes"}),
             "Dmitri": ("vote_law", {"proposal_id": pid, "vote": "yes"})})
    assert w.governance.exiled["Boris"] == 3 + w.config["governance"]["exile_days"]
    w.agents["Boris"].location = "market"
    ops.mint(w, w.agents["Boris"].inventory, "fish", 2)
    assert any("exiled" in t for t in errors(act(w, "Boris", "sell", item="fish", qty=1)))
    assert "sell" not in engine.observe(w, "Boris")["available_actions"]
    assert errors(act(w, "Boris", "run_for_mayor", pitch="revenge"))
    until_day(w, w.governance.exiled["Boris"])
    assert not w.governance.exiled
    w.agents["Boris"].location = "market"
    assert not errors(act(w, "Boris", "sell", item="fish", qty=1))


def test_exiled_mayor_loses_office(w):
    elect(w, "Anna")
    act(w, "Anna", "propose_law", law="exile", person="Anna")
    pid = next(iter(w.governance.proposals))
    step(w, {n: ("vote_law", {"proposal_id": pid, "vote": "yes"}) for n in ["Boris", "Clara"]})
    assert w.governance.mayor is None


def test_report_theft_fines_the_thief(w):
    elect(w, "Anna")
    act(w, "Anna", "propose_law", law="theft_fine", value=7)
    pid = next(iter(w.governance.proposals))
    step(w, {n: ("vote_law", {"proposal_id": pid, "vote": "yes"}) for n in ["Boris", "Clara"]})
    assert w.governance.laws["theft_fine"] == 7
    for n in NAMES:
        w.agents[n].location = "square"
    w.config["steal_notice_chance"] = 1.0
    ops.mint(w, w.agents["Clara"].inventory, "wood", 3)
    assert errors(act(w, "Boris", "report_theft", person="Dmitri"))  # saw nothing
    act(w, "Dmitri", "steal", target="Clara", item="wood", qty=1)
    assert any(c["thief"] == "Dmitri" for c in w.governance.crimes)
    before = w.agents["Dmitri"].coins
    events = act(w, "Boris", "report_theft", person="Dmitri")
    assert "theft_report" in kinds(events)
    assert w.agents["Dmitri"].coins == before - 7
    assert not any("Boris" in c["known_by"] for c in w.governance.crimes if c["thief"] == "Dmitri")


def test_payout_and_grant_spend_the_treasury(w):
    elect(w, "Anna")
    ops.mint_coins(w, w.governance, 50)
    act(w, "Anna", "propose_law", law="grant", person="Anna", value=30)
    pid = next(iter(w.governance.proposals))
    before = w.agents["Anna"].coins
    step(w, {n: ("vote_law", {"proposal_id": pid, "vote": "yes"}) for n in ["Boris", "Clara"]})
    assert w.agents["Anna"].coins == before + 30 and w.governance.coins == 20
    act(w, "Anna", "propose_law", law="payout")
    pid = next(iter(w.governance.proposals))
    coins = {n: a.coins for n, a in w.agents.items()}
    step(w, {n: ("vote_law", {"proposal_id": pid, "vote": "yes"}) for n in ["Boris", "Clara"]})
    assert all(w.agents[n].coins == coins[n] + 4 for n in NAMES) and w.governance.coins == 0


def test_mayor_salary_is_paid_at_dawn(w):
    elect(w, "Anna")
    ops.mint_coins(w, w.governance, 10)
    act(w, "Anna", "propose_law", law="mayor_salary", value=4)
    pid = next(iter(w.governance.proposals))
    step(w, {n: ("vote_law", {"proposal_id": pid, "vote": "yes"}) for n in ["Boris", "Clara"]})
    before = w.agents["Anna"].coins
    until_day(w, 4)
    assert w.agents["Anna"].coins == before + 4 and w.governance.coins == 6


def test_world_roundtrip_keeps_governance(w):
    elect(w, "Anna")
    act(w, "Anna", "propose_law", law="tax", value=3)
    w2 = engine.World.from_dict(w.to_dict())
    assert w2.hash() == w.hash() and w2.governance.proposals[next(iter(w.governance.proposals))].value == 3


def test_random_bots_use_government():
    w = engine.new_world({"seed": 4})
    log = []
    run(w, bots_decider(w, ["random"], 4), days=8, on_tick=lambda world, ev: log.extend(e.kind for e in ev))
    assert "candidate" in log and "election_day" in log
