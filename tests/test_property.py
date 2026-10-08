"""Private property and conflict: no common field, lots for sale, the shared gold mine, fights, arson."""

import pytest

from aivillage import engine, governance, ops
from aivillage.invariants import check
from aivillage.run import bots_decider, replay, run


@pytest.fixture
def w():
    return engine.new_world({"seed": 1, "crises": {"enabled": False}})


def act(w, name, action, args=None):
    w.agents[name].last_error = None
    events = engine.step(w, {name: {"thought": "", "action": {"name": action, "args": args or {}}}})
    check(w)
    return w.agents[name].last_error, events


def give(w, name, **items):
    for k, v in items.items():
        if k == "coins":
            ops.mint_coins(w, w.agents[name], v)
        else:
            ops.mint(w, w.agents[name].inventory, k, v)


def night(w):
    engine.step(w, {})
    while w.hour != w.config["day_start_hour"]:
        engine.step(w, {})
    check(w)


def test_no_common_field_and_start_beds_are_sown(w):
    assert "field" not in w.locations
    assert not any("grain" in loc.resources for loc in w.locations.values())
    beds = {n: [b for b in p.buildings if b["kind"] == "garden_bed"] for n, p in w.plots.items() if p.kind == "home"}
    assert len(beds["home_Anna"]) == 3 and all(not v for k, v in beds.items() if k != "home_Anna")
    assert all(b["crop"] == "grain" and b["ripe_day"] == 2 for b in beds["home_Anna"])
    night(w)
    assert w.plots["home_Anna"].buildings[0]["items"] == {"grain": 9}  # farmer bonus
    err, _ = act(w, "Anna", "collect")
    assert err is None and w.agents["Anna"].inventory["grain"] == 27
    give(w, "Boris", wood=1, grain=1, tool=1)  # anyone can build a bed and sow it; a tool works as a hoe
    assert act(w, "Boris", "build", {"kind": "garden_bed"})[0] is None
    assert act(w, "Boris", "plant")[0] is None
    assert w.plots["home_Boris"].buildings[0]["amount"] == 8


def test_buy_land_build_and_steal_there(w):
    a, b = w.agents["Anna"], w.agents["Boris"]
    lot = w.plots["lot_1"]
    assert lot.owner == "" and lot.kind == "lot" and lot.price == 54
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert {x["id"] for x in obs["land_for_sale"]} == {"lot_1", "lot_2", "lot_3"}
    err, _ = act(w, "Anna", "buy_land", {"lot": "lot_1"})
    assert "go to lot_1" in err
    a.location = "lot_1"
    err, _ = act(w, "Anna", "buy_land")
    assert "costs 54" in err
    give(w, "Anna", coins=50, wood=5)
    treasury = w.governance.coins
    err, events = act(w, "Anna", "buy_land")
    assert err is None and lot.owner == "Anna" and w.governance.coins == treasury + 54
    assert any(e.kind == "land_bought" and e.visibility == "public" for e in events)
    assert "upgrade_house" not in engine.observe(w, "Anna", consume_inbox=False)["available_actions"]
    err, _ = act(w, "Anna", "upgrade_house")
    assert "lot" in err
    err, _ = act(w, "Anna", "build", {"kind": "garden_bed"})
    assert err is None and [x["kind"] for x in lot.buildings] == ["garden_bed"]
    give(w, "Anna", grain=1)
    err, _ = act(w, "Anna", "plant")
    assert err is None
    a.location = "square"
    night(w)
    night(w)
    assert lot.buildings[0]["items"] == {"grain": 9}
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert obs["your_lots"][0]["id"] == "lot_1" and obs["land_owners"] == {"lot_1": "Anna"}
    b.location = "lot_1"  # nobody guards a lot
    err, _ = act(w, "Boris", "steal_from_plot", {"item": "grain", "qty": 4})
    assert err is None and b.inventory["grain"] == 4


