"""Scenarios: start a village at a chosen moment, with chosen memory, instead of playing from day 1.

A scenario (`scenarios/<name>.yaml`) is a cheap, repeatable test of one situation (a hungry villager asks for
food, two villagers build a smithy together, someone does not pay the tax). It says:

- `config`: an ordinary run config (aivillage/runconfig.py: mode, villagers, seed, world overrides);
- `warmup`: optionally play bots for N days first, so the world is lived-in (fields worked, houses built);
- `world` / `villagers`: edits on top of that moment (satiety, items, coins, place, chest, mayor, laws, tax
  bills, building sites, feelings) and each villager's memory (about_me, wants, plan, notes, people, diary);
- `play`: how long to play from there, which villagers are AI (the others stay bots), the model, a cost cap;
- `expect` / `watch`: what to look for in the log afterwards (passed or not / just counted).

The edits are made by the scenario, not by the engine, so the log of a scenario run starts from that moment:
its header carries the whole starting world (`start`), and `run.replay()` begins there. Every tick after
it is played and hash-checked as usual. Edited holdings are booked in the ledger, so invariants hold.

    python -m aivillage.scenario list
    python -m aivillage.scenario run hungry_neighbor --ai Anna,Boris --log runs/hungry.jsonl
    python -m aivillage.scenario run smithy_together --model stub     # the LLM pipeline without a key
The app's start screen has a «🧪 Сценарии» block (viewer/scenarios.js, POST /api/scenario).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import construction, engine, family, mapgen, runconfig
from .bots import BOT_TYPES
from .invariants import check, holdings
from .engine import rng_for
from .ops import Ctx
from .state import Debt, World

DIR = Path(__file__).resolve().parent.parent / "scenarios"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Warmup(Strict):
    days: int = Field(default=0, ge=0, le=30)
    bots: str = "builder"  # bot kind everyone plays during the warmup


class Memory(Strict):
    about_me: str | None = None
    wants: str | None = None
    plan: str | None = None
    notes: str | None = None
    people: dict[str, str] = Field(default_factory=dict)
    diary: list[str] = Field(default_factory=list)  # oldest first; the last one is shown in every prompt
    recent: list[str] = Field(default_factory=list)


class Villager(Strict):
    satiety: int | None = None
    health: int | None = None
    coins: int | None = None
    location: str | None = None  # a location id; "home" = their own house
    inventory: dict[str, int] | None = None  # replaces the pockets
    add: dict[str, int] = Field(default_factory=dict)  # added to the pockets
    chest: dict[str, int] | None = None  # replaces the chest; key "coins" = coins in it
    feelings: dict[str, int] = Field(default_factory=dict)  # what this villager feels about others
    memory: Memory | None = None  # AI villagers only


class Site(Strict):
    kind: str
    by: str  # who started it; the site is opened where they stand (move them with `location` first)
    supplied: bool = False  # all materials already brought (by the starter)


class Bill(Strict):
    who: str
    coins: int = Field(ge=1)
    kind: Literal["tax", "fine"] = "tax"
    days_late: int = Field(default=1, ge=0)  # 0 = due today


class WorldEdits(Strict):
    mayor: str | None = None
    treasury: int | None = Field(default=None, ge=0)
    laws: dict[str, int] = Field(default_factory=dict)
    sites: list[Site] = Field(default_factory=list)
    bills: list[Bill] = Field(default_factory=list)


class Play(Strict):
    days: int = Field(default=1, ge=1, le=30)
    ai: list[str] | Literal["all"] = "all"  # AI villagers; everyone else is a bot
    model: str = "default"  # model id for the AI villagers, "stub" = offline
    bots: str = "worker"
    max_cost: float = Field(default=0.25, ge=0)  # USD, 0 = no cap


class Check(Strict):
    title: str = ""
    kind: str | list[str] | None = None
    actor: str | None = None
    to: str | None = None  # in the event's `to` or its trade `partner`
    who: str | None = None  # actor or `to`
    text: str | None = None  # regex on the event text, case-insensitive
    data: dict = Field(default_factory=dict)  # subset of the event's data
    min: int = Field(default=1, ge=1)
    actors: int = Field(default=1, ge=1)  # at least this many different actors
    ai: bool = False  # only events done by AI villagers count (bots helping do not)
    any: list["Check"] = Field(default_factory=list)  # passes if one of these passes


class Scenario(Strict):
    title: str
    about: str = ""  # what is being tested, in plain words (shown in the app)
    config: dict = Field(default_factory=dict)  # run config (runconfig.RunConfig); days/log come from `play`
    warmup: Warmup = Field(default_factory=Warmup)
    world: WorldEdits = Field(default_factory=WorldEdits)
    villagers: dict[str, Villager] = Field(default_factory=dict)
    play: Play = Field(default_factory=Play)
    expect: list[Check] = Field(default_factory=list)
    watch: list[Check] = Field(default_factory=list)


class ScenarioError(ValueError):
    pass


# --- loading ---

def path_of(name: str, folder: str | Path | None = None) -> Path:
    p = Path(name)
    if p.suffix in (".yaml", ".yml") and p.is_file():
        return p
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ScenarioError(f"no scenario '{name}'")
    p = Path(folder or DIR) / f"{name}.yaml"
    if not p.is_file():
        raise ScenarioError(f"no scenario '{name}' in {p.parent}")
    return p


def load(name: str, folder: str | Path | None = None) -> Scenario:
    p = path_of(name, folder)
    try:
        return parse(yaml.safe_load(p.read_text(encoding="utf-8")) or {}, p.name)
    except yaml.YAMLError as e:
        raise ScenarioError(f"{p.name}: {e}") from None


def parse(data: dict, source: str = "scenario") -> Scenario:
    try:
        return Scenario.model_validate(data)
    except ValidationError as e:
        msgs = "\n".join(f"  {'.'.join(map(str, x['loc'])) or '(top)'}: {x['msg']}" for x in e.errors())
        raise ScenarioError(f"{source} is invalid:\n{msgs}") from None


def listing(folder: str | Path | None = None) -> list[dict]:
    out = []
    for p in sorted(Path(folder or DIR).glob("*.yaml")):
        try:
            s = load(p.stem, folder)
        except ScenarioError:
            continue
        out.append({"name": p.stem, "title": s.title, "about": s.about, "days": s.play.days,
                    "warmup_days": s.warmup.days, "ai": s.play.ai, "mode": s.config.get("mode")})
    return out


# --- building the starting moment ---

def start_world(scn: Scenario) -> World:
    """The world at the scenario's moment: config, warmup with bots, then the edits."""
    try:
        rc = runconfig.parse({**scn.config, "days": 1}, "config")
    except runconfig.ConfigError as e:
        raise ScenarioError(str(e)) from None
    from .run import bots_decider, run, with_tick_minutes
    world = engine.new_world(mapgen.for_run(with_tick_minutes(rc.world_override(), None)))
    if scn.warmup.days:
        if scn.warmup.bots not in BOT_TYPES:
            raise ScenarioError(f"warmup.bots: unknown bot '{scn.warmup.bots}' (have: {', '.join(BOT_TYPES)})")
        run(world, bots_decider(world, [scn.warmup.bots], rc.seed), scn.warmup.days, rc.god_script(world.config))
    edit(world, scn)
    return world


