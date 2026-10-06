"""Choosing where to live (config block `settle`), only in a camp start of «С нуля» (modes.camp_start).

Everyone starts at the camp (`settle.camp`, the square) with no house site: their home location
(`home_<Name>`, with their chest and bed) is a spot at the camp, one road from it. `settle` takes one free
house site at the place where the villager stands, first come: the home then hangs off that place instead of
the camp (same id, so chest, yard and everything keyed by it moves along). It is done once. Until then the
villager has no yard: nothing can be built or kept in it (plots.plot_here sees no plot there).

House sites come from the map: a generated map (mapgen.py) puts a few around each place a villager may want to
live by (`map.sites` = {site id: {"near": place, "cells": n}}, geometry in `map.layout.places`); the hand-made
map gets `sites_per_place` plain sites at every place with resources and at the camp.

Trails: every walk along a road is counted (`trails`, "a|b" -> times), so the viewer draws a footpath where
people walk and a road where they walk a lot; the engine does not use the count.

State: `world.settle` = {"camp": [villagers without a site], "homes": {name: site id}, "trails": {"a|b": n}}.
Log: tick `view.settle` (the same, for the viewer). Spec: docs/specs/survival.md.
"""

from __future__ import annotations

from . import ops
from .ops import Ctx, Event
from .registry import ACTIONS, ActionError
from .state import Agent, World


def _c(cfg: dict) -> dict:
    return cfg.get("settle") or {}


def active(cfg: dict) -> bool:
    """Settling is on: the block is enabled and the run starts as an empty camp."""
    from . import modes
    return bool(_c(cfg).get("enabled")) and modes.camp_start(cfg)


def camp(cfg: dict) -> str:
    return _c(cfg).get("camp", "square")


def sites(cfg: dict) -> dict[str, dict]:
    """House sites: {site id: {"near": place id, "cells": n}} in a fixed order."""
    m = cfg.get("map") or {}
    if m.get("sites") is not None:
        return m["sites"]
    k = int(_c(cfg).get("sites_per_place", 3))
    near = [lid for lid, s in cfg["locations"].items() if s.get("resources") and "lot" not in s]
    if camp(cfg) in cfg["locations"] and camp(cfg) not in near:
        near.insert(0, camp(cfg))
    out, i = {}, 0
    for lid in near:
        for _ in range(k):
            i += 1
            out[f"site_{i}"] = {"near": lid, "cells": int((cfg.get("plots") or {}).get("start_cells", 6))}
    return out


def setup(world: World) -> None:
    """Called by engine.new_world after the homes exist: everyone's home is a spot at the camp."""
    cfg = world.config
    if not active(cfg):
        return
    world.settle = {"camp": sorted(world.agents), "homes": {}, "trails": {}}
    for a in world.agents.values():
        world.locations[a.home].name = f"{a.name}'s spot at the camp"
    if camp(cfg) in world.locations:
        world.locations[camp(cfg)].name = "Camp"


def hidden_actions(cfg: dict) -> frozenset[str]:
    """Leave `settle` out of the handbook when there is no camp start."""
    return frozenset() if active(cfg) else frozenset({"settle"})


def unsettled(world: World, name: str) -> bool:
    return name in (world.settle or {}).get("camp", ())


def free_sites(world: World, place: str) -> list[str]:
    taken = set((world.settle or {}).get("homes", {}).values())
    return [sid for sid, s in sites(world.config).items() if s["near"] == place and sid not in taken]


def _avail(ctx: Ctx, a: Agent) -> bool:
    return unsettled(ctx.world, a.name) and bool(free_sites(ctx.world, a.location))


@ACTIONS.action("settle", "Take a free house site at the place where you stand: your home (bed, chest, yard) moves "
                "there, one road from this place. Free, first come, once.", available=_avail)
def settle(ctx: Ctx, a: Agent, args) -> None:
    w = ctx.world
    if not active(ctx.cfg):
        raise ActionError("homes here stand where they stand")
    if not unsettled(w, a.name):
        raise ActionError(f"you already have a house site ({a.home})")
    free = free_sites(w, a.location)
    if not free:
        open_at = sorted({s["near"] for s in sites(ctx.cfg).values()} - {a.location})
        open_at = [p for p in open_at if free_sites(w, p)]
        raise ActionError("no free house site here; free sites are at: " + (", ".join(open_at) or "nowhere"))
    sid, place, home = free[0], a.location, w.locations[a.home]
    for n in home.neighbors:
        if a.home in w.locations[n].neighbors:
            w.locations[n].neighbors.remove(a.home)
    home.neighbors = [place]
    w.locations[place].neighbors.append(a.home)
    home.name = f"{a.name}'s house"
    w.settle["camp"].remove(a.name)
    w.settle["homes"][a.name] = sid
    ctx.emit("settled", f"{a.name} took a house site at {w.locations[place].name}: {a.name}'s home ({a.home}) is "
             f"now one road from there.", actor=a.name, location=place, visibility="public", site=sid, home=a.home)


def observe(world: World, name: str) -> dict:
    if not active(world.config):
        return {}
    from . import explore
    a = world.agents[name]
    places = sorted({s["near"] for s in sites(world.config).values()})
    if explore.enabled(world.config):
        k = explore.known(world, name)
        places = [p for p in places if p in k]
    out = {"house_sites": {"yours": None if unsettled(world, name) else world.locations[a.home].neighbors[0],
                           "free_here": len(free_sites(world, a.location)),
                           "free_by_place": {p: n for p in places if (n := len(free_sites(world, p)))}}}
    return out


def facts(cfg: dict) -> str:
    if not active(cfg):
        return ""
    return (f"- Homes: everyone starts at the camp ({camp(cfg)}) without a house site; home_<Name> is your spot "
            "there, one road from it. settle takes a free house site at the place where you stand (first come, "
            "once): your home (bed, chest, yard) moves there and is one road from that place. Until then you have "
            "no yard to build or keep things in. \"house_sites\" lists the free sites by place.")


def _trail(ctx: Ctx, ev: Event, recipients: list[str]) -> None:
    """Count a walk along a road (the "left for" move event: the walker already stands at the far end)."""
    if ev.kind != "move" or not ev.actor or "trails" not in (ctx.world.settle or {}):
        return
    a = ctx.world.agents.get(ev.actor)
    if a is None or ev.location == a.location or ev.location not in ctx.world.locations:
        return
    if a.location not in ctx.world.locations[ev.location].neighbors:
        return
    key = "|".join(sorted((ev.location, a.location)))
    tr = ctx.world.settle["trails"]
    tr[key] = tr.get(key, 0) + 1


ops.EVENT_HOOKS.append(_trail)


def view(world: World) -> dict:
    """Log field `settle` for the viewer: who has no site yet, whose home is on which site, trails walked."""
    st = world.settle
    if not st:
        return {}
    return {"settle": {"camp": list(st["camp"]), "homes": dict(st["homes"]), "trails": dict(st["trails"])}}
