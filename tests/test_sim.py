"""Whole-simulation tests: thousands of ticks with scripted bots, invariants every tick,
determinism and replay."""

import json

import pytest

from aivillage import engine
from aivillage.invariants import check
from aivillage.run import bots_decider, replay, run


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("bots", ["random", "worker", "worker,thief,random"])
def test_fuzz_invariants_hold(seed, bots):
    w = engine.new_world({"seed": seed})
    god = {20: [{"name": "fire", "args": {"person": "Anna"}}],
           40: [{"name": "treasure", "args": {"location": "forest", "items": {"ore": 5}, "tell": "Boris"}}],
           60: [{"name": "drought", "args": {"location": "field", "days": 2}}],
           80: [{"name": "sickness", "args": {"person": "Clara", "days": 1}}],
           90: [{"name": "gift", "args": {"person": "Dmitri", "items": {"bread": 2}, "coins": -5}}]}
    run(w, bots_decider(w, bots.split(","), seed), days=12, god_script=god)  # checks invariants every tick
    check(w)
    assert w.day == 13


def test_long_run_with_death_mode():
    w = engine.new_world({"seed": 7, "death_mode": "death"})
    run(w, bots_decider(w, ["random"], 7), days=30)
    check(w)


def test_same_seed_same_world():
    hashes = []
    for _ in range(2):
        w = engine.new_world({"seed": 3})
        run(w, bots_decider(w, ["worker", "thief", "random"], 3), days=5)
        hashes.append(w.hash())
    assert hashes[0] == hashes[1]


def test_replay_reproduces_every_tick(tmp_path):
    log = tmp_path / "run.jsonl"
    w = engine.new_world({"seed": 5})
    god = {10: [{"name": "fire", "args": {"person": "Elena"}}]}
    run(w, bots_decider(w, ["worker", "thief", "random"], 5), days=4, god_script=god, log_path=log)
    replayed = replay(log)
    assert replayed.hash() == w.hash()


def test_replay_detects_tampering(tmp_path):
    log = tmp_path / "run.jsonl"
    w = engine.new_world({"seed": 5})
    run(w, bots_decider(w, ["worker"], 5), days=2, log_path=log)
    lines = log.read_text().splitlines()
    rec = json.loads(lines[5])
    name = rec["asked"][0] if rec["asked"] else "Anna"
    rec["decisions"][name] = {"action": {"name": "move", "args": {"to": "mine"}}}
    rec["asked"] = sorted(set(rec["asked"]) | {name})
    lines[5] = json.dumps(rec)
    log.write_text("\n".join(lines) + "\n")
    with pytest.raises(AssertionError, match="diverged"):
        replay(log)


def test_observation_is_json_and_lists_actions():
    w = engine.new_world()
    obs = engine.observe(w, "Anna")
    json.dumps(obs)
    assert "move" in obs["available_actions"] and "sleep" in obs["available_actions"]
    assert obs["you"]["location"] == "home_Anna"


def test_busy_agents_are_not_asked():
    w = engine.new_world()
    engine.step(w, {"Anna": {"action": {"name": "move", "args": {"to": "mine"}}}})
    assert "Anna" not in engine.waiting_agents(w)  # still walking: square -> forest -> mine
    engine.step(w, {})
    engine.step(w, {})
    assert w.agents["Anna"].location == "mine"
    assert "Anna" in engine.waiting_agents(w)
