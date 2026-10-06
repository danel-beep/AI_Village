"""Raids, beasts, travelers (threats.py), sickness (illness.py) and spreading fire."""

from aivillage import clock, engine, knobs, ops, run, threats
from aivillage.invariants import check
from aivillage.run import bots_decider, replay

QUIET = {"crises": {"enabled": False}, "illness": {"spread_chance": 0.0}}


def world(**over):
    return engine.new_world({"seed": 1, **QUIET, **over})


def step(w, decisions=None, god=None):
    events = engine.step(w, decisions or {}, god)
    check(w)
    return events


def act(w, name, action, **args):
    return step(w, {name: {"action": {"name": action, "args": args}}})


def kinds(events):
    return [e.kind for e in events]


def until(w, tick):
    events = []
    while w.tick < tick:
        events += step(w)
    return events


def test_warned_raid_is_announced_and_arrives_on_time():
    w = world()
    ev = step(w, god=[{"name": "raid", "args": {"target": "Anna", "in_days": 2, "warn": True}}])
    warn = [e for e in ev if e.kind == "threat_warning"][0]
    assert warn.visibility == "public" and "home_Anna" in warn.text and "day 3" in warn.text
    obs = engine.observe(w, "Boris", consume_inbox=False)
    assert obs["threats"] == [{"what": "bandits", "expected": "day 3 around 11:00", "where": "home_Anna"}]
    t = w.threats[0]
    assert t["arrive_tick"] == clock.tick_of(w.config, 3, 11)
    ev = until(w, t["arrive_tick"] + 1)
    assert "threat_arrived" in kinds(ev) and t["state"] == "here" and t["location"] == "home_Anna"
    assert run.view(w)["threats"][0]["kind"] == "raid"


def test_unwarned_raid_is_invisible_until_it_comes():
    w = world()
    ev = step(w, god=[{"name": "raid", "args": {"in_days": 1, "warn": False}}])
    assert "threat_warning" not in kinds(ev)
    assert "threats" not in engine.observe(w, "Anna", consume_inbox=False)
    assert run.view(w)["threats"] == []


def test_unopposed_raid_plunders_moves_on_and_burns():
    w = world()
    chest = w.chests["chest_Anna"]
    ops.mint(w, chest.items, "fish", 10)
    ops.mint_coins(w, chest, 20)
    step(w, god=[{"name": "raid", "args": {"target": "Anna", "warn": False}}])
    ev = []
    for _ in range(12):
        ev += step(w)
        if w.threats[0]["state"] == "gone":
            break
    t = w.threats[0]
    plunder = [e for e in ev if e.kind == "plundered"]
    assert plunder[0].data["home"] == "home_Anna" and plunder[0].data["items"] == {"fish": 4}  # 40%
    assert plunder[0].data["coins"] == 8 and plunder[1].data["home"] == "home_Anna"  # two hours a house
    assert len({e.data["home"] for e in plunder}) == 3  # house after house
    assert t["state"] == "gone" and "threat_left" in kinds(ev)
    assert [e for e in ev if e.kind == "fire" and e.data.get("cause") == "bandits"]


def test_defenders_drive_off_bandits_and_get_the_loot_back():
    w = world(threats={"kinds": {"raid": {"hp": 20}}})  # hourly test ticks: one swing each per hour
    ops.mint(w, w.chests["chest_Anna"].items, "fish", 10)
    step(w, god=[{"name": "raid", "args": {"target": "Anna", "warn": False}}])  # they come next tick
    t = w.threats[0]
    t["loot"], t["loot_coins"] = {"fish": 4}, 6   # as if they had already plundered
    ops.burn(w, w.chests["chest_Anna"].items, "fish", 4)
    for n in ("Anna", "Boris", "Clara"):
        w.agents[n].location = "home_Anna"
    coins = {n: w.agents[n].coins for n in ("Anna", "Boris", "Clara")}
    ev = []
    for _ in range(80):
        if t["state"] not in ("coming", "here"):
            break
        for n in ("Anna", "Boris", "Clara"):
            w.agents[n].health = 100
        ev += step(w, {n: {"action": {"name": "defend", "args": {}}} for n in ("Anna", "Boris", "Clara")})
    assert t["state"] == "defeated"
    assert "plundered" not in kinds(ev)  # fought every hour
    won = [e for e in ev if e.kind == "threat_defeated"][0]
    assert w.locations["home_Anna"].ground.get("fish") == 4
    paid = sum(w.agents[n].coins - coins[n] for n in coins)
    assert paid == sum(won.data["coins"].values()) == 6 + 20  # their purse + the bounty
    assert set(won.data["fighters"]) <= {"Anna", "Boris", "Clara"}


def test_wall_weakens_raiders():
    w = world(projects={"wall": {"name": "Wall", "needs": {"stone": 1}, "reward_coins_each": 0}})
    w.projects["wall"].done = True
    step(w, god=[{"name": "raid", "args": {"target": "Anna", "warn": False}}])
    step(w)
    assert w.threats[0]["max_hp"] == round(60 * 0.6)