def test_sell_land_to_a_neighbour(w):
    w.plots["lot_2"].owner = "Anna"
    err, events = act(w, "Anna", "sell_land", {"lot": "lot_2", "to": "Boris", "price": 30})
    assert err is None and any(e.kind == "land_offer" and e.to == ["Boris"] for e in events)
    assert engine.observe(w, "Boris", consume_inbox=False)["land_offers"][0]["price"] == 30
    err, _ = act(w, "Clara", "buy_land", {"lot": "lot_2"})
    assert "not offered to you" in err
    give(w, "Boris", coins=10)
    coins_a, coins_b = w.agents["Anna"].coins, w.agents["Boris"].coins
    err, _ = act(w, "Boris", "buy_land", {"lot": "lot_2"})  # from anywhere
    assert err is None and w.plots["lot_2"].owner == "Boris"
    assert (w.agents["Anna"].coins, w.agents["Boris"].coins) == (coins_a + 30, coins_b - 30)
    err, _ = act(w, "Anna", "sell_land", {"lot": "lot_2", "to": "Clara", "price": 1})
    assert "not yours" in err


def test_land_offer_expires(w):
    w.plots["lot_2"].owner = "Anna"
    act(w, "Anna", "sell_land", {"lot": "lot_2", "to": "Boris", "price": 0})
    for _ in range(w.config["land"]["sale_ttl_hours"]):  # hourly ticks in engine tests
        engine.step(w, {})
    assert w.plots["lot_2"].sale is None
    err, _ = act(w, "Boris", "buy_land", {"lot": "lot_2"})
    assert "not offered" in err


def test_gold_is_dug_slowly_and_runs_out(w):
    d = w.agents["Dmitri"]
    d.location = "mine"
    give(w, "Dmitri", tool=1)
    act(w, "Dmitri", "work", {"resource": "gold", "hours": 1})
    assert d.inventory["gold"] == 2  # miner x3, tool x2, but at most 2 an hour
    mine = w.locations["mine"]
    while mine.resources["gold"]:
        engine.step(w, {"Dmitri": {"action": {"name": "work", "args": {"resource": "gold"}}}})
    assert d.inventory["gold"] == 24
    night(w)
    assert mine.resources["gold"] == 0  # never comes back


def test_fight_with_weapons_is_deterministic_and_has_consequences():
    def fight():
        w = engine.new_world({"seed": 3})
        for n in ("Anna", "Boris", "Clara"):
            w.agents[n].location = "square"
        give(w, "Boris", spear=1)
        give(w, "Anna", gold=5)
        err, events = act(w, "Boris", "attack", {"target": "Anna", "take": "gold", "qty": 9})
        return w, err, events
    w, err, events = fight()
    assert err is None
    f = next(e for e in events if e.kind == "fight")
    assert f.data["weapons"] == {"Boris": "spear", "Anna": None} and f.data["witnesses"] == ["Clara"]
    lost = 100 - w.agents["Anna"].health
    assert lost == f.data["damage"]["Boris"] and 100 - w.agents["Boris"].health == f.data["damage"]["Anna"]
    assert all(r["hit"] == (r["roll"] == 20 or (r["roll"] != 1 and r["roll"] + r["bonus"] >= 10)) for r in f.data["rounds"])
    if f.data["winner"] == "Boris":
        assert f.data["loot"] == {"gold": 3} and w.agents["Boris"].inventory["gold"] == 3
    else:
        assert f.data["loot"] == {} and w.agents["Anna"].inventory["gold"] == 5
    assert w.kin.feelings["Anna"]["Boris"] == -30 and w.kin.feelings["Clara"]["Boris"] == -10
    assert w.agents["Clara"].reputation["Boris"]["score"] == -3
    assert any("attacked" in n for n in w.agents["Clara"].inbox)
    assert {c["crime"] for c in w.governance.crimes} == {"assault"}
    w2, _, events2 = fight()
    assert w2.hash() == w.hash()  # same seed, same dice


