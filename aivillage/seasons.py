"""Seasons: a pure function of the day number, no extra state.

Each season lasts `seasons.length_days`; day 1 is the first day of `seasons.start` (default order[0]).
A season scales the nightly regrowth of resources; in winter nothing can be sown, and at the first
dawn of a `frost` season every garden bed still growing dies (ripe stock waiting to be collected stays).
`calendar(days)` picks a length and a start so that a short run still ends in winter.
"""

from __future__ import annotations

import math

from . import tiles
from .ops import Ctx


def _pos(cfg: dict, day: int) -> int:
    """Days since the first day of order[0] in the calendar's first year (day 1 = start + offset_days)."""
    s = cfg["seasons"]
    first = s["order"].index(s.get("start") or s["order"][0])
    return first * s["length_days"] + s.get("offset_days", 0) + day - 1


def season_of(cfg: dict, day: int) -> str:
    s = cfg["seasons"]
    return s["order"][(_pos(cfg, day) // s["length_days"]) % len(s["order"])]


def days_left(cfg: dict, day: int) -> int:
    """Days remaining in the current season, today included."""
    n = cfg["seasons"]["length_days"]
    return n - _pos(cfg, day) % n


def calendar(days: int, length: int = 0, order: list[str] | None = None) -> dict:
    """{length_days, start, offset_days} for a run of `days` so that it ends in winter (the last season).

    length 0 = auto: the whole year fits the run (3 days = summer, autumn, winter; 7 days = 2-day seasons).
    Winter takes the last min(length, days // 3) days (at least one); what comes before is rolled back
    from there, so a 2-day run with week-long seasons is one day of late autumn, then winter. A run longer
    than a year starts at the beginning of order[0]."""
    order = order or ["spring", "summer", "autumn", "winter"]
    n, days = len(order), max(1, int(days))
    length = int(length) or math.ceil(days / n)
    if days > n * length:  # more than a year: start at the beginning of it
        return {"length_days": length, "start": order[0], "offset_days": 0}
    winter_day = days - min(length, max(1, days // 3)) + 1
    pos = ((n - 1) * length - winter_day + 1) % (n * length)
    return {"length_days": length, "start": order[pos // length], "offset_days": pos % length}


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
    if not s["enabled"] or w.day == 1 or _pos(cfg, w.day) % s["length_days"] != 0:
        return
    season = season_of(cfg, w.day)
    for loc_id, resources in s.get("wither", {}).get(season, {}).items():
        loc = w.locations.get(loc_id)
        if loc is None:
            continue
        for r in resources:
            tiles.clear(loc, r)
    nxt = s["order"][(s["order"].index(season) + 1) % len(s["order"])]
    text = f"{season.capitalize()} has come. {s['announce'].get(season, '')}".strip()
    ctx.emit("season", f"{text} {nxt.capitalize()} comes in {s['length_days']} day(s).",
             visibility="public", season=season)
    if season in s.get("frost", []):
        _frost(ctx)


def _frost(ctx: Ctx) -> None:
    """Garden beds still growing die; each household is told what it lost."""
    from . import plots  # plots imports seasons
    w = ctx.world
    for plot in w.plots.values():
        dead = [b for b in plot.buildings if b.get("crop")]
        if not plot.owner or not dead:
            continue
        crop = dead[0]["crop"]
        for b in dead:
            b["crop"], b["ripe_day"] = None, 0
            b.pop("amount", None)
        where = "" if plot.kind == "home" else f" at {w.locations[plot.home].name}"
        ctx.emit("frost", f"Frost killed the {crop} growing in {len(dead)} of your garden beds{where}.",
                 to=plots.household(w, plot), location=plot.home, beds=len(dead), crop=crop,
                 by=plot.owner, private=True)


def fact(cfg: dict) -> str:
    """Prompt line: how the year turns (agents also see season, season_days_left, next_season)."""
    s = cfg.get("seasons", {})
    if not s.get("enabled"):
        return ""
    frost = ", ".join(s.get("frost", []))
    return (f"- Seasons: {', '.join(s['order'])}, {s['length_days']} day(s) each, then again. In winter nothing "
            f"can be sown, berries are gone and fish are scarce"
            + (f"; at the first dawn of {frost} any crop still growing freezes" if frost else "")
            + "".join(f"; a {season} night costs {n} more satiety" for season, n in (s.get("night_hunger") or {}).items()
                      if n) + ".")


def night_hunger(cfg: dict, day: int) -> int:
    """Extra satiety lost tonight in this season (config `seasons.night_hunger`, e.g. {"winter": 10})."""
    s = cfg.get("seasons", {})
    if not s.get("enabled") or not s.get("night_hunger"):
        return 0
    return int(s["night_hunger"].get(season_of(cfg, day), 0))
