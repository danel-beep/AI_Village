"""The village debt book (aivillage/debts.py): IOUs, pledges, late fees, collection through the mayor."""

import pytest

from aivillage import debts, engine, ops
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.run import bots_decider, run


MANUAL = {"auto_collect": False}  # the book alone, without automatic collection


@pytest.fixture
def w():
    return engine.new_world({"seed": 1, "debts": MANUAL})


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


def only_debt(w):
    return next(iter(w.debts.values()))


def test_promise_with_pledge_is_held_and_returned_on_repay(w):
    ops.mint(w, w.agents["Boris"].inventory, "wood", 3)
    ev = act(w, "Boris", "promise", to="Anna", coins=4, due_day=3, note="bread on credit", pledge={"wood": 2})
    assert not errors(ev), errors(ev)
    d = only_debt(w)
    assert (d.lender, d.borrower, d.kind, d.pledge) == ("Anna", "Boris", "iou", {"wood": 2})
    assert w.agents["Boris"].inventory.get("wood") == 1
    assert engine.observe(w, "Clara")["board"]["debts"] == []  # private: only the two sides see it
    board = engine.observe(w, "Anna")["board"]["debts"]
    assert board[0]["pledge"] == {"wood": 2} and board[0]["note"] == "bread on credit"
    coins = w.agents["Anna"].coins
    ev = act(w, "Boris", "repay", debt_id=d.id, coins=4)
    assert not errors(ev), errors(ev)
    assert d.status == "repaid" and not d.pledge
    assert w.agents["Boris"].inventory.get("wood") == 3 and w.agents["Anna"].coins == coins + 4


def test_unpaid_pledge_goes_to_the_lender(w):
    ops.mint(w, w.agents["Boris"].inventory, "fish", 2)
    act(w, "Boris", "promise", to="Anna", coins=9, due_day=2, pledge={"fish": 2})
    ev = until_day(w, 3)
    d = only_debt(w)
    assert d.status == "forfeited" and not d.pledge
    assert w.agents["Anna"].inventory.get("fish", 0) >= 2
    assert "pledge_forfeited" in [e.kind for e in ev] and "default" not in [e.kind for e in ev]
    assert errors(act(w, "Boris", "repay", debt_id=d.id, coins=1))


def test_bad_promises_are_refused(w):
    assert errors(act(w, "Boris", "promise", to="Boris", coins=3, due_day=3))
    assert errors(act(w, "Boris", "promise", to="Anna", coins=3, due_day=1))
    assert errors(act(w, "Boris", "promise", to="Anna", coins=3, due_day=3, pledge={"gold": 5}))
    assert errors(act(w, "Boris", "promise", to="Anna", coins=3, due_day=3, pledge={"coins": 1}))
    assert not w.debts


def test_forgive_and_transfer(w):
    act(w, "Boris", "promise", to="Anna", coins=5, due_day=3)
    d = only_debt(w)
    assert errors(act(w, "Clara", "forgive_debt", debt_id=d.id))  # not hers
    assert not errors(act(w, "Anna", "transfer_debt", debt_id=d.id, to="Clara"))
    assert d.lender == "Clara"
    assert errors(act(w, "Anna", "forgive_debt", debt_id=d.id))  # not hers any more
    assert not errors(act(w, "Clara", "forgive_debt", debt_id=d.id))
    assert d.status == "forgiven"
    assert engine.observe(w, "Boris")["board"]["debts"] == []


def test_late_fee_grows_a_defaulted_debt():
    w = engine.new_world({"seed": 1, "debts": {"late_fee_pct": 10, **MANUAL}})
    act(w, "Boris", "promise", to="Anna", coins=10, due_day=2)
    until_day(w, 3)
    d = only_debt(w)
    assert d.status == "defaulted" and d.coins_owed == 10
    until_day(w, 4)
    assert d.coins_owed == 11
    act(w, "Boris", "repay", debt_id=d.id, coins=1)  # partial repay keeps it defaulted
    assert d.status == "defaulted"


