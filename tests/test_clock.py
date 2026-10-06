"""Quarter-hour ticks: game clock, action durations, staggered turns, hourly upkeep, replay."""

import pytest

from aivillage import clock, engine
from aivillage.invariants import check
from aivillage.llm import SYSTEM, world_facts
from aivillage.run import bots_decider, replay, run, view, with_tick_minutes

Q = {"tick_minutes": 15}


def world(**over):
    return engine.new_world({**Q, "seed": 4, **over})


def free_all(w):
    for a in w.agents.values():
        a.busy_until = w.tick


def test_clock_round_trip():
    cfg = engine.new_world(Q).config
    assert clock.per_hour(cfg) == 4 and clock.per_day(cfg) == 64
    assert clock.time_of(cfg, 0) == (1, 6, 0)
    assert clock.time_of(cfg, 5) == (1, 7, 15)
    assert clock.time_of(cfg, 64) == (2, 6, 0)
    for t in (0, 3, 17, 63, 64, 200):
        assert clock.tick_of(cfg, *clock.time_of(cfg, t)) == t
    assert clock.label(cfg, 6) == "day 1 07:30"
    hourly = engine.new_world().config
    assert clock.time_of(hourly, 17) == (2, 7, 0)


def test_bad_tick_minutes_rejected():
    with pytest.raises(ValueError):
        engine.new_world({"tick_minutes": 25})


def test_runs_default_to_quarter_hours():
    assert with_tick_minutes({}, None)["tick_minutes"] == 15
    assert with_tick_minutes({"tick_minutes": 30}, None)["tick_minutes"] == 30  # run config wins
    assert with_tick_minutes({"tick_minutes": 30}, 60)["tick_minutes"] == 60  # the flag wins


def test_clock_advances_by_quarters_and_night_comes_once():
    w = world()
    seen = []
    for _ in range(64):
        seen.append((w.day, w.hour, w.minute))
        engine.step(w, {})
    assert seen[:5] == [(1, 6, 0), (1, 6, 15), (1, 6, 30), (1, 6, 45), (1, 7, 0)]
    assert (w.day, w.hour, w.minute, w.tick) == (2, 6, 0, 64)


def test_upkeep_runs_once_per_hour():
    w = world()
    a = w.agents["Anna"]
    start = a.satiety
    for _ in range(3):
        engine.step(w, {})
    assert a.satiety == start  # no hunger inside the hour
    engine.step(w, {})
    assert a.satiety == start - w.config["satiety_loss_per_hour"]


def test_morning_turns_are_staggered():
    w = world(population={"size": 12})
    offsets = {a.busy_until for a in w.agents.values()}
    assert len(offsets) > 1 and offsets <= {0, 1, 2, 3}
    assert engine.waiting_agents(w) != sorted(w.agents)
    hourly = engine.new_world({"seed": 4, "population": {"size": 12}})
    assert engine.waiting_agents(hourly) == sorted(hourly.agents)  # the old mode is untouched


def test_quick_action_frees_next_tick_long_action_after_an_hour():
    w = world()
    free_all(w)
    w.agents["Boris"].location = w.agents["Anna"].location
    engine.step(w, {"Anna": {"action": {"name": "say", "args": {"text": "hello"}}},
                    "Boris": {"action": {"name": "wait"}}})
    assert engine.needs_decision(w, "Anna")
    assert not engine.needs_decision(w, "Boris")
    for _ in range(3):
        engine.step(w, {})
    assert engine.needs_decision(w, "Boris")


def test_talking_with_wait_is_quick_and_failure_costs_a_quarter():
    w = world()
    free_all(w)
    engine.step(w, {"Anna": {"say": "anyone?", "action": {"name": "wait"}},
                    "Boris": {"action": {"name": "fly"}}})
    assert engine.needs_decision(w, "Anna") and engine.needs_decision(w, "Boris")


def test_work_task_continues_hourly():
    w = world()
    free_all(w)
    a = w.agents["Clara"]  # woodcutter
    a.location = "forest"
    engine.step(w, {"Clara": {"action": {"name": "work", "args": {"resource": "wood", "hours": 3}}}})
    work_ticks = [0]
    for _ in range(12):
        t = w.tick
        evs = engine.step(w, {})
        if any(e.kind == "work" and e.actor == "Clara" for e in evs):
            work_ticks.append(t)
    assert work_ticks == [0, 4, 8]
    assert engine.needs_decision(w, "Clara")


def test_letter_arrives_an_hour_later_and_offer_lives_hours():
    w = world()
    free_all(w)
    engine.step(w, {"Anna": {"action": {"name": "letter", "args": {"to": "Boris", "text": "hi"}}}})
    assert w.mail[0].deliver_tick == 4
    w.agents["Boris"].location = w.agents["Anna"].location
    engine.step(w, {"Anna": {"action": {"name": "offer", "args": {"to": "Boris", "give": {"coins": 1},
                                                                    "want": {"coins": 1}}}}})
    off = next(iter(w.offers.values()))
    assert off.expires_tick == 1 + 4 * w.config["offer_ttl_ticks"]


def test_view_has_minutes_and_busy():
    w = world()
    free_all(w)
    w.agents["Clara"].location = "forest"
    engine.step(w, {"Clara": {"action": {"name": "work", "args": {"resource": "wood"}}},
                    "Anna": {"action": {"name": "say", "args": {"text": "hey"}}}})
    v = view(w)
    assert (v["hour"], v["minute"], v["tick_minutes"]) == (6, 15, 15)
    assert v["agents"]["Clara"]["busy"] == 45 and v["agents"]["Anna"]["busy"] == 0
    assert engine.observe(w, "Anna")["time"]["minute"] == 15


def test_events_carry_minute():
    w = world()
    free_all(w)
    engine.step(w, {})
    evs = engine.step(w, {"Anna": {"action": {"name": "say", "args": {"text": "hey"}}}})
    assert [e.minute for e in evs if e.kind == "say"] == [15]


@pytest.mark.parametrize("seed", range(3))
def test_quarter_fuzz_invariants_and_replay(seed, tmp_path):
    w = engine.new_world({**Q, "seed": seed})
    at = lambda d, h: clock.tick_of(w.config, d, h)
    god = {at(1, 10): [{"name": "fire", "args": {"person": "Anna"}}],
           at(2, 9): [{"name": "treasure", "args": {"location": "forest", "items": {"ore": 5}, "tell": "Boris"}}],
           at(3, 12): [{"name": "sickness", "args": {"person": "Clara", "days": 1}}]}
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["worker", "thief", "random", "trader"], seed), days=5, god_script=god, log_path=log)
    check(w)
    assert w.day == 6 and w.tick == 5 * 64
    assert replay(log).hash() == w.hash()


def test_prompt_explains_quarters_and_optional_thoughts():
    assert "optional" in SYSTEM and "40 words" not in SYSTEM
    cfg = engine.new_world(Q).config
    facts = world_facts(cfg)
    assert "15-minute steps" in facts and "say" in facts
    assert "15-minute steps" not in world_facts(engine.new_world().config)
