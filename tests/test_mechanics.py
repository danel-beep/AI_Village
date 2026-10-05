"""One test per mechanic: the rule works, and failed actions change nothing."""

import pytest

from aivillage import engine, ops, run, tiles
from aivillage.invariants import check
from aivillage.registry import ACTIONS


@pytest.fixture
def w():
    return engine.new_world({"seed": 1})


def put(w, name, loc):
    w.agents[name].location = loc


def gift(w, name, **items):
    for k, v in items.items():
        if k == "coins":
            ops.mint_coins(w, w.agents[name], v)
        else:
            ops.mint(w, w.agents[name].inventory, k, v)


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def snapshot(w):
    return {n: (dict(a.inventory), a.coins, a.location) for n, a in w.agents.items()}, \
        {c.id: (dict(c.items), c.coins) for c in w.chests.values()}


def test_every_action_is_documented():
    text = ACTIONS.describe()
    for name, spec in ACTIONS.specs.items():
        assert spec.description and name in text
        assert spec.schema()["type"] == "object"


def test_failed_action_changes_nothing(w):
    before = snapshot(w)
    for action, args in [("eat", {"item": "bread"}), ("give", {"to": "Boris", "items": {"wood": 1}}),
                         ("craft", {"recipe": "tool"}), ("move", {"to": "atlantis"}), ("bogus", {}),
                         ("work", {"hours": "many"}), ("sell", {"item": "wood"}), ("steal", {"target": "x", "item": "y"})]:
        ev = act(w, "Anna", action, **args)
        assert errors(ev), action
    after = snapshot(w)
    assert before == after
    assert "failed" in " ".join(engine.observe(w, "Anna")["news"])


def test_work_profession_and_tool_multipliers(w):
    put(w, "Anna", "field")
    act(w, "Anna", "work")
    assert w.agents["Anna"].inventory["grain"] == 3
    put(w, "Boris", "field")
    act(w, "Boris", "work")
    assert w.agents["Boris"].inventory["grain"] == 1
    gift(w, "Anna", tool=1)
    act(w, "Anna", "work")
    assert w.agents["Anna"].inventory["grain"] == 3 + 6
    assert w.agents["Anna"].tool_wear == 1


def test_tool_wears_out(w):
    w.config["tool_durability_hours"] = 2
    put(w, "Anna", "field")
    gift(w, "Anna", tool=1)
    act(w, "Anna", "work", hours=2)
    engine.step(w, {})
    check(w)
    assert "tool" not in w.agents["Anna"].inventory


def test_resources_run_out_and_regrow(w):
    put(w, "Anna", "field")
    tiles.clear(w.locations["field"], "grain")
    tiles.grow(w.locations["field"], "grain", 2, 5, 40)
    act(w, "Anna", "work")
    assert w.agents["Anna"].inventory["grain"] == 2
    assert w.locations["field"].resources["grain"] == 0
    while w.day == 1:
        engine.step(w, {})
    assert w.locations["field"].resources["grain"] == 10


def test_craft_rules(w):
    gift(w, "Anna", grain=4)
    act(w, "Anna", "craft", recipe="bread", times=2)
    assert w.agents["Anna"].inventory == {"bread": 2}
    gift(w, "Anna", wood=2, ore=1)
    put(w, "Anna", "smithy")
    assert errors(act(w, "Anna", "craft", recipe="tool"))  # not a smith
    gift(w, "Elena", wood=2, ore=1)
    put(w, "Elena", "smithy")
    act(w, "Elena", "craft", recipe="tool")
    assert w.agents["Elena"].inventory == {"tool": 1}


def test_trade_is_atomic_and_needs_both_present(w):
    gift(w, "Anna", bread=2)
    gift(w, "Boris", fish=5)
    act(w, "Anna", "offer", to="Boris", give={"bread": 1}, want={"fish": 3})
    oid = next(iter(w.offers))
    assert errors(act(w, "Boris", "accept", offer_id=oid))  # not in the same place
    put(w, "Anna", "square")
    put(w, "Boris", "square")
    act(w, "Boris", "accept", offer_id=oid)
    assert w.agents["Anna"].inventory == {"bread": 1, "fish": 3}
    assert w.agents["Boris"].inventory == {"fish": 2, "bread": 1}
    assert not w.offers