def _name(world: World, name: str, where: str) -> str:
    if name not in world.agents:
        raise ScenarioError(f"{where}: no villager '{name}' (have: {', '.join(sorted(world.agents))})")
    return name


def _items(world: World, items: dict[str, int], where: str) -> dict[str, int]:
    bad = [k for k in items if k != "coins" and k not in world.config["items"]]
    if bad:
        raise ScenarioError(f"{where}: unknown items {bad}")
    if any(v < 0 for v in items.values()):
        raise ScenarioError(f"{where}: negative amounts")
    return {k: v for k, v in items.items() if v}


def edit(world: World, scn: Scenario) -> None:
    """Apply `villagers` and `world` edits, then book whatever appeared or vanished in the ledger."""
    cfg = world.config
    for name, v in scn.villagers.items():
        a = world.agents[_name(world, name, "villagers")]
        if v.location is not None:
            loc = a.home if v.location == "home" else v.location
            if loc not in world.locations:
                raise ScenarioError(f"villagers.{name}.location: no place '{v.location}'")
            a.location, a.task, a.busy_until = loc, None, world.tick
        if v.satiety is not None:
            a.satiety = max(0, min(cfg["satiety_max"], v.satiety))
        if v.health is not None:
            a.health = max(1, min(cfg["health_max"], v.health))
        if v.coins is not None:
            a.coins = max(0, v.coins)
        if v.inventory is not None:
            a.inventory = _items(world, v.inventory, f"villagers.{name}.inventory")
        for k, n in _items(world, v.add, f"villagers.{name}.add").items():
            a.inventory[k] = a.inventory.get(k, 0) + n
        if v.chest is not None:
            items = _items(world, v.chest, f"villagers.{name}.chest")
            chest = world.chests[f"chest_{name}"]
            chest.coins = items.pop("coins", 0)
            chest.items = items
        for other, n in v.feelings.items():
            _name(world, other, f"villagers.{name}.feelings")
            family.change(world, name, other, n - family.feeling(world, name, other))
    g, e = world.governance, scn.world
    if e.mayor is not None:
        g.mayor = _name(world, e.mayor, "world.mayor")
    if e.treasury is not None:
        g.coins = e.treasury
    g.laws.update(e.laws)
    for s in e.sites:
        a = world.agents[_name(world, s.by, "world.sites")]
        if not construction.enabled(cfg):
            raise ScenarioError("world.sites: building sites are off in this mode")
        ctx = Ctx(world, rng_for(world, "scenario"))
        try:
            construction.start_building(ctx, a, construction.StartArgs(kind=s.kind))
        except Exception as ex:
            raise ScenarioError(f"world.sites: {s.by} cannot start a {s.kind} at {a.location}: {ex}") from None
        site = list(construction.sites(world).values())[-1]
        if s.supplied:
            site["given"] = dict(site["needs"])
            site["givers"] = {s.by: sum(site["needs"].values())}
    for b in e.bills:
        _name(world, b.who, "world.bills")
        from .debts import TREASURY
        due = world.day - b.days_late
        d = Debt(world.new_id("debt"), TREASURY, b.who, b.coins, due, status="defaulted" if b.days_late else "open",
                 kind=b.kind, note=f"day {max(1, due - 2)}", day=max(1, due - 2))
        world.debts[d.id] = d
    # The scenario is a god: what it added or took is booked as minted or burned, so conservation holds.
    world.ledger = {k: v for k, v in holdings(world).items() if v}
    check(world)


