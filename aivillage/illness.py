"""Sickness with consequences: it spreads, it wears you down, and a neighbour can cure it.

A villager is sick while `day < sick_until_day` (the god's `sickness`, a random case at dawn with
`illness.per_day`, or caught from someone). Sick villagers cannot work (actions.work_hour). Each hour,
everyone awake in the same place as a sick villager catches it with `spread_chance`; every night a sick
villager loses `health_loss_night` health. `care(person, item)` gives a sick person here one of
`cure_items` and cures them at once (nobody can cure themselves). Numbers in config block `illness`.
"""

from __future__ import annotations

import random

from pydantic import BaseModel, Field

from . import ops
from .actions import _agent_here
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, World


def _c(cfg: dict) -> dict:
    return cfg.get("illness") or {}


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def sick(world: World, a: Agent) -> bool:
    return a.status == "active" and world.day < a.sick_until_day


def make_sick(ctx: Ctx, a: Agent, days: int, text: str, **data) -> None:
    a.sick_until_day = max(a.sick_until_day, ctx.world.day + days)
    a.task = None
    ctx.emit("sick", text, visibility="public", person=a.name, days=days, **data)


def end_of_hour(ctx: Ctx, rng: random.Random) -> None:
    """Contagion: one roll per healthy awake villager sharing a place with a sick one."""
    w, c = ctx.world, _c(ctx.cfg)
    p = float(c.get("spread_chance") or 0)
    if not enabled(ctx.cfg) or p <= 0:
        return
    sick_at: dict[str, list[str]] = {}
    for a in w.agents.values():
        if sick(w, a):
            sick_at.setdefault(a.location, []).append(a.name)
    for loc, src in sorted(sick_at.items()):
        for a in sorted(w.agents.values(), key=lambda a: a.name):
            if a.status != "active" or a.asleep or a.location != loc or sick(w, a):
                continue
            if rng.random() < p:
                make_sick(ctx, a, int(c.get("days", 2)), f"{a.name} fell ill (caught it from {sorted(src)[0]}).",
                          source=sorted(src)[0])


def night(ctx: Ctx) -> None:
    w, c = ctx.world, _c(ctx.cfg)
    loss = int(c.get("health_loss_night") or 0)
    if not enabled(ctx.cfg) or loss <= 0:
        return
    for a in w.agents.values():
        if sick(w, a):
            a.health = max(0, a.health - loss)
            ctx.emit("sick_worse", f"The sickness wore you down in the night (-{loss} health).", to=[a.name])


def new_day(ctx: Ctx, rng: random.Random) -> None:
    w, c = ctx.world, _c(ctx.cfg)
    p = float(c.get("per_day") or 0)
    if not enabled(ctx.cfg) or p <= 0 or rng.random() >= p:
        return
    well = sorted(a.name for a in w.agents.values() if a.status == "active" and not sick(w, a))
    if well:
        a = w.agents[rng.choice(well)]
        days = int(c.get("days", 2))
        make_sick(ctx, a, days, f"{a.name} fell ill and cannot work for {days} days.", cause="random")


class CareArgs(BaseModel):
    person: str = Field(description="a sick person here")
    item: str = Field(description="honey, milk or fish_soup you carry")


def _can_care(ctx: Ctx, a: Agent) -> bool:
    return enabled(ctx.cfg) and any(o.name != a.name and o.location == a.location and sick(ctx.world, o)
                                    for o in ctx.world.agents.values())


@ACTIONS.action("care", "Nurse a sick person here with one honey, milk or fish_soup you carry: they are cured at once.",
                CareArgs, available=_can_care)
def care(ctx: Ctx, a: Agent, args: CareArgs) -> None:
    if not enabled(ctx.cfg):
        raise ActionError("there is no sickness in this village")
    other = _agent_here(ctx, a, args.person)
    if not sick(ctx.world, other):
        raise ActionError(f"{other.name} is not sick")
    cures = _c(ctx.cfg).get("cure_items") or []
    if args.item not in cures:
        raise ActionError(f"{args.item} does not help; use one of: {', '.join(cures)}")
    if not ops.count(a.inventory, args.item):
        raise ActionError(f"you have no {args.item}")
    ops.burn(ctx.world, a.inventory, args.item, 1)
    other.sick_until_day = ctx.world.day
    ctx.emit("care", f"{a.name} nursed {other.name} with {args.item}; {other.name} is well again.", actor=a.name,
             location=a.location, visibility="location", to=[other.name], person=other.name, item=args.item)


def facts(cfg: dict) -> str | None:
    c = _c(cfg)
    if not enabled(cfg):
        return None
    return (f"- Sickness: a sick person cannot work, loses {c.get('health_loss_night', 0)} health each night and can "
            f"pass it to people in the same place. care with {', '.join(c.get('cure_items') or [])} cures someone else.")