def test_offer_with_coins_and_expiry(w):
    put(w, "Anna", "square")
    put(w, "Boris", "square")
    gift(w, "Boris", fish=1)
    act(w, "Anna", "offer", to="Boris", give={"coins": 5}, want={"fish": 1})
    for _ in range(w.config["offer_ttl_ticks"]):
        engine.step(w, {})
    assert not w.offers


def test_lend_repay_and_default(w):
    put(w, "Anna", "square")
    put(w, "Boris", "square")
    act(w, "Anna", "lend", to="Boris", coins=10, repay_coins=12, due_day=2)
    d = next(iter(w.debts.values()))
    assert w.agents["Boris"].coins == 30
    act(w, "Boris", "repay", debt_id=d.id, coins=5)
    assert d.coins_owed == 7 and d.status == "open"
    while w.day <= 2:
        engine.step(w, {})
    engine.step(w, {})
    while w.day <= 3:
        engine.step(w, {})
    assert d.status == "defaulted"


def test_market_buy_sell_and_coin_ledger(w):
    put(w, "Anna", "market")
    gift(w, "Anna", grain=10)
    act(w, "Anna", "sell", item="grain", qty=10)
    assert w.agents["Anna"].coins == 20 + 10
    act(w, "Anna", "buy", item="bread", qty=1)
    assert w.agents["Anna"].coins == 30 - 9
    assert errors(act(w, "Anna", "sell", item="water"))


def test_chest_sharing_and_betrayal(w):
    gift(w, "Anna", bread=5, coins=0)
    act(w, "Anna", "store", items={"bread": 5}, coins=20)
    act(w, "Anna", "share_chest", person="Boris")
    put(w, "Boris", "home_Anna")
    act(w, "Boris", "take", items={"bread": 5}, coins=20)
    assert w.agents["Boris"].inventory["bread"] == 5
    assert any("took" in m for m in w.agents["Anna"].inbox)
    act(w, "Anna", "unshare_chest", person="Boris")
    assert errors(act(w, "Boris", "store", items={"bread": 1}))


def test_steal_from_chest_and_lock(w):
    gift(w, "Anna", bread=5)
    act(w, "Anna", "store", items={"bread": 5})
    put(w, "Boris", "home_Anna")
    put(w, "Anna", "square")
    act(w, "Boris", "steal", target="chest", item="bread", qty=10)
    assert w.agents["Boris"].inventory["bread"] == 3  # max 3 per theft
    assert any("Someone stole" in m for m in w.agents["Anna"].inbox)
    put(w, "Anna", "home_Anna")
    gift(w, "Anna", lock=1)
    act(w, "Anna", "install_lock")
    assert errors(act(w, "Boris", "steal", target="chest", item="bread"))


def test_steal_from_sleeping_person_and_witnesses(w):
    w.config["steal_notice_chance"] = 1.0
    for n in ("Anna", "Boris", "Clara"):
        put(w, n, "square")
    act(w, "Anna", "sleep")
    act(w, "Boris", "steal", target="Anna", item="coins", qty=3)
    assert w.agents["Boris"].coins == 23 and w.agents["Anna"].coins == 17
    assert any("You saw Boris steal" in m for m in w.agents["Clara"].inbox)


def test_fire_burns_chest_unless_put_out(w):
    gift(w, "Anna", bread=3)
    act(w, "Anna", "store", items={"bread": 3}, coins=5)
    engine.step(w, {}, [{"name": "fire", "args": {"person": "Anna"}}])
    for _ in range(4):
        engine.step(w, {})
    assert w.fires["home_Anna"].water_needed == 5  # nobody fights it: +1 bucket every 2 hours
    for _ in range(6):
        engine.step(w, {})
        check(w)
    assert "home_Anna" not in w.fires
    assert w.chests["chest_Anna"].items == {} and w.chests["chest_Anna"].coins == 0
    # second fire, put out by a neighbour
    engine.step(w, {}, [{"name": "fire", "args": {"person": "Boris"}}])
    put(w, "Clara", "home_Boris")
    gift(w, "Clara", water=3)
    act(w, "Clara", "extinguish")  # pours all 3 buckets at once
    assert "home_Boris" not in w.fires and w.agents["Clara"].inventory.get("water", 0) == 0