def brains(world: World, scn: Scenario, *, ai: list[str] | None = None, model: str | None = None,
           bots: str | None = None):
    """`decide` (with .agents / .bots like run.main builds it) and `on_night` for the scenario's villagers."""
    from .run import llm_agents, night_reflection
    play = scn.play
    names = sorted(world.agents)
    chosen = ai if ai is not None else (names if play.ai == "all" else list(play.ai))
    for n in chosen:
        _name(world, n, "play.ai")
    kind = bots or play.bots
    if kind not in BOT_TYPES:
        raise ScenarioError(f"play.bots: unknown bot '{kind}' (have: {', '.join(BOT_TYPES)})")
    agents = llm_agents(world, {n: model or play.model for n in chosen})
    seed = world.config["seed"]
    bot = {n: BOT_TYPES[kind](n, seed) for n in names if n not in agents}
    for name, v in scn.villagers.items():
        m = v.memory
        if m is None or name not in agents:
            continue
        ag = agents[name]
        for f in ("about_me", "wants", "plan", "notes"):
            if getattr(m, f) is not None:
                setattr(ag, f, getattr(m, f))
        if m.about_me or m.wants or m.plan:
            ag.introduced = True  # its own words are given: no INTRO call before the first turn
        ag.people.update(m.people)
        ag.recent = list(m.recent)
        first = world.day - len(m.diary)
        ag.diary = [{"day": first + i, "text": t} for i, t in enumerate(m.diary)]

    def decide(name: str, obs: dict) -> dict:
        return agents[name].decide(obs) if name in agents else bot[name].decide(obs)
    decide.agents, decide.bots = agents, bot
    on_night = (lambda w, day: night_reflection(w, agents, day)) if agents else None
    return decide, on_night


