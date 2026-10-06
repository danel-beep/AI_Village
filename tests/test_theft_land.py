"""Conflict from world rules: stores in view, the dark, the owner at home, the treasury (theft.py); land that goes
to whoever comes first, with no court, and gifts of land (land.py); hungrier winter nights (seasons.py)."""

import pytest

from aivillage import engine, governance, llm, ops, theft
from aivillage.invariants import check
from aivillage.run import bots_decider, replay, run

ON = {"theft": {"enabled": True}}


def world(**over):
    return engine.new_world({"seed": 1, "crises": {"enabled": False}, **over})


def act(w, name, action, args=None):
    w.agents[name].last_error = None
    events = engine.step(w, {name: {"thought": "", "action": {"name": action, "args": args or {}}}})
    check(w)
    return w.agents[name].last_error, events


def kinds(events, to):
    return [e.kind for e in events if to in (e.to or [])]


def test_off_by_default_keeps_the_old_rules():
    w = world()
    assert not theft.enabled(w.config) and w.config["land"]["claim"] == "buy"
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert "dark" not in obs["time"]
    w.agents["Boris"].location = "home_Anna"
    obs = engine.observe(w, "Boris", consume_inbox=False)
    assert "coins" not in next(c for c in obs["here"]["chests"] if c["owner"] == "Anna")
    assert theft.fact(w.config) == "" and "claim_land" not in llm.world_facts(w.config)


def test_dark_hours_and_winter():
    w = world(**ON)
    w.hour = 12
    assert not theft.is_dark(w) and theft.notice(w, 0.5) == 0.5
    w.hour = 21
    assert theft.is_dark(w) and theft.notice(w, 0.5) == pytest.approx(0.2)
    w.hour = 6
    assert theft.is_dark(w)
    w.config["seasons"].update(start="winter", offset_days=0)
    w.hour = 18
    assert theft.is_dark(w)  # winter: dark from 18:00
    assert engine.observe(w, "Anna", consume_inbox=False)["time"]["dark"] is True


def test_stores_in_view():
    w = world(**ON)
    a, b = w.agents["Anna"], w.agents["Boris"]
    chest = w.chests["chest_Anna"]
    ops.mint(w, chest.items, "bread", 2)
    ops.mint(w, chest.items, "wood", 5)
    ops.mint_coins(w, a, 7)
    b.location = a.location = a.home
    here = engine.observe(w, "Boris", consume_inbox=False)["here"]
    seen = next(c for c in here["chests"] if c["owner"] == "Anna")
    assert seen["food"] == {"bread": 2} and seen["coins"] == chest.coins and "items" not in seen
    person = next(p for p in here["people"] if p["name"] == "Anna")
    assert person["coins"] == a.coins and "wood" not in person["food"]


def test_owner_at_home_sees_the_thief_or_not():
    for chance, seen in ((1.0, True), (0.0, False)):
        w = world(theft={"enabled": True, "owner_notice_chance": chance})
        a, b = w.agents["Anna"], w.agents["Boris"]
        ops.mint(w, w.chests["chest_Anna"].items, "bread", 3)
        a.location = b.location = a.home
        err, events = act(w, "Boris", "steal", {"target": "chest", "item": "bread", "qty": 1})
        assert err is None and ops.count(b.inventory, "bread") >= 1
        assert ("steal_attempt" in kinds(events, "Anna")) is seen
        assert "robbed" in kinds(events, "Anna")
        if seen:
            assert any(c["thief"] == "Boris" for c in w.governance.crimes)


def test_awake_victim_may_miss_the_thief():
    w = world(theft={"enabled": True, "victim_notice_chance": 0.0}, steal_awake_target_success=1.0)
    a, b = w.agents["Anna"], w.agents["Boris"]
    ops.mint_coins(w, a, 5)
    b.location = a.location
    err, events = act(w, "Boris", "steal", {"target": "Anna", "item": "coins", "qty": 2})
    assert err is None and "steal_attempt" not in kinds(events, "Anna") and "robbed" in kinds(events, "Anna")


def test_steal_from_the_village_treasury_found_only_by_audit():
    w = world(**ON)
    b = w.agents["Boris"]
    ops.mint_coins(w, w.governance, 30)
    err, _ = act(w, "Boris", "steal", {"target": "treasury", "item": "coins", "qty": 3})
    assert "no treasury here" in err
    b.location = "square"
    err, _ = act(w, "Boris", "steal", {"target": "treasury", "item": "bread", "qty": 3})
    assert "only coins" in err
    before = b.coins
    err, events = act(w, "Boris", "steal", {"target": "treasury", "item": "coins", "qty": 3})
    assert err is None and b.coins == before + 3 and w.governance.coins == 27
    assert governance.books(w) == 30 and not any(e.kind == "robbed" for e in events)
    assert engine.observe(w, "Anna", consume_inbox=False)["government"]["treasury"] == 30
    err, events = act(w, "Anna", "move", {"to": "square"})
    while w.agents["Anna"].location != "square":
        engine.step(w, {})
    err, events = act(w, "Anna", "audit_treasury")
    found = [e for e in events if e.kind == "embezzlement_found"]
    assert err is None and "nobody knows who took" in found[0].text and governance.books(w) == 27
    assert not any(c["crime"] == "embezzlement" for c in w.governance.crimes)