def test_tax_and_eviction(w):
    w.agents["Anna"].coins = 0
    w.ledger["coins"] -= 20
    while w.day < 8:
        engine.step(w, {})
        check(w)
    assert w.agents["Anna"].evicted_until_day == 10
    assert w.agents["Boris"].coins == 0  # paid 20
    act(w, "Anna", "store", items={})  # evicted: no access to own chest
    assert "store" not in engine.observe(w, "Anna")["available_actions"]


def test_starvation_leads_to_hospital_and_back(w):
    a = w.agents["Anna"]
    a.satiety, a.health = 0, 5
    gift(w, "Anna", grain=5)
    engine.step(w, {})
    check(w)
    assert a.status == "hospital" and a.inventory == {"grain": 2}
    while a.status == "hospital":
        engine.step(w, {})
        check(w)
    assert a.location == a.home and a.health == 60


def test_death_mode(w):
    w.config["death_mode"] = "death"
    w.agents["Anna"].satiety, w.agents["Anna"].health = 0, 1
    engine.step(w, {})
    assert w.agents["Anna"].status == "dead"
    assert "Anna" not in engine.waiting_agents(w)


def test_project_rewards_everyone(w):
    put(w, "Anna", "square")
    gift(w, "Anna", wood=40, stone=30)
    act(w, "Anna", "contribute", project_id="bridge", items={"wood": 50, "stone": 30})
    assert w.projects["bridge"].done
    assert w.agents["Anna"].inventory == {}  # only what the project still needed was taken
    assert all(a.coins == 40 for a in w.agents.values())


def test_order_goes_to_whoever_delivers(w):
    while w.day < 2:
        engine.step(w, {})
    o = next(iter(w.orders.values()))
    put(w, "Clara", "square")
    for k, v in o.needs.items():
        gift(w, "Clara", **{k: v})
    act(w, "Clara", "fulfill_order", order_id=o.id)
    assert o.status == "fulfilled" and w.agents["Clara"].coins == 20 + o.reward


def test_letters_arrive_next_hour_and_interrupt_work(w):
    put(w, "Boris", "river")
    engine.step(w, {"Boris": {"action": {"name": "work", "args": {"hours": 4}}},
                    "Anna": {"action": {"name": "letter", "args": {"to": "Boris", "text": "meet me"}}}})
    assert w.agents["Boris"].task is not None
    engine.step(w, {})
    assert w.agents["Boris"].task is None
    assert any("meet me" in m for m in w.agents["Boris"].inbox)


def test_say_is_heard_only_here(w):
    put(w, "Anna", "square")
    put(w, "Boris", "square")
    engine.step(w, {"Anna": {"action": {"name": "wait"}, "say": "Hello square"}})
    assert any("Hello square" in m for m in w.agents["Boris"].inbox)
    assert not any("Hello square" in m for m in w.agents["Clara"].inbox)


def test_treasure_hint_and_pick_up(w):
    engine.step(w, {}, [{"name": "treasure", "args": {"location": "mine", "items": {"ore": 4}, "tell": "Anna"}}])
    engine.step(w, {})
    assert any("ore" in m for m in w.agents["Anna"].inbox)
    put(w, "Anna", "mine")
    act(w, "Anna", "pick_up", item="ore", qty=4)
    assert w.agents["Anna"].inventory["ore"] == 4


def _busy(w, *names):
    for n in names:
        put(w, n, "river")
    engine.step(w, {n: {"action": {"name": "work", "args": {"hours": 4}}} for n in names})
    assert all(w.agents[n].task is not None for n in names)


def test_chatter_does_not_wake_busy_bystanders_but_mention_does(w):
    put(w, "Anna", "river")
    _busy(w, "Boris", "Clara")
    engine.step(w, {"Anna": {"action": {"name": "wait"}, "say": "Nice weather"}})
    assert w.agents["Boris"].task is not None and w.agents["Clara"].task is not None
    engine.step(w, {"Anna": {"action": {"name": "wait"}, "say": "boris, come help me"}})
    assert w.agents["Boris"].task is None
    assert w.agents["Clara"].task is not None


def test_give_wakes_receiver_not_bystander(w):
    put(w, "Anna", "river")
    gift(w, "Anna", fish=1)
    _busy(w, "Boris", "Clara")
    engine.step(w, {"Anna": {"action": {"name": "give", "args": {"to": "Boris", "items": {"fish": 1}}}}})
    assert w.agents["Boris"].task is None
    assert w.agents["Clara"].task is not None