def header_meta(world: World, name: str, scn: Scenario) -> dict:
    """Log header fields of a scenario run: the starting world (replay starts there) and the scenario."""
    return {"start": world.to_dict(), "scenario": {"name": name, "title": scn.title, "day": world.day,
                                                    "expect": [c.model_dump(exclude_defaults=True) for c in scn.expect],
                                                    "watch": [c.model_dump(exclude_defaults=True) for c in scn.watch]}}


# --- checking the log ---

def _hits(c: Check, events: list[dict], ai: set[str] | None = None) -> list[dict]:
    kinds = [c.kind] if isinstance(c.kind, str) else c.kind
    rx = re.compile(c.text, re.I) if c.text else None
    out = []
    for ev in events:
        to = list(ev.get("to") or []) + ([ev["data"]["partner"]] if (ev.get("data") or {}).get("partner") else [])
        if kinds and ev["kind"] not in kinds:
            continue
        if c.actor and ev.get("actor") != c.actor:
            continue
        if c.ai and ev.get("actor") not in (ai or set()):
            continue
        if c.to and c.to not in to:
            continue
        if c.who and c.who != ev.get("actor") and c.who not in to:
            continue
        if rx and not rx.search(ev.get("text") or ""):
            continue
        if any((ev.get("data") or {}).get(k) != v for k, v in c.data.items()):
            continue
        out.append(ev)
    return out


def verdict(c: Check, events: list[dict], ai: set[str] | None = None) -> dict:
    """{"title", "ok", "count", "first"}: `first` = "day D HH:MM: text" of the first matching event."""
    if c.any:
        subs = [verdict(s, events, ai) for s in c.any]
        hit = [s for s in subs if s["ok"]]
        firsts = [s for s in subs if s["first"]]
        return {"title": c.title or " or ".join(s["title"] for s in subs), "ok": bool(hit),
                "count": sum(s["count"] for s in subs), "first": min((s["first"] for s in firsts), default=None)}
    hits = _hits(c, events, ai)
    ok = len(hits) >= c.min and len({e.get("actor") for e in hits}) >= c.actors
    first = (f"day {hits[0]['day']} {hits[0]['hour']:02d}:{hits[0].get('minute', 0):02d}: {hits[0]['text']}"
             if hits else None)
    title = c.title or " ".join(str(x) for x in (c.kind, c.actor and f"by {c.actor}", c.to and f"to {c.to}",
                                                   c.who and f"with {c.who}", c.ai and "(AI)") if x)
    return {"title": title, "ok": ok, "count": len(hits), "first": first}


def report(log: str | Path) -> dict:
    """Expect/watch results and the AI villagers' turns of a scenario log."""
    from .run import read_log
    recs = list(read_log(log))
    head = recs[0]
    info = head.get("scenario")
    if not info:
        raise ScenarioError(f"{Path(log).name} is not a scenario run")
    events = [e for r in recs if r.get("type") == "tick" for e in r["events"]]
    ai = {n for n, b in (head.get("brains") or {}).items() if not str(b).startswith("bot:")}
    out = {"name": info["name"], "title": info["title"],
           "expect": [verdict(Check.model_validate(c), events, ai) for c in info.get("expect", [])],
           "watch": [verdict(Check.model_validate(c), events, ai) for c in info.get("watch", [])],
           "kinds": dict(Counter(e["kind"] for e in events).most_common(15)), "turns": {}, "cost": 0.0}
    for r in recs:
        if r.get("type") == "tick":
            for n, d in r["decisions"].items():
                if n in ai:
                    act = d.get("action") or {}
                    line = f"{act.get('name')} {json.dumps(act.get('args') or {}, ensure_ascii=False)}"
                    if d.get("say"):
                        line += f' · says "{d["say"]}"'
                    if d.get("thought"):
                        line += f" · thinks: {d['thought']}"
                    out["turns"].setdefault(n, []).append(f"t{r['tick']}: {line}")
        elif r.get("type") == "usage":
            out["cost"] = round(sum(a.get("cost_usd", 0) for a in r["agents"].values()), 4)
    out["passed"] = all(v["ok"] for v in out["expect"])
    return out


