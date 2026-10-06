"""Night, cold and winter (config block `warmth`; off unless a mode or the start screen turns it on).

Each night every active villager gets warmth where they sleep: 1 for a roof (`has_roof`: a house or a
shelter on the plot they are on), 1 for a burning fire there (a campfire, or the hearth of a house), 1 for clothes they carry (`clothes`, none yet). The season says how
much a night needs (`need`). Each point short costs `short_health` health and `short_satiety` satiety;
in a `cold_seasons` season each point short is also a `sick_chance` of falling ill (illness.py).

A fire burns `fuel_per_night[season]` wood from its store on a night someone sleeps by it (0 = it needs
none); with less than that in the store it stays out. `stoke` puts wood from the bag into the fire where
one stands, and that fire warms everyone sleeping there, whoever brought the wood. The stores are
`world.warmth["fuel"]` ({location: wood}); wood put in is burned at once (it leaves the item ledger).
"""

from __future__ import annotations

import random
from typing import Callable

from pydantic import BaseModel, Field

from . import illness, ops, seasons
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, World

# Other modules add places with a fire: fn(world) -> set of location ids (a campfire building, ...).
FIRE_SOURCES: list[Callable[[World], set[str]]] = []


def _c(cfg: dict) -> dict:
    return cfg.get("warmth") or {}


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def _fuel(world: World) -> dict[str, int]:
    return world.warmth.setdefault("fuel", {})


def season(cfg: dict, day: int) -> str:
    return seasons.season_of(cfg, day) if cfg.get("seasons", {}).get("enabled") else "default"


def need(cfg: dict, day: int) -> int:
    n = _c(cfg).get("need", {})
    return int(n.get(season(cfg, day), n.get("default", 1)))


def fuel_per_night(cfg: dict, day: int) -> int:
    return int(_c(cfg).get("fuel_per_night", {}).get(season(cfg, day), 0))


def has_roof(world: World, a: Agent) -> bool:
    """A roof where `a` sleeps: a house (level >= 1) or a `shelter` in the yard of the plot they stand on;
    at home, also whatever `construction.has_roof(world, name)` says once that module exists."""
    plot = world.plots.get(a.location)
    if plot is not None and (plot.house >= 1 or any(b.get("kind") == "shelter" for b in plot.buildings)):
        return True
    try:
        from . import construction  # type: ignore[attr-defined]  # task 3 ("Стройка своими руками")
    except ImportError:
        return False
    return a.location == a.home and bool(getattr(construction, "has_roof", lambda w, n: False)(world, a.name))


def fire_places(world: World) -> set[str]:
    """Locations with a fireplace: house hearths, campfire buildings in yards, `warmth.campfires`."""
    out = set(_c(world.config).get("campfires") or [])
    for plot in world.plots.values():
        if plot.kind == "home" and plot.house >= 1:
            out.add(plot.home)
        if any(b.get("kind") == "campfire" for b in plot.buildings):
            out.add(plot.home)
    for fn in FIRE_SOURCES:
        out |= fn(world)
    return out


def _clothed(cfg: dict, a: Agent) -> bool:
    return any(ops.count(a.inventory, k) for k in _c(cfg).get("clothes") or [])


def night(ctx: Ctx) -> None:
    """Called once a night, after the engine's own night loop and before health is checked."""
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        return
    c = _c(cfg)
    want, per, now = need(cfg, w.day), fuel_per_night(cfg, w.day), season(cfg, w.day)
    sleepers = sorted((a for a in w.agents.values() if a.status == "active"), key=lambda a: a.name)
    places, store, lit = fire_places(w), _fuel(w), set()
    for loc in sorted({a.location for a in sleepers} & places):
        if per <= 0:
            lit.add(loc)
        elif store.get(loc, 0) >= per:
            store[loc] -= per
            lit.add(loc)
            if not store[loc]:
                del store[loc]
    rng = random.Random(f"{cfg['seed']}:{w.tick}:warmth")
    hp, sat = int(c.get("short_health", 0)), int(c.get("short_satiety", 0))
    cold = now in (c.get("cold_seasons") or [])
    for a in sleepers:
        roof, fire, clothes = has_roof(w, a), a.location in lit, _clothed(cfg, a)
        short = max(0, want - roof - fire - clothes)
        if not short:
            continue
        a.health = max(0, a.health - short * hp)
        a.satiety = max(0, a.satiety - short * sat)
        missing = [x for x, ok in (("no roof", roof), ("no fire" if a.location not in places or per <= 0
                                    else "the fire had too little wood", fire)) if not ok]
        ctx.emit("cold_night", f"You slept cold ({', '.join(missing)}): -{short * hp} health, -{short * sat} satiety.",
                 to=[a.name], person=a.name, short=short, season=now)
        p = short * float(c.get("sick_chance", 0))
        if cold and illness.enabled(cfg) and not illness.sick(w, a) and p > 0 and rng.random() < p:
            illness.make_sick(ctx, a, int(illness._c(cfg).get("days", 2)),
                              f"{a.name} caught a chill in the cold night and fell ill.", cause="cold")


