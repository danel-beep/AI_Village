"""Cooperation audit items: a neighbour's hunger is seen, what was said to a villager stays in view, and a gift
is carried wherever a trade is."""

from aivillage import engine, ops, runconfig
from aivillage.invariants import check
from aivillage.run import bots_decider, run


def world(mode="standard", **over):
    return engine.new_world(runconfig.RunConfig(mode=mode, seed=3).world_override() | over)


def step(w, decisions):
    events = engine.step(w, {n: {"action": d} if "name" in d else d for n, d in decisions.items()})
    check(w)
    return events


def person(obs, name):
    return next(p for p in obs["here"]["people"] if p["name"] == name)


def test_hunger_is_seen_by_people_nearby():
    w = world()
    a, b = sorted(w.agents)[:2]
    w.agents[b].location = w.agents[a].location
    w.agents[b].satiety = 50
    assert "hungry" not in person(engine.observe(w, a, consume_inbox=False), b)
    w.agents[b].satiety = 29
    assert person(engine.observe(w, a, consume_inbox=False), b).get("hungry") is True
    w.agents[b].satiety = 0
    p = person(engine.observe(w, a, consume_inbox=False), b)
    assert p.get("starving") is True and "hungry" not in p
    w.config["hungry_seen_below"] = 0
    assert "starving" not in person(engine.observe(w, a, consume_inbox=False), b)


def test_letters_whispers_and_named_words_stay_until_next_day():
    w = world()
    a, b, c = sorted(w.agents)[:3]
    w.agents[b].location = w.agents[c].location = w.agents[a].location
    step(w, {a: {"name": "letter", "args": {"to": b, "text": "Can you spare some fish?"}}})
    step(w, {c: {"name": "whisper", "args": {"to": b, "text": "Meet me at the river"}}})
    step(w, {a: {"action": {"name": "wait"}, "say": f"Hello {b}, how are you?"}})
    step(w, {c: {"action": {"name": "wait"}, "say": "Nice weather"}})  # no name: not kept
    for _ in range(4):
        step(w, {})
    said = engine.observe(w, b)["said_to_you"]
    assert sorted((m["from"], m["how"]) for m in said) == sorted([(c, "whisper"), (a, "said"), (a, "letter")])
    assert any(m["text"] == "Can you spare some fish?" for m in said)
    assert "said_to_you" not in engine.observe(w, c)  # the sender keeps nothing
    # still there the next day, gone the day after
    w.day += 1
    assert len(engine.observe(w, b)["said_to_you"]) == 3
    w.day += 1
    assert "said_to_you" not in engine.observe(w, b)


def test_a_gift_or_trade_between_the_two_clears_their_messages():
    w = world()
    a, b, c = sorted(w.agents)[:3]
    for n in (a, b, c):
        w.agents[n].location = "square"
    step(w, {a: {"name": "whisper", "args": {"to": b, "text": "I am out of food"}}})
    step(w, {c: {"name": "whisper", "args": {"to": b, "text": "hi"}}})
    ops.mint(w, w.agents[b].inventory, "fish", 1)
    step(w, {b: {"name": "give", "args": {"to": a, "items": {"fish": 1}}}})
    assert [m["from"] for m in engine.observe(w, b)["said_to_you"]] == [c]


def test_old_messages_drop_out_past_the_limit():
    w = world()
    a, b = sorted(w.agents)[:2]
    w.agents[b].location = w.agents[a].location
    for i in range(7):
        step(w, {a: {"name": "whisper", "args": {"to": b, "text": f"note {i}"}}})
    assert [m["text"] for m in engine.observe(w, b)["said_to_you"]] == [f"note {i}" for i in range(2, 7)]


def test_off_without_config_key_keeps_the_world_hash():
    w = world()
    del w.config["said_to_you"]
    a, b = sorted(w.agents)[:2]
    w.agents[b].location = w.agents[a].location
    step(w, {a: {"name": "whisper", "args": {"to": b, "text": "hello"}}})
    assert w.addressed == {} and "addressed" not in w.to_dict()
    assert "said_to_you" not in engine.observe(w, b)


def test_gift_is_carried_where_trades_are():
    w = world("crafts")
    a, b = sorted(w.agents)[:2]
    w.agents[a].location, w.agents[b].location = "square", "river"
    ops.mint(w, w.agents[a].inventory, "fish", 2)
    events = step(w, {a: {"name": "give", "args": {"to": b, "items": {"fish": 2}}}})
    give = next(e for e in events if e.kind == "give")
    assert give.data.get("carried") and w.agents[b].inventory.get("fish", 0) >= 2
    # without carried trades a gift still needs both in one place
    w.config["labor"]["trade_anywhere"] = False
    ops.mint(w, w.agents[a].inventory, "fish", 1)
    events = step(w, {a: {"name": "give", "args": {"to": b, "items": {"fish": 1}}}})
    assert any(e.kind == "error" and "not here" in e.text for e in events)


def test_bots_run_clean_with_the_new_signals():
    for mode in ("crafts", "survival"):
        w = world(mode)
        run(w, bots_decider(w, ["random", "worker", "thief"], 4), days=2)
        check(w)