def test_mayor_collects_from_pocket_then_chest(w):
    w.governance.mayor = "Clara"
    act(w, "Boris", "promise", to="Anna", coins=30, due_day=2)
    d = only_debt(w)
    assert errors(act(w, "Anna", "demand_debt", debt_id=d.id))  # not overdue yet
    until_day(w, 3)
    assert d.status == "defaulted"
    assert errors(act(w, "Boris", "demand_debt", debt_id=d.id))  # only the lender
    assert not errors(act(w, "Anna", "demand_debt", debt_id=d.id))
    assert errors(act(w, "Anna", "demand_debt", debt_id=d.id))  # once
    claims = engine.observe(w, "Clara")["debt_claims"]
    assert claims[0]["debt_id"] == d.id and "debt_claims" not in engine.observe(w, "Anna")
    assert errors(act(w, "Anna", "rule_debt", debt_id=d.id, decision="collect"))  # not the mayor
    boris, anna, chest = w.agents["Boris"], w.agents["Anna"], w.chests["chest_Boris"]
    ops.move_coins(boris, chest, min(boris.coins, 5))
    pocket, stash, before, treasury = boris.coins, chest.coins, anna.coins, w.governance.coins
    ev = act(w, "Clara", "rule_debt", debt_id=d.id, decision="collect")
    assert not errors(ev), errors(ev)
    take = min(30, pocket + stash)
    fee = take * 10 // 100
    assert boris.coins == max(0, pocket - 30) and chest.coins == stash - (take - min(pocket, 30))
    assert anna.coins == before + take - fee and w.governance.coins == treasury + fee
    assert d.coins_owed == 30 - take and d.claim is None
    assert "debt_collected" in [e.kind for e in ev]
    if d.coins_owed:  # ruled today: ask again tomorrow
        assert errors(act(w, "Anna", "demand_debt", debt_id=d.id))


def test_mayor_can_reject_and_no_mayor_no_collection(w):
    act(w, "Boris", "promise", to="Anna", coins=5, due_day=2)
    d = only_debt(w)
    until_day(w, 3)
    assert errors(act(w, "Anna", "demand_debt", debt_id=d.id))  # no mayor yet
    w.governance.mayor = "Boris"  # the debtor is the mayor
    act(w, "Anna", "demand_debt", debt_id=d.id)
    ev = act(w, "Boris", "rule_debt", debt_id=d.id, decision="reject")
    assert "debt_rejected" in [e.kind for e in ev] and d.coins_owed == 5 and d.claim is None


def test_collection_off_hides_it_from_prompt_and_actions():
    w = engine.new_world({"seed": 1, "debts": {"collection": False, **MANUAL}})
    assert "Nobody forces repayment" in world_facts(w.config)
    assert "demand_debt" in world_facts(engine.new_world({"seed": 1}).config)
    w.governance.mayor = "Clara"
    act(w, "Boris", "promise", to="Anna", coins=5, due_day=2)
    until_day(w, 3)
    assert "demand_debt" not in engine.observe(w, "Anna")["available_actions"]
    assert errors(act(w, "Anna", "demand_debt", debt_id=only_debt(w).id))


def test_lawless_preset_has_no_collection():
    from aivillage import runconfig
    cfg = engine.new_world(runconfig.parse({"preset": "lawless"}).world_override()).config
    assert {"demand_debt", "rule_debt"} <= set(cfg["disabled_actions"])


def test_random_bots_keep_invariants_with_debts():
    w = engine.new_world({"seed": 7})
    kinds = []
    run(w, bots_decider(w, ["random"], 7), days=6, on_tick=lambda world, ev: kinds.extend(e.kind for e in ev))
    assert "promise" in kinds


# ---------- automatic collection (debts.auto_collect) ----------

def auto_world(**debts):
    w = engine.new_world({"seed": 1, "debts": {"auto_collect": True, "seize_pct": 50, **debts}})
    for a in w.agents.values():  # empty pockets and chests: each test sets what it needs
        ops.burn_coins(w, a, a.coins)
        chest = w.chests[f"chest_{a.name}"]
        ops.burn_coins(w, chest, chest.coins)
        for store in (a.inventory, chest.items):
            for item, q in list(store.items()):
                ops.burn(w, store, item, q)
    return w


def kinds_of(events):
    return [e.kind for e in events]


def test_night_takes_half_the_coins_pocket_then_chest():
    w = auto_world()
    act(w, "Boris", "promise", to="Anna", coins=30, due_day=2)
    ops.mint_coins(w, w.agents["Boris"], 10)
    ops.mint_coins(w, w.chests["chest_Boris"], 10)
    ev = until_day(w, 3)
    d = only_debt(w)
    assert "debt_seized" in kinds_of(ev)
    assert d.status == "defaulted" and d.coins_owed == 20  # half of 20 coins
    assert w.agents["Boris"].coins + w.chests["chest_Boris"].coins == 10
    assert w.agents["Anna"].coins == 10
    seized = next(e for e in ev if e.kind == "debt_seized")
    assert set(ops.recipients(w, seized)) == {"Anna", "Boris"}  # not shouted to the village


