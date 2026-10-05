"""Seasons: a pure function of the day number, no extra state.

Each season lasts `seasons.length_days`. A season scales the nightly regrowth of
resources; in winter the field gives nothing and what is left on it withers.
"""

from __future__ import annotations

from .ops import Ctx


def season_of(cfg: dict, day: int) -> str:
    s = cfg["seasons"]
    return s["order"][((day - 1) // s["length_days"]) % len(s["order"])]


def days_left(cfg: dict, day: int) -> int:
    """Days remaining in the current season, today included."""
    n = cfg["seasons"]["length_days"]
    return n - (day - 1) % n


def regen(cfg: dict, day: int, resource: str, base: int) -> int:
    if not cfg["seasons"]["enabled"]:
        return base
    mult = cfg["seasons"]["regen_multiplier"].get(season_of(cfg, day), {}).get(resource, 1.0)
    return int(base * mult)


def time_info(cfg: dict, day: int) -> dict:
    if not cfg["seasons"]["enabled"]:
        return {}
    order = cfg["seasons"]["order"]
    season = season_of(cfg, day)
    return {"season": season, "season_days_left": days_left(cfg, day),
            "next_season": order[(order.index(season) + 1) % len(order)]}


def new_day(ctx: Ctx) -> None:
    """Called at dawn, before regrowth. Announces a new season and applies its one-off effects."""
    w, cfg = ctx.world, ctx.cfg
    s = cfg["seasons"]
    if not s["enabled"] or w.day == 1 or (w.day - 1) % s["length_days"] != 0:
        return
    season = season_of(cfg, w.day)
    for loc_id, resources in s.get("wither", {}).get(season, {}).items():
        loc = w.locations.get(loc_id)
        if loc is None:
            continue
        for r in resources:
            loc.resources[r] = 0
    ctx.emit("season", f"{season.capitalize()} has come. {s['announce'].get(season, '')}".strip(),
             visibility="public")
