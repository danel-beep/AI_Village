"""Scenarios: start a village at a chosen moment, with chosen memory, instead of playing from day 1.

A scenario (`scenarios/<name>.yaml`) is a cheap, repeatable test of one situation (a hungry villager asks for
food, two villagers build a smithy together, someone does not pay the tax). It says:

- `config`: an ordinary run config (aivillage/runconfig.py: mode, villagers, seed, world overrides);
- `warmup`: optionally play bots for N days first, so the world is lived-in (fields worked, houses built);
- `world` / `villagers`: edits on top of that moment (satiety, items, coins, place, chest, mayor, laws, tax
  bills, building sites, feelings) and each villager's memory (about_me, wants, plan, notes, people, diary);
- `play`: how long to play from there, which villagers are AI (the others stay bots), the model, a cost cap;
- `expect` / `watch`: what to look for in the log afterwards (passed or not / just counted).

It can also start from a save instead (`from_save`: a `.save.json` or a zip holding one): the world and every
villager's brain come from that moment, and the edits go on top. An experiment adds `arms` (variants that change one
thing: a character, a model, memory, the world), `play.replicates` and `play.seating` (models on seats, mirrored
between replicates); aivillage/lab.py plays every arm and compares them.

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
import copy
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
import hashlib
import zipfile
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import construction, engine, family, mapgen, polity, runconfig, saves
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
    diary: list[str] = Field(default_factory=list)  # oldest first; prompts show the last one (llm.DAY_DIARIES in "day" memory)
    recent: list[str] = Field(default_factory=list)
    remember: list[str] = Field(default_factory=list)  # what it chose to remember for long (reputation.record), oldest first


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
    character: str | None = None  # a preset key or own text, "" / "default" = neutral (llm.character_text)
    model: str | None = None  # this villager's model (makes them AI); "bot" or "bot:<kind>" makes them a bot


class Site(Strict):
    kind: str
    by: str  # who started it; the site is opened where they stand (move them with `location` first)
    supplied: bool = False  # all materials already brought (by the starter)


class Bill(Strict):
    who: str
    coins: int = Field(ge=1)
    kind: Literal["tax", "fine"] = "tax"
    days_late: int = Field(default=1, ge=0)  # 0 = due today


class PolityEdit(Strict):
    """The polity of the first town hall, already governed («С нуля» with polities on): who is in it, its form,
    who holds its treasury (the ruler, the first councillor or the assembly's treasurer), coins and number laws."""
    form: Literal["assembly", "council", "ruler"]
    keeper: str
    members: list[str] | Literal["all"] = "all"
    council: list[str] = Field(default_factory=list)  # council form: the other councillors
    coins: int = Field(default=0, ge=0)
    laws: dict[str, int] = Field(default_factory=dict)  # tax, income_tax, wealth_tax, tax_every, wage
    name: str | None = None
    coin: str | None = None


class WorldEdits(Strict):
    mayor: str | None = None
    polity: PolityEdit | None = None
    treasury: int | None = Field(default=None, ge=0)
    laws: dict[str, int] = Field(default_factory=dict)
    sites: list[Site] = Field(default_factory=list)
    bills: list[Bill] = Field(default_factory=list)


class Seating(Strict):
    """Models on seats for a fair comparison (fairness audit): the AI villagers are split into equal groups by a
    seeded order, one model per group, and every next replicate moves each group to the next model, so with two
    models replicate 2 is replicate 1 with the seats mirrored (3 Luna + 3 Haiku, then the same 6 swapped)."""
    models: list[str] = Field(min_length=2)
    rotate: bool = True  # False: every replicate keeps the same seats


class Play(Strict):
    days: int = Field(default=1, ge=1, le=30)
    ai: list[str] | Literal["all"] = "all"  # AI villagers; everyone else is a bot ("all" + from_save: as saved)
    model: str = "default"  # model id for the AI villagers, "stub" = offline
    bots: str = "worker"
    max_cost: float = Field(default=0.25, ge=0)  # USD per run (each arm and replicate), 0 = no cap
    replicates: int = Field(default=1, ge=1, le=50)  # runs per arm (aivillage/lab.py)
    reseed: bool = False  # each replicate (each mirrored set, with seating) gets the next world seed
    seating: Seating | None = None


class Arm(Strict):
    """One variant of an experiment: edits on top of the scenario's (aivillage/lab.py)."""
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,24}$")
    about: str = ""
    villagers: dict[str, Villager] = Field(default_factory=dict)
    world: WorldEdits = Field(default_factory=WorldEdits)
    config: dict = Field(default_factory=dict)  # merged into the world's config (knobs read while playing)


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
    from_save: str | None = None  # start from this save (.save.json or a zip with one) instead of `config`/`warmup`
    config: dict = Field(default_factory=dict)  # run config (runconfig.RunConfig); days/log come from `play`
    warmup: Warmup = Field(default_factory=Warmup)
    world: WorldEdits = Field(default_factory=WorldEdits)
    villagers: dict[str, Villager] = Field(default_factory=dict)
    play: Play = Field(default_factory=Play)
    expect: list[Check] = Field(default_factory=list)
    watch: list[Check] = Field(default_factory=list)
    arms: list[Arm] = Field(default_factory=list)  # experiment variants; an unedited control "AA" is added

    @property
    def is_lab(self) -> bool:
        """An experiment (several runs compared), not a single scenario run."""
        return bool(self.arms or self.play.seating or self.play.replicates > 1)


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
                    "warmup_days": s.warmup.days, "ai": s.play.ai, "mode": s.config.get("mode"),
                    "lab": s.is_lab, "arms": [a.name for a in s.arms], "replicates": s.play.replicates,
                    "models": s.play.seating.models if s.play.seating else [], "from_save": s.from_save})
    return out


