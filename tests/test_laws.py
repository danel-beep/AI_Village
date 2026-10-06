"""Voluntary laws (config `laws.enforcement`): taxes and fines become public bills in the debt book."""

import pytest

from aivillage import engine, ops
from aivillage.debts import TREASURY
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.run import bots_decider, replay, run

NAMES = ["Anna", "Boris", "Clara", "Dmitri", "Elena"]
CFG = {"seed": 1, "crises": {"enabled": False}, "tax_amount": 10, "tax_every_days": 2,
       "taxes": {"enabled": True, "burn_pct": 20}, "laws": {"enforcement": "voluntary", "bill_days": 2},
       "debts": {"auto_collect": True, "late_fee_pct": 10}}


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


def set_coins(w, name, n):
    a = w.agents[name]
    if a.coins > n:
        ops.burn_coins(w, a, a.coins - n)
    else:
        ops.mint_coins(w, a, n - a.coins)


def bills(w, name=None):
    return [d for d in w.debts.values() if d.lender == TREASURY and (name is None or d.borrower == name)]


def test_auto_is_the_default():
    w = engine.new_world({"seed": 1})
    assert w.config["laws"]["enforcement"] == "auto"
    assert "locked out" in world_facts(w.config) and "pay_bill" not in world_facts(w.config)


def test_tax_day_writes_public_bills_and_takes_nothing(w):
    set_coins(w, "Anna", 0)
    set_coins(w, "Boris", 50)
    events = until_day(w, 3)
    assert w.agents["Boris"].coins == 50 and w.governance.coins == 0
    assert w.agents["Anna"].evicted_until_day <= w.day  # nobody is evicted
    assert not [e for e in events if e.kind in ("tax", "evicted")]
    listed = [e for e in events if e.kind == "tax_bills"]
    assert len(listed) == 1 and listed[0].visibility == "public" and "Anna 10" in listed[0].text
    assert {d.borrower for d in bills(w)} == set(NAMES)
    row = next(r for r in engine.observe(w, "Clara")["board"]["debts"] if r["borrower"] == "Anna")
    assert row["lender"] == TREASURY and row["kind"] == "tax" and row["coins_owed"] == 10


def test_pay_bill_in_parts_goes_to_the_treasury(w):
    until_day(w, 3)
    set_coins(w, "Boris", 50)
    d = bills(w, "Boris")[0]
    events = act(w, "Boris", "pay_bill", debt_id=d.id, coins=5)
    paid = next(e for e in events if e.kind == "bill_paid")
    assert paid.visibility == "public" and d.coins_owed == 5 and d.status == "open"
    assert w.agents["Boris"].coins == 45 and w.governance.coins == 4  # 20% of a tax leaves the game
    assert errors(act(w, "Anna", "pay_bill", debt_id=d.id))  # not hers
    act(w, "Boris", "repay", debt_id=d.id, coins=99)  # repay on a bill pays the bill
    assert d.status == "repaid" and w.agents["Boris"].coins == 40 and w.governance.coins == 8


def test_unpaid_bill_is_marked_overdue_and_never_collected(w):
    until_day(w, 3)
    set_coins(w, "Clara", 80)
    feelings = {n: dict(w.kin.feelings.get(n, {})) for n in NAMES}
    events = until_day(w, 5)
    d = next(d for d in bills(w, "Clara") if d.day == 3)
    assert d.status == "defaulted" and d.coins_owed == 10  # no late fee
    assert w.agents["Clara"].coins == 80  # nothing seized
    assert any(e.kind == "bill_overdue" and e.data["debt"] == d.id and e.visibility == "public" for e in events)
    assert not [e for e in events if e.kind in ("default", "debt_seized", "debt_garnished")]
    assert {n: dict(w.kin.feelings.get(n, {})) for n in NAMES} == feelings  # no rule turns anyone against her
    act(w, "Clara", "pay_bill", debt_id=d.id)
    assert d.status == "repaid"


def test_reported_theft_writes_a_fine_bill(w):
    w.governance.laws["theft_fine"] = 7
    for n in NAMES:
        w.agents[n].location = "square"
    w.config["steal_notice_chance"] = 1.0
    ops.mint(w, w.agents["Clara"].inventory, "wood", 3)
    act(w, "Dmitri", "steal", target="Clara", item="wood", qty=1)
    before = w.agents["Dmitri"].coins
    events = act(w, "Boris", "report_theft", person="Dmitri")
    rep = next(e for e in events if e.kind == "theft_report")
    fine = bills(w, "Dmitri")[0]
    assert w.agents["Dmitri"].coins == before and fine.kind == "fine" and fine.coins_owed == 7
    assert rep.data["bill"] == fine.id and "owes the treasury 7" in rep.text
    act(w, "Dmitri", "pay_bill", debt_id=fine.id)
    assert w.governance.coins == 7  # a fine goes whole to the treasury


def test_facts_say_nobody_takes_it(w):
    facts = world_facts(w.config)
    assert "pay_bill" in facts and "locked out" not in facts and "tax and fine bills excepted" in facts


def test_random_bots_keep_invariants_and_replay(tmp_path):
    w = engine.new_world({**CFG, "seed": 3, "crises": {"enabled": True}})
    kinds = []
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["random"], 3), days=8, log_path=log,
        on_tick=lambda world, ev: (check(world), kinds.extend(e.kind for e in ev)))
    assert "tax_bills" in kinds and "bill_overdue" in kinds
    assert replay(log).hash() == w.hash()