def test_first_come_land_jump_and_give():
    w = world(land={"claim": "first"})
    a, b, c = w.agents["Anna"], w.agents["Boris"], w.agents["Clara"]
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert "land_for_sale" not in obs and {x["id"] for x in obs["land_free"]} == {"lot_1", "lot_2", "lot_3"}
    assert "price" not in obs["land_free"][0]
    a.location = "lot_1"
    err, _ = act(w, "Anna", "buy_land")
    assert "claim_land" in err
    coins = a.coins
    err, events = act(w, "Anna", "claim_land")
    assert err is None and w.plots["lot_1"].owner == "Anna" and a.coins == coins
    assert any(e.kind == "land_claimed" and e.visibility == "public" for e in events)
    b.location = "lot_1"  # the owner is still there: the lot holds
    assert "claim_land" not in engine.observe(w, "Boris", consume_inbox=False)["available_actions"]
    a.location = "square"  # owner away, nothing built: Boris takes it
    err, events = act(w, "Boris", "claim_land")
    assert err is None and w.plots["lot_1"].owner == "Boris"
    assert "land_claimed" in kinds(events, "Anna")
    w.plots["lot_1"].buildings.append({"id": "b1", "kind": "garden_bed", "items": {}, "crop": None, "ripe_day": 0})
    c.location, b.location = "lot_1", "square"  # something built: it holds
    err, _ = act(w, "Clara", "claim_land")
    assert "something is built" in err
    err, events = act(w, "Boris", "give_land", {"lot": "lot_1", "to": "Clara"})
    assert err is None and w.plots["lot_1"].owner == "Clara" and "land_given" in kinds(events, "Clara")
    err, _ = act(w, "Boris", "give_land", {"lot": "lot_1", "to": "Anna"})
    assert "not yours" in err


def test_no_jump_when_off():
    w = world(land={"claim": "first", "claim_jump": False})
    w.plots["lot_1"].owner = "Anna"
    w.agents["Boris"].location = "lot_1"
    assert "claim_land" not in engine.observe(w, "Boris", consume_inbox=False)["available_actions"]


def test_winter_nights_are_hungrier():
    hungry = {}
    for extra in (0, 10):
        w = world(seasons={"start": "winter", "night_hunger": {"winter": extra}})
        before = w.agents["Anna"].satiety
        engine.step(w, {})
        while w.hour != w.config["day_start_hour"]:
            engine.step(w, {})
        hungry[extra] = before - w.agents["Anna"].satiety
    assert hungry[10] == hungry[0] + 10
    assert "a winter night costs 10 more satiety" in llm.world_facts(world(seasons={"night_hunger": {"winter": 10}}).config)


@pytest.mark.parametrize("mode", ["survival", "lawless"])
def test_bots_with_the_new_rules_replay(mode, tmp_path):
    from aivillage import runconfig
    w = engine.new_world(runconfig.RunConfig(mode=mode, seed=3).world_override())
    assert theft.enabled(w.config)
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["thief", "builder", "homestead", "worker"], 3), days=3, log_path=log)
    replay(log)


def test_tax_board_shows_who_paid():
    w = world(tax_amount=10, tax_every_days=2, taxes={"enabled": True},
              laws={"enforcement": "voluntary", "bill_days": 2})
    assert taxes_board(w) == []
    for n in ("Anna", "Boris"):
        ops.mint_coins(w, w.agents[n], 20)
    while w.day < 3:
        engine.step(w, {})
    bill = next(d for d in w.debts.values() if d.kind == "tax" and d.borrower == "Boris")
    err, _ = act(w, "Boris", "pay_bill", {"debt_id": bill.id})
    assert err is None
    row = taxes_board(w)[0]
    assert row["tax_day"] == 3 and row["to"] == "village treasury" and row["paid"] == ["Boris"]
    assert "Anna" in row["not_paid_yet"] and "Boris" not in row["not_paid_yet"]
    while w.day < 5 or w.hour < 8:
        engine.step(w, {})
    rows = taxes_board(w)
    assert [r["tax_day"] for r in rows] == [5, 3] and "Anna" in rows[1]["overdue"]
    assert '"tax_board" lists' in llm.world_facts(w.config)
    w.config["laws"]["tax_board"] = False
    assert taxes_board(w) == []


def taxes_board(w):
    return engine.observe(w, "Clara", consume_inbox=False).get("tax_board", [])
