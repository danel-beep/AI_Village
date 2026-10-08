"""Run a simulation, write a replayable JSONL log, and replay logs.

    python -m aivillage.run --days 10 --bots worker,worker,thief,worker,random --log runs/demo.jsonl
    python -m aivillage.run --config configs/example.yaml
    python -m aivillage.run --replay runs/demo.jsonl
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import sys
import random
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable

from . import animals, clock, construction, crafting, crises, engine, explore, graves, hire, honors, labor, land, mapgen, merchant, modes, plots, pricing, remote, settle, talk, threats, tiles, transport, works
from .bots import BOT_TYPES
from .invariants import check
from .logio import ViewDeltas, read_log  # noqa: F401  (read_log: the public reader, re-exported)
from .state import World

LOG_VERSION = 2  # 2: every World field in the dict and hash, `preset` in the config (2026-10-08)


@functools.lru_cache(maxsize=1)
def code_version() -> dict:
    """Which code played a log: the git commit when run from a checkout (None from the launcher's download) and a
    hash of the package sources, which also tells two downloads apart. Rules and prompts live in the code."""
    pkg = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in sorted(pkg.rglob("*.py")):
        h.update(p.relative_to(pkg).as_posix().encode() + b"\0" + p.read_bytes())
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pkg, capture_output=True, text=True,
                                timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {"commit": commit, "source": h.hexdigest()[:16]}

# decide(name, observation) -> decision
DecideFn = Callable[[str, dict], dict]


class JsonlLog:
    def __init__(self, path: str | Path | None, append: bool = False):
        self.f = None
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.f = open(path, "a" if append else "w", encoding="utf-8")
        self.deltas = ViewDeltas()  # tick views as deltas (aivillage/logio.py); an appended run starts whole

    def write(self, rec: dict) -> str:
        """Write one record (a tick view as a delta); returns the whole record's JSON line, without the newline."""
        line = json.dumps(rec, ensure_ascii=False)
        if self.f:
            self.f.write(json.dumps(self.deltas.compact(rec), ensure_ascii=False) + "\n")
            self.f.flush()  # a problem report can zip the log mid-run
        return line

    def close(self) -> None:
        if self.f:
            self.f.close()


def run(world: World, decide: DecideFn, days: int, god_script: dict[int, list] | None = None,
        log_path: str | Path | None = None, check_every_tick: bool = True,
        on_tick: Callable[[World, list], None] | None = None,
        on_night: Callable[[World, int], dict] | None = None,
        on_record: Callable[[dict], None] | None = None, meta: dict | None = None,
        max_cost: float = 0.0, checkpoint: Callable[[World], None] | None = None,
        resume_header: dict | None = None) -> dict:
    """Drive the world for `days` days. Returns summary stats.

    `on_night(world, day)` runs after each day ends; whatever it returns is logged as a `diary` record
    (outside the engine, so replay ignores it). `on_record` sees every log record as it is written
    (the live server streams them). `meta` goes into the header; who plays whom (`brains`: villager -> model
    id or "bot:<kind>") is read from `decide.agents` / `decide.bots` when not given, and LLM token use and cost
    are logged as a `usage` record after every night and at the end (aivillage/scorecard.py reads both).
    `max_cost` (USD, 0 = no limit): stop early once the LLM villagers together have spent this much.
    `checkpoint(world)` runs before every tick, when the world, the log and the villagers' memory agree
    (aivillage/saves.py saves there); it may raise to stop the run. `resume_header`: the world was loaded from a
    save (aivillage/saves.py), so append to the log at `log_path` and only hand its old header to `on_record`."""
    log = JsonlLog(log_path, append=resume_header is not None)
    meta = {"brains": brains_of(decide), **villains_meta(decide), **(meta or {})}
    llm = getattr(decide, "agents", None) or {}

    def emit(rec: dict) -> None:
        line = log.write(rec)
        if on_record:  # a copy read back from the line: `view` holds live world containers that change later
            on_record(json.loads(line))

    if resume_header is not None:
        if on_record:
            on_record(resume_header)
    else:
        emit({"type": "header", "version": LOG_VERSION, "config": world.config, "hash": world.hash(),
              "code": code_version(), **meta})
    stats: Counter = Counter()
    end_day = world.day + days
    try:
        while world.day < end_day:
            if checkpoint:
                checkpoint(world)
            asked = engine.waiting_agents(world)
            observations = {name: engine.observe(world, name) for name in asked}
            turns = talk.groups(world, asked)
            decisions = decide_all(world, decide, asked, observations, turns)
            god = (god_script or {}).get(world.tick, [])
            tick, day = world.tick, world.day
            events = engine.step(world, decisions, god, turns)
            if check_every_tick:
                check(world)
            for ev in events:
                stats[ev.kind] += 1
            stats["llm_calls"] += len(asked)
            emit({"type": "tick", "tick": tick, "asked": asked, "decisions": decisions, "god": god,
                  **({"talk": turns} if turns else {}),
                  "events": [asdict(e) for e in events], "hash": world.hash(), "view": view(world)})
            if on_tick:
                on_tick(world, events)
            if on_night and world.day != day:
                entries = on_night(world, day)
                if entries:
                    emit({"type": "diary", "day": day, "entries": entries})
            if llm and world.day != day:
                emit(usage_record(llm, world.tick))
            if llm and max_cost and sum(ag.usage.cost_usd for ag in llm.values()) >= max_cost:
                stats["stopped_at_cost_cap"] = 1
                emit({"type": "stop", "tick": world.tick, "reason": f"cost cap ${max_cost:g} reached"})
                break
    finally:
        if llm:
            emit(usage_record(llm, world.tick))
        log.close()
    return dict(stats)


def decide_all(world: World, decide: DecideFn, asked: list[str], observations: dict[str, dict],
               turns: list[list[str]]) -> dict[str, dict]:
    """Ask every waiting villager. Different places think at the same time, so a slow model does not slow
    the others down; at one place villagers take turns when talk.turn_taking is on (`turns`, talk.py), each
    hearing the earlier ones (`just_said`)."""
    taking_turns = {n for g in turns for n in g}
    jobs = [[[n]] for n in asked if n not in taking_turns] + [talk.waves(world, g) for g in turns]

    def take_turns(waves: list[list[str]]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for wave in waves:
            earlier = list(out.items())
            for n in wave:
                heard = talk.just_said(n, earlier)
                if heard:
                    observations[n]["just_said"] = heard
            if len(wave) == 1:
                out[wave[0]] = decide(wave[0], observations[wave[0]])
            else:
                with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                    out.update(zip(wave, pool.map(lambda n: decide(n, observations[n]), wave)))
        return out

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        for part in pool.map(take_turns, jobs):
            results.update(part)
    return {n: results[n] for n in asked}


def hidden_actions(cfg: dict) -> frozenset[str]:
    """Actions the villagers' prompt leaves out under this config (switched off, or their mechanic is off)."""
    return frozenset(cfg.get("disabled_actions") or ()) | animals.hidden_actions(cfg) | transport.hidden_actions(cfg) \
        | hire.hidden_actions(cfg) | construction.hidden_actions(cfg) | land.hidden_actions(cfg) \
        | settle.hidden_actions(cfg) | crafting.hidden_actions(cfg) | merchant.hidden_actions(cfg)


def brains_of(decide: DecideFn) -> dict[str, str]:
    """{villager: model id or "bot:<kind>"} from a decider built by `llm_agents` / `bots_decider` / `main`."""
    kinds = {cls: k for k, cls in BOT_TYPES.items()}
    out = {n: f"bot:{kinds.get(type(b), type(b).__name__)}" for n, b in (getattr(decide, "bots", None) or {}).items()}
    out.update({n: getattr(ag.client, "model", "?") for n, ag in (getattr(decide, "agents", None) or {}).items()})
    return dict(sorted(out.items()))


def villains_meta(decide: DecideFn) -> dict:
    """{"villains": {villager: model}} for the log header when any LLM villager has the villain character, else {}."""
    from .llm import VILLAIN_CHARACTER
    bad = {n: getattr(ag.client, "model", "?") for n, ag in (getattr(decide, "agents", None) or {}).items()
           if getattr(ag, "character", "") == VILLAIN_CHARACTER}
    return {"villains": dict(sorted(bad.items()))} if bad else {}


def usage_record(agents: dict, tick: int) -> dict:
    """Cumulative token use and cost per LLM villager (the last `usage` record in a log is the total)."""
    return {"type": "usage", "tick": tick,
            "agents": {n: {"model": getattr(ag.client, "model", "?"), "calls": ag.usage.calls,
                           "failures": ag.usage.failures, "prompt_tokens": ag.usage.prompt_tokens,
                           "cached_tokens": ag.usage.cached_tokens,
                           "completion_tokens": ag.usage.completion_tokens, "cost_usd": round(ag.usage.cost_usd, 6),
                           "by_model": dict(ag.usage.by_model)} for n, ag in sorted(agents.items())}}


def view(world: World) -> dict:
    """Small snapshot for the viewer (not used by replay). Time is the moment after the tick;
    `busy` = game minutes until the villager acts again (0: free next tick), `task` = move | work | None."""
    tm = clock.tick_minutes(world.config)
    return {"day": world.day, "hour": world.hour, "minute": world.minute, "tick_minutes": tm,
            "agents": {a.name: {"location": a.location, "status": a.status, "asleep": a.asleep,
                                "satiety": a.satiety, "health": a.health, "coins": a.coins,
                                "profession": a.profession, "inventory": a.inventory,
                                "busy": max(0, a.busy_until - world.tick) * tm,
                                "task": (a.task or {}).get("kind"), "hospital_stays": a.hospital_stays}
                       for a in world.agents.values()},
            # chests for the hero page's property list (viewer/hero.js)
            "chests": {c.owner: {"coins": c.coins, "items": c.items, "locked": c.locked} for c in world.chests.values()},
            "kin": {"feelings": world.kin.feelings, "couples": [m.spouses for m in world.kin.marriages.values()]},
            # reputation.py: each villager's own tally of others and the rumors they heard (non-empty only)
            "social": {a.name: {"reputation": a.reputation, "rumors": a.rumors}
                       for a in world.agents.values() if a.reputation or a.rumors},
            "plots": plots.view(world),
            "crises": crises.view(world),  # active world crises (crises.py)
            "threats": threats.view(world),  # raids, beasts, travelers here or warned (threats.py)
            **({"merchant": m} if (m := merchant.view(world)) else {}),  # merchant.py: here and his stock left
            **animals.view(world),  # animals.py: herds per place and open hunt parties (animals on)
            **transport.view(world),  # transport.py: riding and pack animals, wild ones per place (transport on)
            "graves": graves.view(world),  # graves.py: who is buried where
            **({"labor": lab} if (lab := labor.view(world)) else {}),  # labor.py: skills, trader's day
            "mayor": world.governance.mayor, "treasury": world.governance.coins,
            "treasury_missing": world.governance.hidden,  # embezzled, not found yet (governance.py)
            "works": works.view(world),  # village structures and open projects (works.py)
            **construction.view(world),  # building sites and common buildings (construction.py)
            **honors.view(world),  # honors.py: the honor board (notes and titles), when not empty
            **hire.view(world),  # hire.py: hired outsiders and where they are, open jobs (hiring on)
            "fires": list(world.fires), "locations": {l.id: l.name for l in world.locations.values()},
            "fire_info": {f.location: {"water_needed": f.water_needed, "hours_left": f.ticks_left, "hours": f.hours}
                          for f in world.fires.values()},
            **({"known": k} if (k := explore.view(world)) is not None else {}),  # explore.py: places someone knows
            **explore.view_by(world),  # explore.py: what each villager knows, on ticks where it changed
            **settle.view(world),  # settle.py: house sites taken, trails walked (camp start)
            "map": {l.id: tiles.snapshot(l, world.config["locations"][l.id]["resources"])
                    for l in world.locations.values() if l.slots},
            # for the viewer's object panels (viewer/inspect.js): the square's order board, trader prices
            "orders": [{"id": o.id, "needs": o.needs, "reward": o.reward, "until": o.expires_day}
                       for o in world.orders.values() if o.status == "open"],
            "market": market_prices(world)}


def market_prices(world: World) -> dict:
    """What the NPC trader charges ("buy") and pays ("sell") now, same as actions._price (pricing.py)."""
    return {item: [pricing.price(world, item, "buy"), pricing.price(world, item, "sell")]
            for item, info in world.config["items"].items() if info.get("tradable", True)}


def replay(path: str | Path) -> World:
    """Re-run a log through the engine and verify every tick's hash. Raises on divergence."""
    recs = read_log(path)
    header = next(recs)
    assert header["type"] == "header" and header["version"] == LOG_VERSION
    world = start_of(header)
    if world.hash() != header["hash"]:
        raise AssertionError("initial world differs (engine or config changed)")
    for rec in recs:
        if rec.get("type") != "tick":
            continue
        for name in rec["asked"]:
            engine.observe(world, name)
        engine.step(world, rec["decisions"], rec["god"], rec.get("talk"))
        if world.hash() != rec["hash"]:
            raise AssertionError(f"replay diverged at tick {rec['tick']}")
    return world


def start_of(header: dict) -> World:
    """The world a log starts from: built from its config, or given whole (a scenario run, aivillage/scenario.py)."""
    return World.from_dict(header["start"]) if "start" in header else engine.new_world(header["config"])


def seat_order(names, seed: int) -> list[str]:
    """Villagers in a seeded random order, for handing out a cycled list of models or bot kinds: by name
    order the alphabetically first villager (often Boris, who is in every village) would always get the first one."""
    order = sorted(names)
    random.Random(f"{seed}:seats").shuffle(order)
    return order


def villains_of(models: dict[str, str], per_model: int, seed: int) -> dict[str, str]:
    """{villager: model} of the villains: `per_model` villagers of every model (own AIs aside), drawn from the seed,
    so each model gets the same number and no seat (Boris included) is fixed."""
    out: dict[str, str] = {}
    for m in sorted(set(models.values()) - {"mcp"}):
        names = sorted(n for n, mm in models.items() if mm == m)
        random.Random(f"{seed}:villains:{m}").shuffle(names)
        out.update({n: m for n in names[:max(0, per_model)]})
    return dict(sorted(out.items()))


def bots_decider(world: World, kinds: list[str], seed: int) -> DecideFn:
    names = seat_order(world.agents, seed)
    bots = {n: BOT_TYPES[kinds[i % len(kinds)]](n, seed) for i, n in enumerate(names)}

    def decide(name: str, obs: dict) -> dict:
        return bots[name].decide(obs)
    decide.bots = bots  # brains_of() names them in the log header
    return decide


def summary(world: World, stats: dict) -> str:
    lines = [f"Day {world.day}, tick {world.tick}. Model calls that would be made: {stats.get('llm_calls', 0)}"]
    for a in world.agents.values():
        chest = world.chests[f"chest_{a.name}"]
        lines.append(f"  {a.name:8} {a.profession:10} {a.status:8} hp={a.health:3} food={a.satiety:3} "
                     f"coins={a.coins:4} chest_coins={chest.coins:3} inv={a.inventory}")
    keys = ["trade", "give", "steal", "witness", "lend", "promise", "repay", "default", "debt_collected", "debt_seized",
            "order_done", "contribute", "project_done", "fire_out", "house_burned", "hospital", "evicted", "error"]
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
    p.add_argument("--fallback", default=None,
                   help="comma-separated backup OpenRouter models used when the main one is rate-limited or down "
                        "(default: env AIVILLAGE_FALLBACK_MODELS)")
    p.add_argument("--agents", type=int, default=0,
                   help="number of villagers: the first N, or more with generated names (resources scale up)")
    p.add_argument("--preset", default=None, help="preset on top of «С нуля» (presets/*.yaml): "
                                                  + ", ".join(modes.PRESETS))
    p.add_argument("--tick-minutes", type=int, default=None, choices=clock.ALLOWED,
                   help=f"game minutes per tick (default {clock.RUN_DEFAULT}; 60 = the old hourly turns)")
    p.add_argument("--max-cost", type=float, default=float(os.environ.get("AIVILLAGE_MAX_COST") or 0),
                   help="stop the run once LLM villagers have spent this many USD (default: env AIVILLAGE_MAX_COST, "
                        "0 = no limit)")
    mapgen.add_args(p)
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
    for key in ("days", "seed", "log", "preset"):
        if getattr(a, key) is not None:
            setattr(rc, key, getattr(a, key))
    if rc.preset not in modes.PRESETS:
        print(f"unknown preset '{rc.preset}' (have: {', '.join(modes.PRESETS)})", file=sys.stderr)
        return 2
    override = rc.world_override()
    if a.agents:
        override["population"] = {**(override.get("population") or {}), "size": a.agents}
    with_tick_minutes(override, a.tick_minutes)
    world = engine.new_world(mapgen.for_run(override, a.fixed_map, a.unfairness, a.map_size))
    names = sorted(world.agents)
    brains = rc.brains(names)
    seats = seat_order(names, rc.seed)
    # Old-style flags cycle over agents and override the file.
    if a.models:
        models = a.models.split(",")
        brains = {n: ("model", models[i % len(models)]) for i, n in enumerate(seats)}
    elif a.bots:
        kinds = a.bots.split(",")
        brains = {n: ("bot", kinds[i % len(kinds)]) for i, n in enumerate(seats)}
    fallbacks = a.fallback.split(",") if a.fallback else (rc.fallback_models or None)
    agents = llm_agents(world, {n: m for n, (kind, m) in brains.items() if kind == "model"}, fallbacks)
    bots = {n: BOT_TYPES[k](n, rc.seed) for n, (kind, k) in brains.items() if kind == "bot"}

    def decide(name: str, obs: dict) -> dict:
        return agents[name].decide(obs) if name in agents else bots[name].decide(obs)
    decide.agents, decide.bots = agents, bots

    god = rc.god_script(world.config)
    if a.fire_day:
        victim = names[rc.seed % len(names)]
        fire_at = clock.tick_of(world.config, a.fire_day, world.config["day_start_hour"] + 4)
        god.setdefault(fire_at, []).append({"name": "fire", "args": {"person": victim}})
    on_night = (lambda w, day: night_reflection(w, agents, day)) if agents else None
    stats = run(world, decide, rc.days, god, rc.log, on_night=on_night, max_cost=a.max_cost)
    print(summary(world, stats))
    for name, ag in agents.items():
        u = ag.usage
        print(f"  {name:8} {ag.client.model:30} calls={u.calls} fail={u.failures} "
              f"tokens={u.prompt_tokens}+{u.completion_tokens} cached={u.cached_tokens} cost=${u.cost_usd:.4f}"
              + (f" answered_by={u.by_model}" if len(u.by_model) > 1 else ""))
    from .llm import _GATES
    for model, g in _GATES.items():
        print(f"  queue {model}: {g.calls} calls, max {g.limit} at once, {g.rate_limited} rate-limited, "
              f"{g.paced} paused before the limit, {g.waited:.0f}s waiting")
    if rc.log:
        from . import scorecard
        print(f"  scorecard: {scorecard.write(rc.log)}")
        from . import session  # the same end-of-session summary the app saves (aivillage/session.py)
        session.save(rc.log, ended_by="finished", days_planned=rc.days)
        print(f"  session: {session.paths(rc.log)['html']}")
    return 0


def with_tick_minutes(override: dict, flag: int | None) -> dict:
    """Real runs think in quarter hours unless the flag or the run config's `world:` says otherwise."""
    if flag is not None:
        override["tick_minutes"] = flag
    override.setdefault("tick_minutes", clock.RUN_DEFAULT)
    return override


def night_reflection(world: World, agents: dict, day: int) -> dict:
    """Living LLM agents write a diary entry and update what they think of people."""
    from .llm import reflect_all
    return reflect_all({n: ag for n, ag in agents.items() if world.agents[n].status != "dead"}, day)


def llm_agents(world: World, models: list[str] | dict[str, str], fallbacks: list[str] | None = None) -> dict:
    """models: ids cycled over agents, or agent name -> id. An id is an OpenRouter model,
    'default' (saved model, else llm.DEFAULT_MODEL), 'stub' or 'mcp' (the player's own AI, aivillage/remote.py);
    llm.make_client picks the provider.
    `fallbacks`: backup models (None = env AIVILLAGE_FALLBACK_MODELS)."""
    if isinstance(models, list):
        seats = seat_order(world.agents, world.config["seed"])
        models = {n: models[i % len(models)] for i, n in enumerate(seats)}
    if not models:
        return {}
    from .llm import VILLAIN_CHARACTER, LLMAgent, StubClient, character_text, make_client, world_facts
    off = hidden_actions(world.config)
    facts = world_facts(world.config)
    chars = {a["name"]: a.get("character") for a in world.config["agents"]}
    mode = world.config.get("characters", "default")
    own = world.config.get("own_ai") or {}
    if "mcp" in models.values():  # own AIs over MCP (aivillage/remote.py): new links and new consent every time
        remote.HUB.reset(wait_minutes=own.get("wait_minutes", 5), style=own.get("style", "owner"),
                         info={"villagers": len(world.agents)})
        remote.HUB.world = world  # the lobby's table: who is alive and how rich
    villains = villains_of(models, int(world.config.get("villains") or 0), world.config["seed"])
    out = {}
    for name, m in models.items():
        character = character_text(chars.get(name), mode=mode, seed=world.config["seed"], name=name)
        if name in villains:
            character = VILLAIN_CHARACTER
        if m == "mcp":
            client = remote.RemoteClient(remote.HUB.add(name, world.agents[name].profession))
            if remote.HUB.style == "owner":
                character = remote.OWNER_CHARACTER
            elif remote.HUB.style == "model":  # the tournament: nothing of the host's, the AI is itself
                character = remote.MODEL_CHARACTER
        else:
            client = StubClient(name) if m == "stub" else make_client(m, fallbacks=fallbacks)
        out[name] = LLMAgent(name, world.agents[name].profession, client, facts=facts,
                             facts_cfg=world.config if world.config.get("llm_facts", "open") == "open" else None,
                             disabled_actions=off,
                             character=character,
                             own_goals=bool(world.config.get("own_goals", True)),
                             memory=world.config.get("llm_memory", "day"),
                             obs_mode=world.config.get("llm_obs", "changes"))
    return out


if __name__ == "__main__":
    sys.exit(main())