def test_fire_wakes_everyone(w):
    _busy(w, "Boris", "Clara")
    engine.step(w, {}, [{"name": "fire", "args": {"person": "Anna"}}])
    assert w.agents["Boris"].task is None and w.agents["Clara"].task is None


def test_hunger_wakes_once(w):
    _busy(w, "Boris")
    w.agents["Boris"].satiety = 1
    engine.step(w, {})
    assert w.agents["Boris"].task is None and w.agents["Boris"].satiety == 0
    engine.step(w, {"Boris": {"action": {"name": "work", "args": {"hours": 4}}}})
    engine.step(w, {})
    assert w.agents["Boris"].task is not None

def test_winter_field_yields_nothing_until_spring():
    w = engine.new_world({"seed": 1, "seasons": {"length_days": 2}})
    assert engine.observe(w, "Anna", consume_inbox=False)["time"]["season"] == "spring"
    while w.day < 7:  # day 7 = first day of winter
        engine.step(w, {})
    check(w)
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert obs["time"]["season"] == "winter" and obs["time"]["next_season"] == "spring"
    assert any("Winter has come" in n for n in obs["news"])
    assert w.locations["field"].resources["grain"] == 0
    put(w, "Anna", "field")
    act(w, "Anna", "work")
    assert w.agents["Anna"].inventory.get("grain", 0) == 0
    while w.day < 9:  # spring again: the field regrows
        engine.step(w, {})
    assert w.locations["field"].resources["grain"] == 10


def test_seasons_can_be_disabled():
    w = engine.new_world({"seed": 1, "seasons": {"enabled": False, "length_days": 1}, "crises": {"enabled": False}})
    while w.day < 5:
        engine.step(w, {})
    assert w.locations["field"].resources["grain"] == 40
    assert "season" not in engine.observe(w, "Anna", consume_inbox=False)["time"]


def test_trees_fall_and_regrow_as_objects(w):
    forest = w.locations["forest"]
    assert forest.slots["wood"] == [10] * 8 and forest.resources["wood"] == 80
    put(w, "Clara", "forest")
    gift(w, "Clara", tool=1)
    events = act(w, "Clara", "work", resource="wood", hours=2)  # 6 wood per hour, finishes one tree first
    assert forest.slots["wood"] == [4] + [10] * 7
    events += engine.step(w, {})
    assert forest.slots["wood"] == [0, 8] + [10] * 6
    assert [e.data["slot"] for e in events if e.kind == "slot_empty"] == [0]
    while w.day == 1:
        engine.step(w, {})
    assert forest.slots["wood"] == [10] * 8  # regrowth refills the stump first
    view = run.view(w)
    assert view["map"]["forest"]["slots"]["wood"] == [10] * 8


def test_plant_and_harvest_a_bed(w):
    field = w.locations["field"]
    put(w, "Anna", "field")
    gift(w, "Anna", grain=1)
    assert "no free bed" in errors(act(w, "Anna", "plant"))[0]
    tiles.clear(field, "grain")
    act(w, "Anna", "plant")
    assert field.planted == {"0": {"resource": "grain", "by": "Anna", "ripe_day": 3}}
    assert engine.observe(w, "Anna", consume_inbox=False)["here"]["beds"]["grain"]["growing"] == [3]
    assert "grain" not in w.agents["Anna"].inventory
    while w.day < 2:
        engine.step(w, {})
        check(w)
    assert field.slots["grain"][0] == 0 and field.slots["grain"][1] > 0  # sown bed waits, others regrow
    while w.day < 3:
        engine.step(w, {})
    check(w)
    assert field.planted == {} and field.slots["grain"][0] == 5
    assert any("is ripe" in n for n in w.agents["Anna"].inbox)


def test_fire_grows_and_pouring_is_logged(w):
    engine.step(w, {}, [{"name": "fire", "args": {"person": "Anna"}}])
    put(w, "Boris", "home_Anna")
    gift(w, "Boris", water=2)
    events = act(w, "Boris", "extinguish")
    pour = [e for e in events if e.kind == "pour_water"][0]
    assert pour.data == {"helper": "Boris", "house": "home_Anna", "buckets": 2, "water_needed": 1}
    assert run.view(w)["fire_info"]["home_Anna"]["water_needed"] >= 1
    while w.hour < 21:
        engine.step(w, {})
    assert "home_Anna" not in w.fires  # 10 hours: burned down before night
