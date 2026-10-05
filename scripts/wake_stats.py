"""Measure how many model calls the wake-on-event rules save.

For a few bot scenarios, counts decisions requested under three policies:
  every_hour - every agent that can act is asked every hour (no multi-hour tasks)
  legacy     - old rule: any whisper/offer/steal/fire/say/give/lend the agent saw woke it
  current    - engine.WAKE_RULES (addressed events only, `say` only when your name is mentioned)

Usage: python scripts/wake_stats.py [--days 10] [--seeds 3]
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aivillage import engine, ops  # noqa: E402
from aivillage.run import bots_decider, run  # noqa: E402

LEGACY = {k: "heard" for k in ("whisper", "offer", "steal_attempt", "fire", "say", "give", "lend")}
SMALLTALK = ["Nice weather today.", "Busy day!", "Anyone seen the trader?", "Prices are high lately."]


def chatty(decide, seed: int, p: float):
    """LLM agents talk a lot: add unaddressed small talk to a share of decisions."""
    r = random.Random(seed)

    def wrapped(name, obs):
        dec = decide(name, obs)
        if not dec.get("say") and r.random() < p:
            dec = {**dec, "say": r.choice(SMALLTALK)}
        return dec
    return wrapped


def measure(kinds: list[str], seed: int, days: int, talk: float, rules: dict) -> tuple[int, int]:
    saved_rules = engine.WAKE_RULES
    engine.WAKE_RULES = rules
    try:
        w = engine.new_world({"seed": seed})
        decide = bots_decider(w, kinds, seed)
        if talk:
            decide = chatty(decide, seed, talk)
        can_act = 0

        def on_tick(world, _events):
            nonlocal can_act
            can_act += sum(ops.can_act(a) for a in world.agents.values())
        fire_tick = (w.config["day_end_hour"] - w.hour) + 4  # day 2, a few hours after waking
        stats = run(w, decide, days, {fire_tick: [{"name": "fire", "args": {"person": "Anna"}}]},
                    check_every_tick=False, on_tick=on_tick)
        return stats.get("llm_calls", 0), can_act
    finally:
        engine.WAKE_RULES = saved_rules


SCENARIOS = [
    ("workers", ["worker"], 0.0),
    ("workers + thief", ["worker", "worker", "thief"], 0.0),
    ("chatty workers (30% small talk)", ["worker"], 0.3),
    ("chatty workers + thief", ["worker", "worker", "thief"], 0.3),
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=10)
    p.add_argument("--seeds", type=int, default=3)
    a = p.parse_args(argv)
    print(f"{a.days} days x {a.seeds} seeds, 5 agents, one fire on day 2. Model calls (sum over seeds):\n")
    print("| scenario | every hour | legacy | current | saved vs legacy | saved vs every hour |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for title, kinds, talk in SCENARIOS:
        legacy = current = every = 0
        for s in range(1, a.seeds + 1):
            calls, base = measure(kinds, s, a.days, talk, LEGACY)
            legacy += calls
            calls, base = measure(kinds, s, a.days, talk, engine.WAKE_RULES)
            current += calls
            every += base
        print(f"| {title} | {every} | {legacy} | {current} | {1 - current / legacy:.0%} | {1 - current / every:.0%} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
