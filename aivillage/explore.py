"""Exploration: each villager knows only the places they have walked to themselves (config block `explore`).

Off by default: every villager sees the whole map, as in every mode before it. On:
- At the start a villager knows where they stand, their home, `center` (the square) and every place within
  `start_radius` roads of it. A place becomes known to a villager when they stand there themselves; others can
  only tell about it (say, letter), which teaches nothing to the engine.
- The observation lists the villager's known places with what can be gathered there (`explored.places`) and the
  roads from them into places they do not know yet (`explored.roads_to_unexplored`). The prompt's map line is
  replaced by `facts()`.
- `move` goes to a known place, or one road further from a known place, and only walks through known places.

Knowledge is marked when the villager is observed (they are always observed after a walk ends, and replay
observes the same villagers at the same ticks), so it is part of the world state and of its hash.
State: `world.explore` = {name: [known location ids, sorted]}. Log: tick `view.known` = places someone knows.
Spec: docs/specs/survival.md.
"""

from __future__ import annotations

from collections import deque

from . import actions
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, World


def _c(cfg: dict) -> dict:
    return cfg.get("explore") or {}


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def _start(world: World, a: Agent) -> set[str]:
    locs = world.locations
    c = _c(world.config)
    center = c.get("center", "square")
    if center not in locs:
        center = a.location
    known = {a.location, center}
    if a.home in locs:
        known.add(a.home)
    frontier = [center]
    for _ in range(int(c.get("start_radius", 1))):
        frontier = [n for cur in frontier for n in locs[cur].neighbors if n not in known]
        known.update(frontier)
    return known


def known(world: World, name: str) -> set[str]:
    """Places `name` knows (starting knowledge on first use)."""
    st = world.explore
    if name not in st:
        st[name] = sorted(_start(world, world.agents[name]))
    return set(st[name])


def mark(world: World, name: str) -> None:
    """The villager stands where they are: that place is known to them from now on."""
    k = known(world, name)
    loc = world.agents[name].location
    if loc not in k:
        world.explore[name] = sorted(k | {loc})


def observe(world: World, name: str) -> dict:
    if not enabled(world.config):
        return {}
    mark(world, name)
    k = known(world, name)
    locs, cfg_locs = world.locations, world.config["locations"]
    places = {lid: sorted((cfg_locs.get(lid) or {}).get("resources") or {}) for lid in sorted(k)}
    roads = {lid: [n for n in locs[lid].neighbors if n not in k] for lid in sorted(k)}
    return {"explored": {"places": places, "roads_to_unexplored": {lid: r for lid, r in roads.items() if r}}}


def view(world: World) -> list[str] | None:
    """Log field `view.known`: places at least one villager knows; None when exploration is off."""
    if not enabled(world.config):
        return None
    return sorted({lid for ids in world.explore.values() for lid in ids})


def facts(cfg: dict) -> str:
    if not enabled(cfg):
        return ""
    return ("- Map: you know only the places you have stood in yourself (and those you knew at the start). "
            "\"explored.places\" lists them with what can be gathered there; \"explored.roads_to_unexplored\" lists "
            "roads from them into places you have not been to. Others can tell you about a place; it stays unknown "
            "to you until you get there. move goes to a known place or one road further from a known place, walking "
            "only through places you know; it finds the path itself, one step per hour.")


# ---------- move only through known places ----------

def _path(world: World, start: str, goal: str, allowed: set[str]) -> list[str] | None:
    prev: dict[str, str] = {start: start}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            path = []
            while cur != start:
                path.append(cur)
                cur = prev[cur]
            return list(reversed(path))
        for n in world.locations[cur].neighbors:
            if n not in prev and n in allowed:
                prev[n] = cur
                q.append(n)
    return None


_plain_move = ACTIONS.specs["move"].apply


def _move(ctx: Ctx, a: Agent, args: actions.MoveArgs) -> None:
    w = ctx.world
    if not enabled(ctx.cfg) or args.to not in w.locations or args.to == a.location:
        return _plain_move(ctx, a, args)
    k = known(w, a.name) | {a.location}
    if args.to not in k and not any(args.to in w.locations[lid].neighbors for lid in k):
        raise ActionError(f"you do not know the way to {args.to}: you have not been there and no road from a place "
                          "you know leads there")
    path = _path(w, a.location, args.to, k | {args.to})
    if not path:
        raise ActionError(f"no road to {args.to} through places you know")
    actions.step_move(ctx, a, path[0])
    a.task = {"kind": "move", "path": path[1:]} if len(path) > 1 else None


ACTIONS.specs["move"].apply = _move
