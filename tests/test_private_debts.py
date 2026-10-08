"""Private debts and debts in kind (debts.py, plan item 5): only the two sides see a debt, and an offer can carry
an "I owe you later" part (`i_owe`) that is paid off by giving the items."""

import pytest

from aivillage import debts, engine, modes, ops
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.run import bots_decider, replay, run
from aivillage.state import Marriage, World


def make(**debt_cfg):
    w = engine.new_world({"seed": 1, "debts": {"in_kind": True, **debt_cfg}})
    for a in w.agents.values():
        a.location = "square"
    return w


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def board(w, name):
    return engine.observe(w, name, consume_inbox=False)["board"]["debts"]


def heard(w, name, kind):
    return any(kind in line for line in w.agents[name].inbox)


def borrow_fish(w, owe=None, due=3):
    """Elena, hungry, gets 3 fish from Anna now against 4 fish by `due`."""
    ops.mint(w, w.agents["Anna"].inventory, "fish", 3)
    ev = act(w, "Elena", "offer", to="Anna", want={"fish": 3}, i_owe=owe or {"fish": 4}, due_day=due)
    assert not errors(ev), errors(ev)
    ev = act(w, "Anna", "accept", offer_id=list(w.offers)[-1])
    assert not errors(ev), errors(ev)
    return list(w.debts.values())[-1]


def test_a_debt_is_seen_only_by_its_two_sides_and_their_spouses():
    w = make()
    w.kin.marriages["m1"] = Marriage("m1", ["Boris", "Clara"], w.agents["Boris"].home, 1)
    act(w, "Anna", "lend", to="Boris", coins=2, repay_coins=3, due_day=3)
    d = next(iter(w.debts.values()))
    assert [r["id"] for r in board(w, "Anna")] == [d.id] == [r["id"] for r in board(w, "Boris")]
    assert [r["id"] for r in board(w, "Clara")] == [d.id]  # Boris's wife
    assert board(w, "Dmitri") == []
    act(w, "Boris", "repay", debt_id=d.id, coins=1)
    assert "repaid 1 coins" in "".join(w.agents["Anna"].inbox)
    assert "repaid" not in "".join(w.agents["Dmitri"].inbox)
    act(w, "Anna", "promise", to="Dmitri", coins=5, due_day=4)
    assert not any("IOU" in line for line in w.agents["Elena"].inbox)


def test_a_default_is_told_to_the_two_sides_only():
    w = make(auto_collect=False)
    act(w, "Anna", "promise", to="Boris", coins=5, due_day=2)
    while w.day < 3:
        engine.step(w, {})
        check(w)
    assert next(iter(w.debts.values())).status == "defaulted"
    assert any("failed to repay" in line for line in w.agents["Boris"].inbox)
    assert not any("failed to repay" in line for line in w.agents["Clara"].inbox)


def test_offer_with_i_owe_writes_a_private_debt_in_kind():
    w = make()
    d = borrow_fish(w)
    assert (d.lender, d.borrower, d.kind, d.items_owed, d.coins_owed, d.due_day) == ("Anna", "Elena", "iou",
                                                                                      {"fish": 4}, 0, 3)
    assert w.agents["Elena"].inventory["fish"] == 3 and not w.agents["Anna"].inventory.get("fish")
    assert board(w, "Elena")[0]["items_owed"] == {"fish": 4}
    assert board(w, "Clara") == []
    assert any("now owes Anna 4 fish" in line for line in w.agents["Anna"].inbox)
    assert not any("now owes" in line for line in w.agents["Clara"].inbox)


def test_offer_with_i_owe_is_refused_when_off_or_malformed():
    w = make()
    w.config["debts"]["in_kind"] = False
    assert errors(act(w, "Elena", "offer", to="Anna", want={"fish": 1}, i_owe={"fish": 2}, due_day=3))
    w.config["debts"]["in_kind"] = True
    assert errors(act(w, "Elena", "offer", to="Anna", want={"fish": 1}, i_owe={"fish": 2}))  # no due day
    assert errors(act(w, "Elena", "offer", to="Anna", want={"fish": 1}, i_owe={"fish": 2}, due_day=1))
    assert errors(act(w, "Elena", "offer", to="Anna", i_owe={"fish": 2}, due_day=3))  # nothing wanted
    assert errors(act(w, "Elena", "offer", to="Anna", want={"fish": 1}, due_day=3))  # due day alone
    assert errors(act(w, "Elena", "offer", to="Anna", want={"fish": 1}, i_owe={"unicorn": 1}, due_day=3))
    assert not w.offers and not w.debts


