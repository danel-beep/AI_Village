"""Run a simulation, write a replayable JSONL log, and replay logs.

    python -m aivillage.run --days 10 --bots worker,worker,thief,worker,random --log runs/demo.jsonl
    python -m aivillage.run --config configs/example.yaml
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

from . import engine, modes, tiles
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
            self.f.flush()  # a problem report can zip the log mid-run

    def close(self) -> None:
        if self.f:
            self.f.close()


def run(world: World, decide: DecideFn, days: int, god_script: dict[int, list] | None = None,
        log_path: str | Path | None = None, check_every_tick: bool = True,
        on_tick: Callable[[World, list], None] | None = None,
        on_night: Callable[[World, int], dict] | None = None,
        on_record: Callable[[dict], None] | None = None) -> dict:
    """Drive the world for `days` days. Returns summary stats.

    `on_night(world, day)` runs after each day ends; whatever it returns is logged as a `diary` record
    (outside the engine, so replay ignores it). `on_record` sees every log record as it is written
    (the live server streams them)."""
    log = JsonlLog(log_path)

    def emit(rec: dict) -> None:
        log.write(rec)
        if on_record:
            on_record(rec)

    emit({"type": "header", "version": LOG_VERSION, "config": world.config, "hash": world.hash()})
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
            tick, day = world.tick, world.day
            events = engine.step(world, decisions, god)
            if check_every_tick:
                check(world)
            for ev in events:
                stats[ev.kind] += 1
            stats["llm_calls"] += len(asked)
            emit({"type": "tick", "tick": tick, "asked": asked, "decisions": decisions, "god": god,
                       "events": [asdict(e) for e in events], "hash": world.hash(), "view": view(world)})
            if on_tick:
                on_tick(world, events)
            if on_night and world.day != day:
                entries = on_night(world, day)
                if entries:
                    emit({"type": "diary", "day": day, "entries": entries})
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
            "kin": {"feelings": world.kin.feelings, "couples": [m.spouses for m in world.kin.marriages.values()]},
            # reputation.py: each villager's own tally of others and the rumors they heard (non-empty only)
            "social": {a.name: {"reputation": a.reputation, "rumors": a.rumors}
                       for a in world.agents.values() if a.reputation or a.rumors},
            "mayor": world.governance.mayor, "treasury": world.governance.coins,
            "fires": list(world.fires), "locations": {l.id: l.name for l in world.locations.values()},
            "fire_info": {f.location: {"water_needed": f.water_needed, "hours_left": f.ticks_left, "hours": f.hours}
                          for f in world.fires.values()},
            "map": {l.id: tiles.snapshot(l, world.config["locations"][l.id]["resources"])
                    for l in world.locations.values() if l.slots}}


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
        if rec.get("type") != "tick":
            continue
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
    p = argparse.ArgumentParser(description="Run the AI Village with scripted bots or LLM agents.")
    p.add_argument("--config", default=None, help="YAML run config (see configs/example.yaml); "
                                                  "flags below override it")
    p.add_argument("--days", type=int, default=None, help="default 3")
    p.add_argument("--seed", type=int, default=None, help="default 1")
    p.add_argument("--bots", default=None, help="comma-separated bot kinds, cycled over agents (default worker)")
    p.add_argument("--log", default=None, help="write a replayable JSONL log here")
    p.add_argument("--replay", default=None, help="replay and verify a log instead of running")
    p.add_argument("--fire-day", type=int, default=0, help="god: set a random house on fire on this day")
    p.add_argument("--models", default=None,
                   help="LLM agents instead of bots: comma-separated OpenRouter model ids cycled over agents, "
                        "'default' for llm.DEFAULT_MODEL, or 'stub' to test the LLM pipeline without a key")
    p.add_argument("--agents", type=int, default=0, help="use only the first N villagers")
    p.add_argument("--mode", default=None, help="economy mode (aivillage/modes.py): "
                                                "standard, peaceful, scarcity, debt, gold_rush, lawless")
    a = p.parse_args(argv)

    if a.replay:
        w = replay(a.replay)
        print(f"replay OK: {w.tick} ticks, final hash {w.hash()}")
        return 0
    from . import runconfig
    try:
        rc = runconfig.load(a.config) if a.config else runconfig.RunConfig()
    except runconfig.ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    for key in ("days", "seed", "log", "mode"):
        if getattr(a, key) is not None:
            setattr(rc, key, getattr(a, key))
    if rc.mode not in modes.MODES:
        print(f"unknown mode '{rc.mode}' (have: {', '.join(modes.MODES)})", file=sys.stderr)
        return 2
    override = rc.world_override()
    if a.agents:
        from .config import DEFAULT_CONFIG
        override["agents"] = (override.get("agents") or DEFAULT_CONFIG["agents"])[: a.agents]
    world = engine.new_world(override)
    names = sorted(world.agents)
    brains = rc.brains(names)
    # Old-style flags cycle over agents and override the file.
    if a.models:
        models = a.models.split(",")
        brains = {n: ("model", models[i % len(models)]) for i, n in enumerate(names)}
    elif a.bots:
        kinds = a.bots.split(",")
        brains = {n: ("bot", kinds[i % len(kinds)]) for i, n in enumerate(names)}
    agents = llm_agents(world, {n: m for n, (kind, m) in brains.items() if kind == "model"})
    bots = {n: BOT_TYPES[k](n, rc.seed) for n, (kind, k) in brains.items() if kind == "bot"}

    def decide(name: str, obs: dict) -> dict:
        return agents[name].decide(obs) if name in agents else bots[name].decide(obs)

    god = rc.god_script(world.config)
    if a.fire_day:
        hours = world.config["day_end_hour"] - world.config["day_start_hour"]
        victim = names[rc.seed % len(names)]
        god.setdefault((a.fire_day - 1) * hours + 4, []).append({"name": "fire", "args": {"person": victim}})
    on_night = (lambda w, day: night_reflection(w, agents, day)) if agents else None
    stats = run(world, decide, rc.days, god, rc.log, on_night=on_night)
    print(summary(world, stats))
    for name, ag in agents.items():
        u = ag.usage
        print(f"  {name:8} {ag.client.model:30} calls={u.calls} fail={u.failures} "
              f"tokens={u.prompt_tokens}+{u.completion_tokens} cost=${u.cost_usd:.4f}")
    return 0


def night_reflection(world: World, agents: dict, day: int) -> dict:
    """Living LLM agents write a diary entry and update what they think of people."""
    from .llm import reflect_all
    return reflect_all({n: ag for n, ag in agents.items() if world.agents[n].status != "dead"}, day)


def llm_agents(world: World, models: list[str] | dict[str, str]) -> dict:
    """models: ids cycled over agents, or agent name -> id. An id is an OpenRouter model,
    'default' (llm.DEFAULT_MODEL) or 'stub'."""
    if isinstance(models, list):
        models = {n: models[i % len(models)] for i, n in enumerate(sorted(world.agents))}
    if not models:
        return {}
    from .llm import DEFAULT_MODEL, LLMAgent, OpenRouterClient, StubClient, world_facts
    off = frozenset(world.config.get("disabled_actions") or ())
    facts = world_facts(world.config)
    out = {}
    for name, m in models.items():
        m = DEFAULT_MODEL if m == "default" else m
        client = StubClient(name) if m == "stub" else OpenRouterClient(m)
        out[name] = LLMAgent(name, world.agents[name].profession, client, facts=facts, disabled_actions=off)
    return out


if __name__ == "__main__":
    sys.exit(main())