def test_beast_eats_food_and_mauls():
    w = world()
    ops.mint(w, w.chests["chest_Anna"].items, "fish", 10)
    w.agents["Anna"].location = "home_Anna"
    step(w, god=[{"name": "beast", "args": {"target": "Anna", "warn": False}}])
    ev = []
    while not [e for e in ev if e.kind == "beast_attack"]:
        ev += step(w)
    hit = [e for e in ev if e.kind == "beast_attack"][0]
    assert hit.data["items"] == {"fish": 5} and hit.data["victim"] == "Anna"
    assert w.agents["Anna"].health == 100 - hit.data["damage"] and hit.data["damage"] > 0


def test_honest_traveler_rewards_helpers():
    w = world()
    w.agents["Boris"].location = "square"
    ops.mint(w, w.agents["Boris"].inventory, "fish", 3)
    step(w, god=[{"name": "traveler", "args": {}}])
    step(w)
    obs = engine.observe(w, "Boris", consume_inbox=False)
    assert obs["threats"][0]["asks_food"] == 2 and "help_stranger" in obs["available_actions"]
    before = (w.agents["Boris"].coins, dict(w.agents["Boris"].inventory))
    act(w, "Boris", "help_stranger", item="fish")
    ev = act(w, "Boris", "help_stranger", item="fish")
    thanks = [e for e in ev if e.kind == "stranger_thanks"][0]
    assert "Boris" in thanks.data["gifts"]
    assert (w.agents["Boris"].coins, w.agents["Boris"].inventory) != before


def test_scout_brings_a_raid_unless_chased():
    for chase in (False, True):
        w = world()
        w.agents["Boris"].location = "square"
        step(w, god=[{"name": "traveler", "args": {"scout": True}}])
        step(w)
        if chase:
            act(w, "Boris", "chase_stranger")
        while w.day < 2:
            step(w)
        raids = [t for t in w.threats if t["kind"] == "raid"]
        assert bool(raids) is not chase
        if raids:
            assert raids[0]["warned"] is False and raids[0]["from_scout"]


def test_random_threats_follow_their_chance():
    for p, expect in ((0.0, 0), (1.0, 1)):
        w = world(threats={"kinds": {"raid": {"per_day": p}}, "warn_chance": 1.0})
        while w.day < 2:
            step(w)
        assert len(w.threats) == expect
        if expect:
            assert w.threats[0]["warned"] and w.threats[0]["arrive_day"] == 4


def test_fire_spreads_to_a_neighbour_once():
    w = world()
    step(w, god=[{"name": "fire", "args": {"person": "Anna"}}])
    ev = []
    for _ in range(w.config["fire_spread_hours"] + 1):
        ev += step(w)
    spread = [e for e in ev if e.kind == "fire" and e.data.get("cause") == "spread"]
    assert len(spread) == 1 and spread[0].data["spread_from"] == "home_Anna"
    assert len(w.fires) == 2


def test_sickness_spreads_hurts_and_is_cured_by_care():
    w = world(illness={"spread_chance": 1.0})
    for n in ("Anna", "Boris"):
        w.agents[n].location = "square"
    step(w, god=[{"name": "sickness", "args": {"person": "Anna", "days": 3}}])
    assert w.day < w.agents["Boris"].sick_until_day  # caught it at the square
    w.agents["Boris"].location = "market"  # away from home: no rest at night
    ops.mint(w, w.agents["Clara"].inventory, "honey", 1)
    w.agents["Clara"].location = "square"
    ev = act(w, "Clara", "care", person="Anna", item="honey")
    assert "care" in kinds(ev) and w.day >= w.agents["Anna"].sick_until_day
    health = w.agents["Boris"].health
    while w.day < 2:
        step(w)
    assert w.agents["Boris"].health < health  # the night wore him down


def test_threat_run_replays_exactly(tmp_path):
    log = tmp_path / "run.jsonl"
    w = engine.new_world({"seed": 4, "threats": {"kinds": {k: {"per_day": 1.0} for k in threats.KINDS},
                                                 "max_active": 3}, "illness": {"per_day": 1.0}})
    god = {5: [{"name": "raid", "args": {"target": "Clara", "warn": False}}]}
    run.run(w, bots_decider(w, ["worker", "thief", "random"], 4), days=4, god_script=god, log_path=log)
    assert replay(log).hash() == w.hash()
    assert any(t["state"] in ("gone", "defeated") for t in w.threats)


def test_presets_set_every_chance():
    keys = {k["key"]: k for k in knobs.active()}
    preset = keys["chaos"]
    for option, values in preset["sets"].items():
        assert set(values) <= set(keys), option
    fair = knobs.to_run({"chaos": "fair"})["override"]
    assert fair["threats"]["kinds"]["raid"]["per_day"] == 0 and fair["crises"]["enabled"] is False
    wild = knobs.to_run({"chaos": "chaos"})["override"]
    assert wild["threats"]["kinds"]["raid"]["per_day"] > 0.1 and wild["random_fires"]["per_day"] > 0
    mine = knobs.to_run({"chaos": "chaos", "raid_chance": 3})["override"]  # a slider moved by hand wins
    assert mine["threats"]["kinds"]["raid"]["per_day"] == 0.03