def test_giving_the_owed_items_pays_it_off_part_by_part():
    w = make()
    d = borrow_fish(w, owe={"fish": 3, "wood": 2, "coins": 1})
    ops.mint(w, w.agents["Elena"].inventory, "wood", 5)
    act(w, "Elena", "give", to="Anna", items={"wood": 1})
    assert d.items_owed == {"fish": 3, "wood": 1} and d.status == "open"
    act(w, "Elena", "give", to="Anna", items={"wood": 3, "fish": 3})  # one wood more than owed is a gift
    assert d.items_owed == {} and d.coins_owed == 1 and d.status == "open"
    assert w.agents["Anna"].inventory["wood"] == 4
    assert errors(act(w, "Elena", "repay", debt_id=d.id, coins=5)) == []  # the coin part with repay
    assert d.status == "repaid"
    assert any("paid Anna" in line for line in w.agents["Anna"].inbox)


def test_repay_points_to_give_for_a_debt_owed_in_items():
    w = make()
    d = borrow_fish(w)
    assert "give them to Anna" in errors(act(w, "Elena", "repay", debt_id=d.id, coins=1))[0]


def test_forgiving_a_debt_in_kind():
    w = make()
    d = borrow_fish(w)
    assert not errors(act(w, "Anna", "forgive_debt", debt_id=d.id))
    assert d.status == "forgiven" and board(w, "Elena") == []


def test_overdue_debt_in_kind_takes_owed_goods_never_food():
    w = make(auto_collect=True, seize_pct=50)
    d = borrow_fish(w, owe={"fish": 4, "wood": 4})
    elena = w.agents["Elena"]
    ops.mint(w, elena.inventory, "wood", 4)
    while w.day < 4:
        engine.step(w, {})
        check(w)
    assert d.status in ("defaulted", "repaid")
    assert elena.inventory.get("fish", 0) + elena.satiety > 0  # food stays hers (eaten or kept)
    assert not d.items_owed  # wood taken in kind, fish turned into coins
    took = [e for e in w.agents["Anna"].inbox if "wood from Elena" in e]
    assert took and "4 fish" in took[0] and "still owed now count as" in took[0]
    assert "fish" not in took[0].split(" from Elena")[0]  # wood taken, the fish stays with her


def test_food_owed_and_food_held_is_never_seized():
    w = make(auto_collect=True, seize_pct=100)
    d = borrow_fish(w, owe={"fish": 4})
    elena = w.agents["Elena"]
    chest, dmitri = w.chests["chest_Elena"], w.agents["Dmitri"]
    for src in (elena, chest):  # nothing but food left to her
        ops.move_items(src.inventory if src is elena else src.items, dmitri.inventory,
                       dict(src.inventory if src is elena else src.items))
        ops.move_coins(src, dmitri, src.coins)
    ops.mint(w, elena.inventory, "fish", 6)
    fish = w.agents["Anna"].inventory.get("fish", 0)
    while w.day < 4:
        engine.step(w, {})
        check(w)
    assert w.agents["Anna"].inventory.get("fish", 0) == fish
    assert d.status == "defaulted" and not d.items_owed and d.coins_owed > 0


def test_saves_with_and_without_debts_in_kind_keep_their_hash():
    w = make()
    act(w, "Anna", "lend", to="Boris", coins=2, repay_coins=3, due_day=3)
    ops.mint(w, w.agents["Anna"].inventory, "fish", 1)
    act(w, "Anna", "offer", to="Boris", give={"fish": 1}, want={"coins": 1})
    assert World.from_dict(w.to_dict()).hash() == w.hash()
    borrow_fish(w)
    ops.mint(w, w.agents["Clara"].inventory, "bread", 1)
    act(w, "Clara", "offer", to="Boris", give={"bread": 1}, want={"coins": 1}, i_owe={"fish": 1}, due_day=5)
    back = World.from_dict(w.to_dict())
    assert back.hash() == w.hash() and back.debts.keys() == w.debts.keys()


def test_survival_turns_it_on_and_says_so_neutrally():
    cfg = engine.new_world({"seed": 1, **modes.world_override("normal")}).config
    assert debts.in_kind(cfg)
    assert "i_owe" in world_facts(cfg) and "private" in world_facts(cfg)
    assert not debts.in_kind(engine.new_world({"seed": 1}).config)


@pytest.mark.parametrize("seed", [0, 1])
def test_random_bots_with_debts_in_kind_keep_invariants_and_replay(tmp_path, seed):
    w = engine.new_world({"seed": seed, "debts": {"in_kind": True}})
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["random", "worker", "random", "trader"], seed), days=3, log_path=log)
    check(w)
    assert replay(log).hash() == w.hash()


def test_lean_winter_builder_bots_borrow_food_in_kind(tmp_path):
    from aivillage.scenario import run_scenario
    log = tmp_path / "lw.jsonl"
    rep = run_scenario("lean_winter", log=str(log), ai=[], days=1)
    assert rep["passed"]
    assert any('"kind": "iou"' in line for line in log.read_text().splitlines())
