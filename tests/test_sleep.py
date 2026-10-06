"""Daytime sleep is a nap; going to bed in the evening sleeps until morning; council orders differ."""

from aivillage import clock, engine
from aivillage.invariants import check


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def test_daytime_sleep_is_a_nap():
    w = engine.new_world({"seed": 1})
    ev = act(w, "Anna", "sleep")
    assert any("nap until 08:00" in e.text for e in ev)
    a = w.agents["Anna"]
    assert a.asleep and not engine.needs_decision(w, "Anna")
    engine.step(w, {})
    assert a.asleep
    engine.step(w, {})  # two hours later (60-minute ticks in engine tests)
    assert not a.asleep and engine.needs_decision(w, "Anna")


def test_evening_sleep_lasts_until_morning():
    w = engine.new_world({"seed": 1, "tick_minutes": 15})
    while w.hour < w.config["sleep_from_hour"]:
        engine.step(w, {})
    act(w, "Anna", "sleep")
    a = w.agents["Anna"]
    for _ in range(clock.hours(w.config, 1)):
        engine.step(w, {})
    assert a.asleep and a.task is None
    while w.day == 1:
        engine.step(w, {})
    assert not a.asleep


def test_letter_wakes_a_napper():
    w = engine.new_world({"seed": 1})
    act(w, "Anna", "sleep")
    act(w, "Boris", "letter", to="Anna", text="Wake up, I have fish for you")
    engine.step(w, {})
    assert not w.agents["Anna"].asleep


def test_council_orders_posted_together_differ():
    w = engine.new_world({"seed": 1, "orders_per_post": 2})
    while w.day < 2:
        engine.step(w, {})
    needs = [tuple(sorted(o.needs.items())) for o in w.orders.values()]
    assert len(needs) == 2 and needs[0] != needs[1]