class StokeArgs(BaseModel):
    wood: int = Field(default=1, ge=1, description="how much wood from your bag")


def _can_stoke(ctx: Ctx, a: Agent) -> bool:
    return enabled(ctx.cfg) and ops.count(a.inventory, "wood") > 0 and a.location in fire_places(ctx.world)


@ACTIONS.action("stoke", "Put wood from your bag into the fire where you stand; it burns while people sleep by it.",
                StokeArgs, available=_can_stoke)
def stoke(ctx: Ctx, a: Agent, args: StokeArgs) -> None:
    w, cap = ctx.world, int(_c(ctx.cfg).get("max_fuel", 20))
    if not enabled(ctx.cfg):
        raise ActionError("there is no fire to keep in this village")
    if a.location not in fire_places(w):
        raise ActionError("there is no fireplace here")
    have = ops.count(a.inventory, "wood")
    if have < args.wood:
        raise ActionError(f"you have {have} wood")
    store = _fuel(w)
    put = min(args.wood, cap - store.get(a.location, 0))
    if put <= 0:
        raise ActionError(f"the fire here already holds {cap} wood")
    ops.burn(w, a.inventory, "wood", put)
    store[a.location] = store.get(a.location, 0) + put
    loc = w.locations[a.location].name
    ctx.emit("stoke", f"{a.name} put {put} wood into the fire at {loc} (it holds {store[a.location]}).",
             actor=a.name, location=a.location, visibility="location", wood=put, fuel=store[a.location])


def hidden(cfg: dict) -> frozenset[str]:
    """Actions kept out of the handbook while warmth is off (run.llm_agents adds them to disabled_actions)."""
    return frozenset() if enabled(cfg) else frozenset({"stoke"})


def observe(world: World, name: str) -> dict:
    cfg = world.config
    if not enabled(cfg):
        return {}
    a = world.agents[name]
    here: dict = {"roof": has_roof(world, a), "fireplace": a.location in fire_places(world)}
    if here["fireplace"]:
        here["fire_wood"] = _fuel(world).get(a.location, 0)
    return {"warmth": {"night_warmth_needed": need(cfg, world.day),
                       "wood_a_fire_burns_tonight": fuel_per_night(cfg, world.day), "here": here}}


def facts(cfg: dict) -> str | None:
    if not enabled(cfg):
        return None
    c = _c(cfg)
    needs = ", ".join(f"{k} {v}" for k, v in c.get("need", {}).items())
    fuel = ", ".join(f"{k} {v}" for k, v in c.get("fuel_per_night", {}).items() if v) or "none"
    cold = ", ".join(c.get("cold_seasons") or [])
    return (f"- Night and cold: a night needs warmth ({needs}). A roof where you sleep (a house) gives 1, a burning "
            f"fire there (a campfire or a house hearth) gives 1. Each point short costs {c.get('short_health', 0)} "
            f"health and {c.get('short_satiety', 0)} satiety that night"
            + (f"; in {cold} each point short is also a {round(100 * float(c.get('sick_chance', 0)))}% chance "
               f"to fall ill" if cold and c.get("sick_chance") else "")
            + f". A fire burns wood from its store each night someone sleeps by it ({fuel}); stoke puts wood from "
            f"your bag into the fire where you stand, and it warms everyone sleeping there.")
