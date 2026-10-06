"""Graves: a dead villager is buried by their house and the whole village knows it.

`death_mode: "death"` lets villagers die (starvation, wounds, the god's lightning). Each death leaves a grave
(`World.graves`: name, profession, day, hour, cause, the place they died, the house the grave stands by),
a public `death` event that wakes everyone (engine.WAKE_RULES) and a lasting `graves` list in every
villager's observation, so the village keeps remembering who died and why. At the grave, `pay_respects`
is one more quick action; nothing in the world asks for it.
"""

from __future__ import annotations

from pydantic import BaseModel

from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, World

CAUSES = {"hunger": "of hunger", "wounds": "of their wounds", "lightning": "of a lightning strike"}


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("graves", {}).get("enabled", True))


def cause_of(a: Agent) -> str:
    """What killed `a`: a marked harm (the god's lightning), hunger (starving), else wounds."""
    return a.harm or ("hunger" if a.satiety == 0 else "wounds")


def bury(ctx: Ctx, a: Agent) -> None:
    """Called by the engine when `a` dies: emit the public death event and, if graves are on, dig the grave."""
    w = ctx.world
    cause = cause_of(a)
    a.harm = ""
    place = w.locations[a.location].name if a.location in w.locations else a.location
    house = w.locations[a.home].name if a.home in w.locations else a.home
    if not enabled(ctx.cfg):
        ctx.emit("death", f"{a.name} has died.", visibility="public", person=a.name, cause=cause)
        return
    grave = {"name": a.name, "profession": a.profession, "day": w.day, "hour": w.hour, "cause": cause,
             "died_at": a.location, "home": a.home}
    w.graves.append(grave)
    ctx.emit("death", f"{a.name} the {a.profession} died {CAUSES.get(cause, cause)} at {place} (day {w.day}). "
             f"A grave now stands by {house}.", actor=a.name, location=a.home, visibility="public",
             person=a.name, cause=cause, grave=grave)


def at(world: World, location: str) -> list[dict]:
    return [g for g in world.graves if g["home"] == location]


def observe(world: World, name: str) -> dict:
    if not world.graves:
        return {}
    a = world.agents[name]
    out = {"graves": [{"name": g["name"], "profession": g["profession"], "died_day": g["day"], "cause": g["cause"],
                       "grave_at": g["home"]} for g in world.graves]}
    if here := at(world, a.location):
        out["graves_here"] = [g["name"] for g in here]
    return out


def lives(cfg: dict) -> int:
    """How many times a villager can drop to 0 health; the last one is death. 0 = never die."""
    return 1 if cfg["death_mode"] == "death" else max(0, int(cfg.get("lives", 0)))


def lives_left(cfg: dict, a: Agent) -> dict:
    """The villager's own count for the observation: hospital stays so far and how many remain before death."""
    n = lives(cfg)
    if n <= 1:
        return {}
    return {"hospital_stays": a.hospital_stays, "hospital_stays_left": max(0, n - 1 - a.hospital_stays)}


def facts(cfg: dict) -> str:
    n = lives(cfg)
    if n == 0:
        return ""
    tail = (" The dead are buried by their house; \"graves\" lists everyone who died, when and of what. "
            "A dead villager's things and land go to their spouse or closest friend; with neither, the land "
            "belongs to nobody and the chest stays where it is.")
    if n == 1:
        return "- Death: at 0 health a villager dies for good." + tail
    stays = "once" if n == 2 else f"{n - 1} times"
    return (f"- Death: at 0 health a villager is taken to the hospital ({cfg['hospital_days']} days, half of what "
            f"they carry is lost) {stays}; the next time they drop to 0 health they die for good. "
            "\"you.hospital_stays\" and \"you.hospital_stays_left\" show your own count." + tail)


def view(world: World) -> list[dict]:
    return list(world.graves)


class PersonArgs(BaseModel):
    person: str


@ACTIONS.action("pay_respects", "Stand by someone's grave for a while (at the house it stands by). People here see it.",
                PersonArgs, available=lambda c, a: bool(at(c.world, a.location)))
def pay_respects(ctx: Ctx, a: Agent, args: PersonArgs) -> None:
    graves = at(ctx.world, a.location)
    g = next((g for g in graves if g["name"].lower() == args.person.lower()), None)
    if g is None:
        here = ", ".join(x["name"] for x in graves) or "nobody"
        raise ActionError(f"there is no grave of {args.person} here (graves here: {here})")
    ctx.emit("pay_respects", f"{a.name} stands quietly at {g['name']}'s grave.", actor=a.name,
             location=a.location, visibility="location", person=g["name"])