def test_fight_rules(w):
    err, _ = act(w, "Anna", "attack", {"target": "Boris"})
    assert "here" in err or "not" in err
    w.agents["Boris"].location = w.agents["Anna"].location = "square"
    w.agents["Anna"].health = 10
    err, _ = act(w, "Anna", "attack", {"target": "Boris"})
    assert "too weak" in err
    w.agents["Anna"].health = 100
    w.agents["Boris"].asleep = True
    err, events = act(w, "Anna", "attack", {"target": "Boris"})
    f = next(e for e in events if e.kind == "fight")
    assert err is None and f.data["surprised"] and f.data["rounds"][0]["by"] == "Anna"
    assert not any(r["by"] == "Boris" and r["round"] == 1 for r in f.data["rounds"])


def test_fight_can_send_to_hospital(w):
    w.agents["Boris"].location = w.agents["Anna"].location = "square"
    w.agents["Boris"].health = 20
    w.config["combat"]["give_up_health"] = 0
    give(w, "Anna", spear=1)
    w.agents["Boris"].health = 1
    w.config["combat"]["min_health"] = 0
    act(w, "Anna", "attack", {"target": "Boris"})
    for _ in range(30):
        if w.agents["Boris"].status == "hospital":
            break
        w.agents["Boris"].health = 1
        act(w, "Anna", "attack", {"target": "Boris"})
    assert w.agents["Boris"].status == "hospital"


def test_arson_starts_a_fire_and_the_family_sees_it(w):
    a = w.agents["Anna"]
    a.location = "home_Boris"  # Boris is at home and awake
    err, _ = act(w, "Anna", "set_fire")
    assert "wood" in err
    give(w, "Anna", wood=1)
    err, events = act(w, "Anna", "set_fire")
    assert err is None and "home_Boris" in w.fires and "wood" not in a.inventory
    fire = next(e for e in events if e.kind == "fire")
    assert fire.visibility == "public" and "Anna" not in fire.text and fire.data["arsonist"] == "Anna"
    assert any(e.kind == "arson_seen" and e.to == ["Boris"] for e in events)
    assert w.kin.feelings["Boris"]["Anna"] == -30
    assert any(c.get("crime") == "arson" for c in w.governance.crimes)
    err, _ = act(w, "Anna", "set_fire")
    assert err  # already burning, or no wood
    a.location = "home_Anna"
    give(w, "Anna", wood=1)
    err, _ = act(w, "Anna", "set_fire")
    assert "someone else's house" in err


def test_report_assault(w):
    w.config["governance"]["start"]["theft_fine"] = 5
    w.governance.laws["theft_fine"] = 5
    for n in ("Anna", "Boris"):
        w.agents[n].location = "square"
    act(w, "Boris", "attack", {"target": "Anna"})
    err, events = act(w, "Anna", "report_theft", {"person": "Boris"})
    assert err is None
    assert "attacked Anna" in next(e for e in events if e.kind == "theft_report").text


def test_random_fires_setting():
    w = engine.new_world({"seed": 1, "random_fires": {"per_day": 1.0}})
    night(w)
    assert len(w.fires) == 1
    w = engine.new_world({"seed": 1})
    for _ in range(3):
        night(w)
    assert not w.fires


def test_generated_map_has_lots_and_replays(tmp_path):
    w = engine.new_world({"seed": 5, "map": {"procedural": True}})
    lots = [p for p in w.plots.values() if p.kind == "lot"]
    assert len(lots) == 3 and all(p.owner == "" and p.price > 0 for p in lots)
    places = w.config["map"]["layout"]["places"]
    assert all(places[p.home]["kind"] == "lot" and len(places[p.home]["plot"]) == 4 for p in lots)
    assert "field" not in w.locations and "gold" not in w.config["locations"].get("quarry", {}).get("resources", {})
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["thief", "homestead", "worker", "random", "trader"], 5), days=2, log_path=log)
    replay(log)


def test_bots_live_a_week_with_violence_and_land():
    w = engine.new_world({"seed": 2, "start_coins": 80})
    stats = run(w, bots_decider(w, ["thief", "homestead", "worker", "thief", "trader"], 2), days=7)
    check(w)
    assert stats.get("hospital", 0) <= 2
