"""Riding and pack animals, carts and the carry limit (aivillage/transport.py)."""

import json

from test_neutrality import evaluative

from aivillage import construction, engine, ops, runconfig, transport
from aivillage.invariants import check
from aivillage.run import bots_decider, replay, run

ON = {"seed": 1, "transport": {"enabled": True, "kinds": {"horse": {"catch_chance": 1.0},
                                                          "donkey": {"catch_chance": 1.0}}}}


def world(**kw):
    w = engine.new_world({**ON, **kw})
    for a in w.agents.values():
        a.busy_until = 0
    return w


def act(w, name, action, **args):
    a = w.agents[name]
    a.busy_until, a.task, a.asleep = w.tick, None, False
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def horse_for(w, name, kind="horse"):
    """`name` catches a wild animal where it roams and walks back home with it."""
    a = w.agents[name]
    a.location = "forest" if kind == "horse" else "mine"
    assert errors(act(w, name, "catch_animal", animal=kind)) == []
    a.location = a.home
    return transport.led_by(w, name)[0]


def walk(w, name, to):
    """Ticks until `name` reaches `to` (nobody else acts)."""
    act(w, name, "move", to=to)
    n = 1
    while w.agents[name].location != to:
        engine.step(w, {})
        n += 1
        assert n < 200
    return n


def nights(w, n):
    day = w.day + n
    while w.day < day:
        engine.step(w, {})
    check(w)


def test_off_by_default_changes_nothing():
    w = engine.new_world({"seed": 1})
    assert w.transport == {}
    assert transport.observe(w, "Anna") == {}
    assert transport.hidden_actions(w.config) >= {"catch_animal", "take_animal"}
    w.agents["Anna"].location = "forest"
    assert "catch_animal" not in engine.observe(w, "Anna", consume_inbox=False)["available_actions"]
    assert errors(act(w, "Anna", "catch_animal", animal="horse"))


def test_catch_a_wild_horse_and_lead_it():
    w = world()
    assert w.transport["wild"] == {"forest": {"horse": 2}, "mine": {"donkey": 2}}
    an = horse_for(w, "Anna")
    assert (an["owner"], an["holder"], an["kind"]) == ("Anna", "Anna", "horse")
    assert w.transport["wild"]["forest"]["horse"] == 1
    obs = engine.observe(w, "Anna", consume_inbox=False)["transport"]
    assert obs["your_animals"][0]["id"] == an["id"] and obs["carrying"]["full_pace_up_to"] == 20 + 15
    w.agents["Anna"].location = "forest"
    assert "already lead" in errors(act(w, "Anna", "catch_animal", animal="horse"))[0]
    assert "unknown animal" in errors(act(w, "Anna", "catch_animal", animal="unicorn"))[0]


def test_horse_walks_twice_as_fast_and_a_load_slows_down():
    w = world()
    horse_for(w, "Anna")
    on_foot = walk(w, "Boris", "mine")       # home -> square -> forest -> mine
    w2 = world()
    horse_for(w2, "Anna")
    riding = walk(w2, "Anna", "mine")
    assert riding < on_foot
    w3 = world()
    ops.mint(w3, w3.agents["Boris"].inventory, "stone", 30)
    loaded = walk(w3, "Boris", "mine")
    assert loaded > on_foot
    w4 = world()  # a cart by hand carries 10 more: 30 items at full pace
    ops.mint(w4, w4.agents["Boris"].inventory, "stone", 30)
    ops.mint(w4, w4.agents["Boris"].inventory, "cart", 1)
    assert transport.capacity(w4, "Boris") == 30
    assert walk(w4, "Boris", "mine") == on_foot


def test_donkey_and_cart_carry_more():
    w = world()
    horse_for(w, "Dmitri", "donkey")
    assert transport.capacity(w, "Dmitri") == 20 + 30
    ops.mint(w, w.agents["Dmitri"].inventory, "cart", 1)
    assert transport.capacity(w, "Dmitri") == 20 + 30 + 40
    assert "cart" in w.config["recipes"] and w.config["items"]["hay"]


def test_buy_from_the_trader():
    w = world()
    a = w.agents["Anna"]
    a.location = "market"
    ops.mint_coins(w, a, 100)
    coins = a.coins
    assert errors(act(w, "Anna", "buy_animal", animal="horse")) == []
    assert a.coins == coins - 60 and transport.led_by(w, "Anna")[0]["kind"] == "horse"
    b = w.agents["Boris"]
    b.location = "market"
    ops.mint_coins(w, b, 100)
    assert "no more horses today" in errors(act(w, "Boris", "buy_animal", animal="horse"))[0]
    assert errors(act(w, "Boris", "buy_animal", animal="donkey")) == []


def test_lend_return_and_overdue():
    w = world()
    an = horse_for(w, "Anna")
    w.agents["Boris"].location = w.agents["Anna"].location
    ev = act(w, "Anna", "lend_animal", to="Boris", days=1)
    assert [e for e in ev if e.kind == "animal_lent"][0].to == ["Boris"]
    assert (an["owner"], an["holder"], an["lent_to"]) == ("Anna", "Boris", "Boris")
    assert "lead no animal of your own" in errors(act(w, "Boris", "give_animal", to="Anna"))[0]
    seen = []
    day = w.day + 2
    while w.day < day:
        seen += [e for e in engine.step(w, {}) if e.kind == "animal_overdue"]
    assert len(seen) == 1 and sorted(seen[0].to) == ["Anna", "Boris"]
    w.agents["Anna"].location = "square"
    w.agents["Boris"].location = "forest"
    assert "is not here" in errors(act(w, "Boris", "return_animal"))[0]
    w.agents["Boris"].location = w.agents["Anna"].home
    ev = act(w, "Boris", "return_animal")
    back = [e for e in ev if e.kind == "animal_returned"][0]
    assert back.data["late"] and (an["holder"], an["location"], an["lent_to"]) == (None, "home_Anna", None)