def test_goods_after_coins_but_never_food():
    w = auto_world()
    act(w, "Boris", "promise", to="Anna", coins=100, due_day=2)
    boris = w.agents["Boris"]
    ops.mint(w, boris.inventory, "tool", 2)
    ops.mint(w, boris.inventory, "bread", 5)
    ops.mint(w, w.chests["chest_Boris"].items, "fish", 4)
    until_day(w, 3)
    d = only_debt(w)
    price = debts.unit_price(w.config, "tool")
    assert boris.inventory.get("tool", 0) == 1 and w.agents["Anna"].inventory.get("tool", 0) == 1
    assert d.coins_owed == 100 - price  # one of two tools = half their value
    assert boris.inventory["bread"] == 5 and w.chests["chest_Boris"].items["fish"] == 4


def test_never_takes_more_than_owed():
    w = auto_world()
    act(w, "Boris", "promise", to="Anna", coins=3, due_day=2)
    ops.mint_coins(w, w.agents["Boris"], 50)
    ev = until_day(w, 3)
    d = only_debt(w)
    assert d.status == "repaid" and w.agents["Anna"].coins == 3 and w.agents["Boris"].coins == 47
    assert "the debt is closed" in next(e.text for e in ev if e.kind == "debt_seized")


def test_half_of_new_income_goes_to_the_lender():
    w = auto_world()
    act(w, "Boris", "promise", to="Anna", coins=20, due_day=2)
    until_day(w, 3)
    assert only_debt(w).status == "defaulted"
    ops.mint_coins(w, w.agents["Clara"], 10)
    w.agents["Clara"].location = w.agents["Boris"].location
    ev = act(w, "Clara", "give", to="Boris", coins=10)
    assert not errors(ev), errors(ev)
    assert "debt_garnished" in kinds_of(ev)
    assert w.agents["Boris"].coins == 5 and w.agents["Anna"].coins == 5 and only_debt(w).coins_owed == 15
    # moving coins into his own chest is not income
    w.agents["Boris"].location = w.agents["Boris"].home
    ev = act(w, "Boris", "store", coins=5)
    assert not errors(ev), errors(ev)
    assert "debt_garnished" not in kinds_of(ev) and w.chests["chest_Boris"].coins == 5


def test_oldest_debt_is_served_first_and_pledged_debts_are_left_alone():
    w = auto_world()
    act(w, "Boris", "promise", to="Clara", coins=10, due_day=3)
    act(w, "Boris", "promise", to="Anna", coins=10, due_day=2)
    until_day(w, 4)
    ops.mint_coins(w, w.agents["Boris"], 40)
    until_day(w, 5)
    to_anna = next(d for d in w.debts.values() if d.lender == "Anna")
    to_clara = next(d for d in w.debts.values() if d.lender == "Clara")
    assert to_anna.status == "repaid" and to_clara.status == "repaid"
    assert w.agents["Anna"].coins == 10 and w.agents["Clara"].coins == 10


def test_auto_collect_off_and_lawless_take_nothing():
    w = auto_world(auto_collect=False)
    act(w, "Boris", "promise", to="Anna", coins=10, due_day=2)
    ops.mint_coins(w, w.agents["Boris"], 10)
    assert "debt_seized" not in kinds_of(until_day(w, 3))
    assert w.agents["Boris"].coins == 10
    assert "collected by the village" not in world_facts(w.config)
    from aivillage import runconfig
    cfg = engine.new_world(runconfig.parse({"preset": "lawless"}).world_override()).config
    assert not debts.auto_on(cfg) and "Nobody forces repayment" in world_facts(cfg)


def test_prompt_states_the_rule():
    w = engine.new_world({"seed": 1})
    facts = world_facts(w.config)
    assert "collected by the village" in facts and "food is never taken" in facts


def test_random_bots_keep_invariants_and_replay_with_auto_collection(tmp_path):
    from aivillage.run import replay
    w = engine.new_world({"seed": 3, "debts": {"auto_collect": True, "late_fee_pct": 10}})
    kinds = []
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["random"], 3), days=8, log_path=log,
        on_tick=lambda world, ev: (check(world), kinds.extend(e.kind for e in ev)))
    assert "debt_seized" in kinds or "debt_garnished" in kinds
    assert replay(log).hash() == w.hash()
