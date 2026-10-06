"""What there is to steal and who sees it: stores in view, the dark, the owner at home, the treasury.

Config block `theft` (off by default, so «Обычный» is unchanged; on in «С нуля» and «Беззаконие»):

- `see_stores`: standing somewhere you see the coins and food in other people's chests there and in the
  pockets of the people next to you (`here.chests[].coins/food`, `here.people[].coins/food`), not only your own.
- the dark: waking hours from `dark_from_hour` (`winter_dark_hours` earlier in winter) to the end of the day,
  and before `dark_until_hour`, are dark (`time.dark`). In the dark every chance to notice a theft is
  multiplied by `dark_factor`.
- `owner_notice_chance`: the owner of a chest, at home and awake, sees who robs it with this chance
  (before: never, they only learned that something was gone). `victim_notice_chance`: an awake person you
  rob notices you with this chance (before: always).
- `treasury`: `steal treasury` at the square (the village treasury) or at a polity's town hall takes coins
  from it like the holder's embezzlement: the books still show them, so nobody knows until an audit, which
  then says the coins were taken by someone unknown. The holder sees what is really there.

Pure helpers for actions.steal / plots.steal_from_plot and the observation; no state of its own.
"""

from __future__ import annotations

from . import seasons
from .state import Agent, World

UNKNOWN = "?"  # key in a treasury's `embezzled` for coins a thief (not the holder) took


def _c(cfg: dict) -> dict:
    return cfg.get("theft") or {}


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def dark_from(cfg: dict, day: int) -> int:
    t = _c(cfg)
    start = int(t.get("dark_from_hour") or cfg["day_end_hour"])
    if cfg.get("seasons", {}).get("enabled") and seasons.season_of(cfg, day) == "winter":
        start -= int(t.get("winter_dark_hours", 0))
    return start


def is_dark(world: World) -> bool:
    cfg = world.config
    if not enabled(cfg):
        return False
    return world.hour >= dark_from(cfg, world.day) or world.hour < int(_c(cfg).get("dark_until_hour") or 0)


def notice(world: World, chance: float) -> float:
    """A chance to notice a theft, lowered in the dark."""
    return chance * float(_c(world.config).get("dark_factor", 1.0)) if is_dark(world) else chance


def owner_chance(world: World) -> float:
    return notice(world, float(_c(world.config).get("owner_notice_chance", 0))) if enabled(world.config) else 0.0


def victim_chance(world: World) -> float:
    return notice(world, float(_c(world.config).get("victim_notice_chance", 1.0))) if enabled(world.config) else 1.0


def treasury_on(cfg: dict) -> bool:
    return enabled(cfg) and bool(_c(cfg).get("treasury"))


def treasury_here(world: World, a: Agent):
    """(holder for ops.move_coins, books dict-like owner, name) of the treasury where `a` stands, or None.

    A polity's treasury is kept at its town hall, the village treasury (no polities) at the square."""
    if not treasury_on(world.config):
        return None
    from . import governance, polity  # governance -> actions -> theft
    if governance.polity_on(world.config):
        p = next((p for p in world.polities.values() if p["location"] == a.location), None)
        return (polity._Purse(p), p, f"the treasury of {polity.title(p)}") if p else None
    if governance.enabled(world.config) and a.location == "square":
        return world.governance, world.governance, "the village treasury"
    return None


def take_from_treasury(world: World, books, n: int) -> None:
    """Record coins a thief took: the books still show them, an audit finds them missing (taker unknown)."""
    if isinstance(books, dict):
        books["hidden"] = books.get("hidden", 0) + n
        books.setdefault("embezzled", {})[UNKNOWN] = books["embezzled"].get(UNKNOWN, 0) + n
    else:
        books.hidden += n
        books.embezzled[UNKNOWN] = books.embezzled.get(UNKNOWN, 0) + n


def _food(cfg: dict, items: dict) -> dict:
    return {k: n for k, n in items.items() if n > 0 and cfg["items"].get(k, {}).get("food")}


def observe(world: World, name: str, obs: dict) -> None:
    """Adds `time.dark` and, with `see_stores`, coins and food of the people and chests here."""
    cfg = world.config
    if not enabled(cfg):
        return
    obs["time"]["dark"] = is_dark(world)
    if not _c(cfg).get("see_stores"):
        return
    here = obs["here"]
    for p in here["people"]:
        o = world.agents[p["name"]]
        p["coins"], p["food"] = o.coins, _food(cfg, o.inventory)
    loc = world.agents[name].location
    for c, chest in zip(here["chests"], [x for x in world.chests.values() if x.location == loc]):
        if "items" not in c:  # yours or shared with you: you already see it all
            c["coins"], c["food"] = chest.coins, _food(cfg, chest.items)


def fact(cfg: dict) -> str:
    if not enabled(cfg):
        return ""
    t = _c(cfg)
    parts = []
    if t.get("see_stores"):
        parts.append("you see the coins and food in other people's chests where you stand and in the pockets of "
                     "the people next to you")
    end = cfg["day_end_hour"]
    dark = f"from {int(t.get('dark_from_hour') or end)}:00"
    if t.get("winter_dark_hours"):
        dark += f" ({int(t.get('dark_from_hour') or end) - int(t['winter_dark_hours'])}:00 in winter)"
    if t.get("dark_until_hour"):
        dark += f" and before {int(t['dark_until_hour'])}:00"
    parts.append(f"it is dark {dark} (\"time.dark\"); in the dark every chance to notice a theft is "
                 f"x{float(t.get('dark_factor', 1.0)):g}")
    parts.append(f"an awake person you rob notices it with {float(t.get('victim_notice_chance', 1.0)):.0%} chance, "
                 f"the owner of a chest, at home and awake, sees who robs it with "
                 f"{float(t.get('owner_notice_chance', 0)):.0%} chance; a robbed person always finds the loss, "
                 "not always the thief")
    if t.get("treasury"):
        from . import governance
        where = "at a polity's town hall" if governance.polity_on(cfg) else "at the square"
        parts.append(f"steal target 'treasury' {where} takes the treasury's coins; the books still show them until "
                     "an audit, which finds them missing but not who took them; the treasury's holder sees what is "
                     "really there")
    return "- Theft: " + "; ".join(parts) + "."