def test_leading_away_someones_animal_is_seen_and_the_owner_can_take_it_back():
    w = world()
    an = horse_for(w, "Anna")
    for n in ("Anna", "Boris", "Clara"):
        w.agents[n].location = "square"
    act(w, "Anna", "leave_animal")
    w.agents["Anna"].location = "river"
    ev = act(w, "Boris", "take_animal", animal=an["id"])
    taken = [e for e in ev if e.kind == "animal_taken"][0]
    assert "Anna" in taken.to and an["holder"] == "Boris" and an["owner"] == "Anna"
    wit = [e for e in ev if e.kind == "witness"]
    assert [e.to for e in wit] == [["Clara"]] and wit[0].data["thief"] == "Boris"
    assert "lead no animal of your own" in errors(act(w, "Boris", "give_animal", to="Clara"))[0]
    w.agents["Anna"].location = "square"
    ev = act(w, "Anna", "take_animal", animal=an["id"])
    assert [e for e in ev if e.kind == "animal_reclaimed"] and an["holder"] == "Anna"


def test_give_animal_passes_ownership():
    w = world()
    an = horse_for(w, "Anna")
    w.agents["Boris"].location = w.agents["Anna"].location
    assert errors(act(w, "Anna", "give_animal", to="Boris")) == []
    assert (an["owner"], an["holder"]) == ("Boris", "Boris")


def test_hunger_weakens_and_an_unfed_animal_runs_off():
    w = world()
    an = horse_for(w, "Anna")  # at home: no grass there, nothing in the trough
    nights(w, 1)
    assert an["strength"] == 2
    nights(w, 1)
    assert an["strength"] == 1 and transport.speed(w, "Anna") == 1.0  # weak: a person's pace
    assert transport.capacity(w, "Anna") == 20 + 15 // 2
    nights(w, 1)
    assert an["id"] not in transport.animals(w)
    assert w.transport["wild"]["forest"]["horse"] == 2  # back to the wild


def test_fed_at_home_regains_strength_and_grazing_keeps_it():
    w = world()
    an = horse_for(w, "Anna")
    ops.mint(w, w.agents["Anna"].inventory, "hay", 3)
    assert errors(act(w, "Anna", "feed_animal", item="hay", qty=3)) == []
    assert an["food"] == 3 and ops.count(w.agents["Anna"].inventory, "hay") == 0
    assert "eat" in errors(act(w, "Anna", "feed_animal", item="stone"))[0]
    nights(w, 1)
    assert (an["strength"], an["food"]) == (4, 2)
    w.agents["Anna"].location = "forest"  # led at a place with berries: grazes, no stable
    an["food"] = 0
    nights(w, 1)
    assert an["strength"] == 4
    ev = act(w, "Anna", "cut_hay")
    assert ops.count(w.agents["Anna"].inventory, "hay") == 4 and not errors(ev)


def test_stable_needed_when_buildings_are_built():
    w = world(construction={"enabled": True})
    an = horse_for(w, "Anna")
    an["strength"], an["food"] = 2, 6
    nights(w, 1)
    assert an["strength"] == 2  # fed, but no stable at home
    construction.place(w, "stable", "home_Anna")
    nights(w, 1)
    assert an["strength"] == 3


def test_opens_with_the_village_stage_in_survival():
    camp = engine.new_world(runconfig.RunConfig(preset="normal", seed=2).world_override())
    assert camp.transport and not transport.active(camp)  # no carry limit, no animals before the village
    name = sorted(camp.agents)[0]
    assert transport.observe(camp, name) == {}
    assert "catch_animal" not in engine.observe(camp, name, consume_inbox=False)["available_actions"]
    ov = runconfig.RunConfig(preset="normal", seed=2).world_override()
    ov["progress"] = {**ov.get("progress", {}), "start_stage": "village"}
    vil = engine.new_world(ov)
    assert transport.active(vil)
    assert "carrying" in engine.observe(vil, sorted(vil.agents)[0], consume_inbox=False)["transport"]


def test_bots_runs_keep_invariants_replay_and_neutral_texts(tmp_path):
    ov = runconfig.RunConfig(preset="normal", seed=3).world_override()
    ov["progress"] = {**ov.get("progress", {}), "start_stage": "village"}
    ov["transport"] = ON["transport"]
    w = engine.new_world(ov)
    found: set[str] = set()
    bots = bots_decider(w, ["random", "worker", "random"], 3)

    def decide(name, obs, _bots=bots):
        found.update(evaluative(json.dumps(obs)))
        return _bots(name, obs)
    decide.bots = bots.bots
    log = tmp_path / "run.jsonl"
    run(w, decide, days=3, log_path=log)
    assert found == set()
    assert replay(log).hash() == w.hash()
    assert evaluative(transport.facts(w.config)) == []