def markdown(rep: dict) -> str:
    lines = [f"# {rep['title']} ({rep['name']})", ""]
    for head, key in (("Ожидаем", "expect"), ("Наблюдаем", "watch")):
        if rep[key]:
            lines.append(f"## {head}")
            for v in rep[key]:
                mark = ("✅" if v["ok"] else "❌") if key == "expect" else "•"
                lines.append(f"- {mark} {v['title']}: {v['count']}" + (f" (первое: {v['first']})" if v["first"] else ""))
            lines.append("")
    lines += [f"Стоимость ИИ: ${rep['cost']}", "", "## События", ", ".join(f"{k} {n}" for k, n in rep["kinds"].items()), ""]
    for n, turns in rep["turns"].items():
        lines += [f"## Ходы {n}", *[f"- {t}" for t in turns], ""]
    return "\n".join(lines)


def write_report(log: str | Path) -> Path:
    """`<log>.scenario.md` next to the log: expect/watch results and the AI villagers' turns."""
    out = Path(log).with_suffix(".scenario.md")
    out.write_text(markdown(report(log)), encoding="utf-8")
    return out


# --- CLI ---

def run_scenario(name: str, *, log: str | Path, ai: list[str] | None = None, model: str | None = None,
                 days: int | None = None, max_cost: float | None = None, folder: str | Path | None = None) -> dict:
    from .run import run
    scn = load(name, folder)
    world = start_world(scn)
    decide, on_night = brains(world, scn, ai=ai, model=model)
    cap = scn.play.max_cost if max_cost is None else max_cost
    stats = run(world, decide, days or scn.play.days, None, log, on_night=on_night, max_cost=cap,
                meta=header_meta(world, Path(name).stem, scn))
    write_report(log)
    return {**report(log), "stats": stats}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Play a scenario: a village started at a chosen moment.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="scenarios in scenarios/")
    r = sub.add_parser("run", help="play a scenario")
    r.add_argument("name", help="scenario name (scenarios/<name>.yaml) or a path to a .yaml")
    r.add_argument("--log", default=None, help="default runs/scenario-<name>.jsonl")
    r.add_argument("--ai", default=None, help="comma-separated AI villagers (default: the scenario's play.ai); "
                                              "'none' = bots only")
    r.add_argument("--model", default=None, help="model for AI villagers ('stub' = offline)")
    r.add_argument("--days", type=int, default=None)
    r.add_argument("--max-cost", type=float, default=None)
    c = sub.add_parser("check", help="expect/watch results of a scenario log")
    c.add_argument("log")
    a = p.parse_args(argv)
    try:
        if a.cmd == "list":
            for s in listing():
                print(f"{s['name']:20} {s['title']} (mode {s['mode']}, warmup {s['warmup_days']} d, play {s['days']} d)")
            return 0
        if a.cmd == "check":
            rep = report(a.log)
        else:
            ai = None if a.ai is None else ([] if a.ai == "none" else a.ai.split(","))
            log = a.log or f"runs/scenario-{Path(a.name).stem}.jsonl"
            rep = run_scenario(a.name, log=log, ai=ai, model=a.model, days=a.days, max_cost=a.max_cost)
            print(f"log: {log}, report: {Path(log).with_suffix('.scenario.md')}")
    except ScenarioError as e:
        print(e, file=sys.stderr)
        return 2
    print(markdown({**rep, "turns": {}}))
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