# --- building the starting moment ---

def read_save(path: str | Path) -> dict:
    """A save (aivillage/saves.py) from a `.save.json` or from a zip holding one (the app's report zips).
    Adds `sha` (of the save's bytes) and `source` for the fork's log header."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ScenarioError(f"from_save: no file {p}")
    try:
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as z:
                inner = [n for n in z.namelist() if n.endswith(".save.json")]
                if len(inner) != 1:
                    raise ScenarioError(f"from_save: {p.name} must hold exactly one .save.json")
                raw = z.read(inner[0])
        else:
            raw = p.read_bytes()
        snap = json.loads(raw)
        if snap.get("type") != "save" or snap.get("version") != saves.SAVE_VERSION:
            raise ValueError("not a village save this version can read")
        saves.world_of(snap)  # checks the hash once: the engine still plays this world the same way
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        raise ScenarioError(f"from_save: {p.name}: {e}") from None
    return {**snap, "sha": hashlib.sha256(raw).hexdigest()[:16], "source": str(p)}


def start_world(scn: Scenario, *, seed: int | None = None, snap: dict | None = None) -> World:
    """The world at the scenario's moment: config and warmup with bots (or the save's world), then the edits.
    `seed`: another world seed (replicates with `play.reseed`); `snap`: the save, when the caller read it already."""
    if scn.from_save or snap is not None:
        world = World.from_dict(copy.deepcopy((snap or read_save(scn.from_save))["world"]))
        if seed is not None:
            world.config["seed"] = seed  # the named random streams (crises, threats, illness) follow it
        edit(world, scn)
        return world
    try:
        rc = runconfig.parse({**scn.config, "days": 1, **({"seed": seed} if seed is not None else {})}, "config")
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


def _polity(world: World, e: PolityEdit) -> None:
    if not polity.enabled(world.config):
        raise ScenarioError("world.polity: polities are off in this mode")
    if not world.polities:
        halls = polity.halls(world)
        if not halls:
            raise ScenarioError("world.polity: no town hall stands (start at the town stage or build one)")
        polity._found(Ctx(world, rng_for(world, "scenario")), halls[0])
    p = next(iter(world.polities.values()))
    members = sorted(world.agents) if e.members == "all" else [_name(world, n, "world.polity.members") for n in e.members]
    keeper = _name(world, e.keeper, "world.polity.keeper")
    if keeper not in members:
        raise ScenarioError("world.polity.keeper: must be one of the members")
    for other in world.polities.values():
        other["members"] = [n for n in other["members"] if n not in members]
    bad = sorted(set(e.laws) - set(polity.NUMBER_LAWS))
    if bad:
        raise ScenarioError(f"world.polity.laws: unknown {', '.join(bad)} (have: {', '.join(polity.NUMBER_LAWS)})")
    p.update(members=members, form=e.form, keeper=keeper, ballot={}, coins=e.coins,
             rulers=[] if e.form == "assembly" else [keeper] + [_name(world, n, "world.polity.council")
                                                                for n in e.council if n != keeper])
    p["laws"].update(e.laws)
    if e.name is not None:
        p["name"] = e.name
    if e.coin is not None:
        p["coin"] = e.coin


def _items(world: World, items: dict[str, int], where: str) -> dict[str, int]:
    bad = [k for k in items if k != "coins" and k not in world.config["items"]]
    if bad:
        raise ScenarioError(f"{where}: unknown items {bad}")
    if any(v < 0 for v in items.values()):
        raise ScenarioError(f"{where}: negative amounts")
    return {k: v for k, v in items.items() if v}


def _merge(into: dict, edits: dict) -> None:
    for k, v in edits.items():
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            _merge(into[k], v)
        else:
            into[k] = v


def edit(world: World, scn: Scenario | Arm) -> None:
    """Apply `villagers` and `world` edits (of a scenario, or an experiment arm on top of it; an arm's `config` is
    merged into the world's config too), then book whatever appeared or vanished in the ledger."""
    cfg = world.config
    if isinstance(scn, Arm):
        _merge(cfg, scn.config)
    for name, v in scn.villagers.items():
        a = world.agents[_name(world, name, "villagers")]
        if v.character is not None:  # llm_agents builds the prompt's character line from the config
            next(x for x in cfg["agents"] if x["name"] == name)["character"] = v.character
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
    if e.polity is not None:
        _polity(world, e.polity)
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
    # Untouched holdings keep the ledger as it was (an unedited fork starts with its save's exact hash).
    held = {k: v for k, v in holdings(world).items() if v}
    if held != {k: v for k, v in world.ledger.items() if v}:
        world.ledger = held
    check(world)


def ai_names(world: World, scn: Scenario, *, ai: list[str] | None = None, snap: dict | None = None,
             arm: Arm | None = None) -> list[str]:
    """Who plays with a model: `ai` (the caller's choice), else the scenario's play.ai ("all" from a save = the
    save's AI villagers), then villagers given a `model` edit join (or leave, with "bot")."""
    names = sorted(world.agents)
    if ai is not None:
        chosen = list(ai)
    elif scn.play.ai != "all":
        chosen = list(scn.play.ai)
    elif snap is not None:
        chosen = sorted(snap["brains"]["agents"])
    else:
        chosen = names
    for n in chosen:
        _name(world, n, "play.ai")
    for edits in (scn.villagers, arm.villagers if arm else {}):
        for n, v in edits.items():
            if v.model:
                chosen = [x for x in chosen if x != n] + ([] if v.model.startswith("bot") else [n])
    return sorted(set(chosen))


def brains(world: World, scn: Scenario, *, ai: list[str] | None = None, model: str | None = None,
           bots: str | None = None, snap: dict | None = None, arm: Arm | None = None,
           seats: dict[str, str] | None = None):
    """`decide` (with .agents / .bots like run.main builds it) and `on_night` for the scenario's villagers.

    Models: `model` (else play.model) for every AI villager, then `seats` (play.seating, aivillage/lab.py), then
    each villager's own `model` edit. From a save (`snap`) the villagers keep their saved brains (memory, diary,
    bot state) and their saved model unless one of those changes it; a model change keeps the memory. Token use
    starts at zero, so a fork's cost is its own."""
    from .llm import Usage
    from .run import llm_agents, night_reflection
    play = scn.play
    names = sorted(world.agents)
    chosen = ai_names(world, scn, ai=ai, snap=snap, arm=arm)
    kind = bots or play.bots
    if kind not in BOT_TYPES:
        raise ScenarioError(f"play.bots: unknown bot '{kind}' (have: {', '.join(BOT_TYPES)})")
    villagers = [scn.villagers, arm.villagers if arm else {}]
    saved = (snap or {}).get("brains") or {"agents": {}, "bots": {}}
    models = {n: model or (saved["agents"][n]["model"] if n in saved["agents"] else play.model) for n in chosen}
    models.update({n: m for n, m in (seats or {}).items() if n in models})
    bot_kind = {}
    for edits in villagers:
        for n, v in edits.items():
            if v.model and v.model.startswith("bot"):
                bot_kind[n] = v.model.partition(":")[2] or kind
            elif v.model:
                models[n] = v.model
    for k in bot_kind.values():
        if k not in BOT_TYPES:
            raise ScenarioError(f"villagers: unknown bot '{k}' (have: {', '.join(BOT_TYPES)})")
    seed = world.config["seed"]
    if snap is not None:
        keep = copy.deepcopy(saved)
        keep["agents"] = {n: {**a, "model": models[n]} for n, a in keep["agents"].items() if n in models}
        keep["bots"] = {n: b for n, b in keep["bots"].items() if n not in models and n not in bot_kind}
        old, _ = saves.decider(world, {"brains": keep})
        agents, bot = dict(old.agents), dict(old.bots)
        agents.update(llm_agents(world, {n: m for n, m in models.items() if n not in agents}))
        for ag in agents.values():
            ag.usage = Usage()
    else:
        agents, bot = llm_agents(world, models), {}
    for n in names:
        if n not in agents and n not in bot:
            bot[n] = BOT_TYPES[bot_kind.get(n, kind)](n, seed)
    for edits in villagers:
        for name, v in edits.items():
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
            ag.kept = [{"day": max(1, world.day - 1), "text": t} for t in m.remember]

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
