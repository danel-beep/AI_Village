"""Run a simulation, write a replayable JSONL log, and replay logs.

    python -m aivillage.run --days 10 --bots worker,worker,thief,worker,random --log runs/demo.jsonl
    python -m aivillage.run --replay runs/demo.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable

from . import engine
from .bots import BOT_TYPES
from .invariants import check
from .state import World

LOG_VERSION = 1

# decide(name, observation) -> decision
DecideFn = Callable[[str, dict], dict]


class JsonlLog:
    def __init__(self, path: str | Path | None):
        self.f = None
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.f = open(path, "w", encoding="utf-8")

    def write(self, rec: dict) -> None:
        if self.f:
            self.f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def close(self) -> None:
        if self.f:
            self.f.close()


def run(world: World, decide: DecideFn, days: int, god_script: dict[int, list] | None = None,
        log_path: str | Path | None = None, check_every_tick: bool = True,
        on_tick: Callable[[World, list], None] | None = None) -> dict:
    """Drive the world for `days` days. Returns summary stats."""
    log = JsonlLog(log_path)
    log.write({"type": "header", "version": LOG_VERSION, "config": world.config, "hash": world.hash()})
    stats: Counter = Counter()
    end_day = world.day + days
    try:
        while world.day < end_day:
            asked = engine.waiting_agents(world)
            observations = [(name, engine.observe(world, name)) for name in asked]
            # All agents think at the same time: a slow model does not slow the others down.
            with ThreadPoolExecutor(max_workers=max(1, len(asked))) as pool:
                results = list(pool.map(lambda pair: decide(*pair), observations))
            decisions = dict(zip(asked, results))
            god = (god_script or {}).get(world.tick, [])
            tick = world.tick
            events = engine.step(world, decisions, god)
            if check_every_tick:
                check(world)
            for ev in events:
                stats[ev.kind] += 1
            stats["llm_calls"] += len(asked)
            log.write({"type": "tick", "tick": tick, "asked": asked, "decisions": decisions, "god": god,
                       "events": [asdict(e) for e in events], "hash": world.hash(), "view": view(world)})
            if on_tick:
                on_tick(world, events)
    finally:
        log.close()
    return dict(stats)


def view(world: World) -> dict:
    """Small snapshot for the viewer (not used by replay)."""
    return {"day": world.day, "hour": world.hour,
            "agents": {a.name: {"location": a.location, "status": a.status, "asleep": a.asleep,
                                "satiety": a.satiety, "health": a.health, "coins": a.coins,
                                "profession": a.profession, "inventory": a.inventory}
                       for a in world.agents.values()},
            "fires": list(world.fires), "locations": {l.id: l.name for l in world.locations.values()}}


def read_log(path: str | Path) -> Iterable[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def replay(path: str | Path) -> World:
    """Re-run a log through the engine and verify every tick's hash. Raises on divergence."""
    recs = read_log(path)
    header = next(recs)
    assert header["type"] == "header" and header["version"] == LOG_VERSION
    world = engine.new_world(header["config"])
    if world.hash() != header["hash"]:
        raise AssertionError("initial world differs (engine or config changed)")
    for rec in recs:
        for name in rec["asked"]:
            engine.observe(world, name)
        engine.step(world, rec["decisions"], rec["god"])
        if world.hash() != rec["hash"]:
            raise AssertionError(f"replay diverged at tick {rec['tick']}")
    return world


def bots_decider(world: World, kinds: list[str], seed: int) -> DecideFn:
    names = sorted(world.agents)
    bots = {n: BOT_TYPES[kinds[i % len(kinds)]](n, seed) for i, n in enumerate(names)}
    return lambda name, obs: bots[name].decide(obs)


def summary(world: World, stats: dict) -> str:
    lines = [f"Day {world.day}, tick {world.tick}. Model calls that would be made: {stats.get('llm_calls', 0)}"]
    for a in world.agents.values():
        chest = world.chests[f"chest_{a.name}"]
        lines.append(f"  {a.name:8} {a.profession:10} {a.status:8} hp={a.health:3} food={a.satiety:3} "
                     f"coins={a.coins:4} chest_coins={chest.coins:3} inv={a.inventory}")
    keys = ["trade", "give", "steal", "witness", "lend", "repay", "default", "order_done", "contribute",
            "project_done", "fire_out", "house_burned", "hospital", "evicted", "error"]
    lines.append("  events: " + ", ".join(f"{k}={stats.get(k, 0)}" for k in keys))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the AI Village with scripted bots.")
    p.add_argument("--days", type=int, default=10)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--bots", default="worker", help="comma-separated bot kinds, cycled over agents")
    p.add_argument("--log", default=None, help="write a replayable JSONL log here")
    p.add_argument("--replay", default=None, help="replay and verify a log instead of running")
    p.add_argument("--fire-day", type=int, default=0, help="god: set a random house on fire on this day")
    p.add_argument("--models", default=None,
                   help="LLM agents instead of bots: comma-separated OpenRouter model ids cycled over agents, "
                        "'default' for llm.DEFAULT_MODEL, or 'stub' to test the LLM pipeline without a key")
    p.add_argument("--agents", type=int, default=0, help="use only the first N villagers")
    a = p.parse_args(argv)

    if a.replay:
        w = replay(a.replay)
        print(f"replay OK: {w.tick} ticks, final hash {w.hash()}")
        return 0
    override: dict = {"seed": a.seed}
    if a.agents:
        from .config import DEFAULT_CONFIG
        override["agents"] = DEFAULT_CONFIG["agents"][: a.agents]
    world = engine.new_world(override)
    kinds = a.bots.split(",")
    agents = None
    if a.models:
        agents = llm_agents(world, a.models.split(","))
        decide = lambda name, obs: agents[name].decide(obs)
    else:
        decide = bots_decider(world, kinds, a.seed)
    god = {}
    if a.fire_day:
        hours = world.config["day_end_hour"] - world.config["day_start_hour"]
        victim = sorted(world.agents)[a.seed % len(world.agents)]
        god[(a.fire_day - 1) * hours + 4] = [{"name": "fire", "args": {"person": victim}}]
    stats = run(world, decide, a.days, god, a.log)
    print(summary(world, stats))
    for name, ag in (agents or {}).items():
        u = ag.usage
        print(f"  {name:8} {ag.client.model:30} calls={u.calls} fail={u.failures} "
              f"tokens={u.prompt_tokens}+{u.completion_tokens} cost=${u.cost_usd:.4f}")
    return 0


def llm_agents(world: World, models: list[str]) -> dict:
    from .llm import LLMAgent, OpenRouterClient, StubClient, world_facts, DEFAULT_MODEL
    facts = world_facts(world.config)
    out = {}
    for i, name in enumerate(sorted(world.agents)):
        m = models[i % len(models)]
        m = DEFAULT_MODEL if m == "default" else m
        client = StubClient(name) if m == "stub" else OpenRouterClient(m)
        out[name] = LLMAgent(name, world.agents[name].profession, client, facts=facts)
    return out


if __name__ == "__main__":
    sys.exit(main())
