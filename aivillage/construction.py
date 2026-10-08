"""Building with your own hands: houses, workshops and village buildings go up on a building site.

Off by default (config `construction.enabled`); then houses are upgraded at once with `upgrade_house` as before.
On, every kind in `construction.catalog` is built in three steps, each one public to the people around:
- `start_building(kind)` opens a site where the villager stands: "home" kinds in their own yard (house,
  shelter, workshops, granary), "village" kinds at a common place (campfire anywhere common, market square,
  town hall, tavern, palisade at the square). The next level of something standing is a new site.
- `bring_materials(site_id, items)` delivers the level's `items` at the site (anyone may bring them).
- `construct(site_id)` is one hour of work at the site (anyone may work). The level needs `hours` in all.
  Big buildings have `min_workers`: an hour counts once at least that many different villagers worked on
  the site on the same day; hours nobody joined that day are lost. Every extra co-worker that day (up to
  `team_max`) adds `team_bonus` to each counted hour.
Finished, a "home" building stands in the owner's yard (`plot.buildings`, with a `level`; a house sets the
plot's house level) and a "village" building is common (`world.construction["buildings"]`, owner None).
The finish event names everyone who brought or worked (and, for a village building, who did not).

Effects (per level row of the catalog): `roof` (has_roof), `food_keeps_x` (spoilage.STORAGE_SOURCES),
`sell_bonus` and `defense` (works.SELL_BONUS_SOURCES / DEFENSE_SOURCES), `workshop` (crafting asks
has_building), `extra_per_batch` (a higher-level workshop adds to every batch made there; a `craft` event
hook), `makes` + `feed` + `cap` (a pen: fed from the owner's chest at night, its stock is collected like
a coop's). `opens` is text only: what village stages keep closed until one stands (shown with progress on,
so the catalog says what a market square or town hall brings). Without crafting chains, crafted materials are asked raw (`raw_instead`). Which kinds may be started at which stage: progress.DEFAULT_UNLOCKS "building:<kind>[@<level>]".

State: `world.construction` = {"sites": {id: site}, "buildings": [common buildings]}; reads never create it,
so observing does not change the world. Log: tick `view.sites` (docs/specs/survival.md) and `view.buildings`.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from . import clock, ops, plots, progress, spoilage, works
from .ops import Ctx, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, Plot, World

# Who can start what, when progress is on (the «С нуля» mode); a kind with no rule is open from the camp.
progress.DEFAULT_UNLOCKS.update({
    "building:granary": {"stage": "hamlet"},
    "building:smokehouse": {"stage": "hamlet"},
    "building:market_square": {"stage": "hamlet"},
    "building:smithy": {"stage": "hamlet"},
    "building:palisade": {"stage": "hamlet"},
    "building:house@2": {"stage": "hamlet"},
    "building:campfire@2": {"stage": "hamlet"},
    "building:granary@2": {"stage": "village"},
    "building:house@3": {"stage": "village"},
    "building:town_hall": {"stage": "village"},
    "building:tavern": {"stage": "village"},
    "building:market_square@2": {"stage": "village"},
    "building:palisade@2": {"stage": "town"},
    # task 10: more workshops, livestock, the stone wall and second levels
    "building:kiln": {"stage": "hamlet"},
    "building:mill": {"stage": "hamlet"},
    "building:tannery": {"stage": "hamlet"},
    "building:pen": {"stage": "hamlet"},
    "building:workbench@2": {"stage": "hamlet"},
    "building:weaving_shed": {"stage": "village"},
    "building:pen@2": {"stage": "village"},
    "building:kiln@2": {"stage": "village"},
    "building:mill@2": {"stage": "village"},
    "building:tannery@2": {"stage": "village"},
    "building:smokehouse@2": {"stage": "village"},
    "building:smithy@2": {"stage": "town"},
    "building:wall": {"stage": "town", "building": "palisade@2"},
})


# ---------- config and state ----------

def _c(cfg: dict) -> dict:
    return cfg.get("construction") or {}


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def catalog(cfg: dict) -> dict:
    return _c(cfg).get("catalog", {})


def _levels(cfg: dict, kind: str) -> list[dict]:
    return catalog(cfg)[kind]["levels"]


def _row(cfg: dict, kind: str, lvl: int) -> dict:
    """The catalog row of a level (its effects); {} for level 0 or an unknown kind."""
    spec = catalog(cfg).get(kind)
    return spec["levels"][min(lvl, len(spec["levels"])) - 1] if spec and lvl >= 1 else {}


def level_items(cfg: dict, row: dict) -> dict[str, int]:
    """Materials of a level. Without crafting chains, crafted materials (plank, brick, iron, clay) are asked as
    the raw ones they come from (`raw_instead`), so the catalog works in any mode."""
    items = dict(row.get("items", {}))
    if (cfg.get("crafting") or {}).get("enabled"):
        return items
    out: dict[str, int] = {}
    for k, n in items.items():
        for raw, m in (_c(cfg).get("raw_instead", {}).get(k) or {k: 1}).items():
            out[raw] = out.get(raw, 0) + n * m
    return out


def _name(cfg: dict, kind: str) -> str:
    return catalog(cfg).get(kind, {}).get("name", kind).lower()


def sites(world: World) -> dict[str, dict]:
    return world.construction.get("sites", {})


def common(world: World) -> list[dict]:
    return world.construction.get("buildings", [])


def _mut(world: World) -> dict:
    st = world.construction
    st.setdefault("sites", {})
    st.setdefault("buildings", [])
    return st


def _since(world: World) -> int:
    """First tick that still counts as 'together' now: the start of the day."""
    cfg = world.config
    return clock.tick_of(cfg, world.day, cfg["day_start_hour"])


# ---------- what stands ----------

def _plot_level(plot: Plot, kind: str) -> int:
    if kind == "house":
        return plot.house
    return max((int(b.get("level", 1)) for b in plot.buildings if b["kind"] == kind), default=0)


def _common_at(world: World, kind: str, location: str) -> dict | None:
    return next((b for b in common(world) if b["kind"] == kind and b["location"] == location), None)


def _homes_of(world: World, name: str) -> list[Plot]:
    return [p for p in world.plots.values() if p.kind == "home" and plots.may_use(world, name, p)]


def has_building(world: World, kind: str, name: str | None = None, location: str | None = None) -> int:
    """Highest level of `kind` standing (0 = none). `name`: in that villager's (or spouse's) yards or lots;
    `location`: at that place (a yard or a common place); neither: anywhere in the village."""
    best = 0
    for p in world.plots.values():
        if (name is None or plots.may_use(world, name, p)) and (location is None or p.home == location):
            best = max(best, _plot_level(p, kind))
    if name is None:
        for b in common(world):
            if b["kind"] == kind and (location is None or b["location"] == location):
                best = max(best, b["level"])
    return best


def has_roof(world: World, name: str) -> bool:
    """Does this villager (or their spouse) have a house of level 1+ or a shelter at home?"""
    cfg = world.config
    for p in _homes_of(world, name):
        if p.house >= 1:
            return True
        if any(_row(cfg, b["kind"], int(b.get("level", 1))).get("roof") for b in p.buildings):
            return True
    return False


def built(world: World) -> Counter:
    """progress.BUILT_SOURCES: common buildings (yard ones are counted from plots by progress itself)."""
    c: Counter = Counter()
    for b in common(world):
        c[b["kind"]] += 1
        for k in range(2, b["level"] + 1):
            c[f"{b['kind']}@{k}"] += 1
    return c


progress.BUILT_SOURCES.append(built)


# ---------- effects other modules read ----------

def food_keeps_x(world: World, owner: str, item: str | None) -> float:
    """spoilage.STORAGE_SOURCES: how many times longer food keeps in the owner's store (granary, smokehouse)."""
    cfg = world.config
    if not enabled(cfg):
        return 1.0
    best = 1.0
    for p in _homes_of(world, owner):
        for b in p.buildings:
            row = _row(cfg, b["kind"], int(b.get("level", 1)))
            if row.get("food_keeps_x") and (item is None or item in row.get("food_items", [item])):
                best = max(best, float(row["food_keeps_x"]))
    return best


def _common_sum(world: World, key: str) -> float:
    if not enabled(world.config):
        return 0
    return sum(_row(world.config, b["kind"], b["level"]).get(key, 0) for b in common(world))


def defense(world: World) -> int:
    return int(_common_sum(world, "defense"))


def sell_bonus(world: World) -> float:
    return float(_common_sum(world, "sell_bonus"))


def _workshop_bonus(ctx: Ctx, ev: ops.Event, names: list[str]) -> None:
    """ops.EVENT_HOOKS: a workshop of a higher level (`extra_per_batch`) adds that many to every batch made there."""
    w, cfg = ctx.world, ctx.cfg
    if ev.kind != "craft" or not enabled(cfg) or not (cfg.get("crafting") or {}).get("enabled"):
        return
    a, r = w.agents.get(ev.actor or ""), cfg["recipes"].get(ev.data.get("recipe"))
    if a is None or r is None or not ev.data.get("amount"):
        return
    from . import crafting
    fits = {r.get("building")} | set(r.get("more_at", {}))
    here = [x for x in crafting.workshops_at(w, a.location) if x["kind"] in fits and crafting._may_use(x, a.name)]
    best = max(((int(_row(cfg, x["kind"], x["level"]).get("extra_per_batch", 0)), x) for x in here),
               default=(0, None), key=lambda t: t[0])
    if best[0] <= 0:
        return
    kinds = {x["kind"] for x in here}
    base = max([r["output"], *[n for k, n in r.get("more_at", {}).items() if k in kinds]])
    extra = best[0] * (ev.data["amount"] // max(1, base))
    if extra <= 0:
        return
    rid, ws = ev.data["recipe"], best[1]
    ops.mint(w, a.inventory, rid, extra)
    ctx.emit("workshop_bonus", f"The {_level_text(cfg, ws['kind'], ws['level'])} gave {a.name} {extra} more {rid}.",
             actor=a.name, location=a.location, visibility="location", recipe=rid, amount=extra,
             building=ws["kind"], level=ws["level"])


def after_night(ctx: Ctx) -> None:
    """New day: yard buildings with `makes` (a pen) produce into their stock if fed from the owner's chest."""
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        return
    for plot in w.plots.values():
        if not plot.owner:
            continue
        chest = w.chests.get(f"chest_{plot.owner}")
        for b in plot.buildings:
            row = _row(cfg, b["kind"], int(b.get("level", 1)))
            if not row.get("makes"):
                continue
            feed = row.get("feed") or {}
            if any(chest is None or ops.count(chest.items, k) < n for k, n in feed.items()):
                ctx.emit("hungry_animals", f"Your {_name(cfg, b['kind'])} had no {fmt_items(feed)} in your chest "
                         f"last night and made nothing.", to=plots.household(w, plot), home=plot.home,
                         animals=[b["kind"]])
                continue
            for k, n in feed.items():
                ops.burn(w, chest.items, k, n)
            b.setdefault("items", {})
            for item, n in row["makes"].items():
                room = int(row.get("cap", 9)) - ops.count(b["items"], item)
                if room > 0:
                    ops.mint(w, b["items"], item, min(room, n))


spoilage.STORAGE_SOURCES.append(food_keeps_x)
ops.EVENT_HOOKS.append(_workshop_bonus)
works.DEFENSE_SOURCES.append(defense)
works.SELL_BONUS_SOURCES.append(sell_bonus)


# ---------- what can be started where ----------

def _is_private(world: World, location: str) -> bool:
    return location in world.plots or location.startswith("home_")


def _open(world: World, kind: str, lvl: int) -> bool:
    return progress.unlocked(world, f"building:{kind}") and (lvl < 2 or progress.unlocked(world, f"building:{kind}@{lvl}"))


def _site_at(world: World, kind: str, location: str) -> dict | None:
    return next((s for s in sites(world).values() if s["kind"] == kind and s["location"] == location), None)


def startable(world: World, a: Agent) -> dict[str, int]:
    """Kinds this villager can start where they stand -> the level the site would build."""
    cfg = world.config
    if not enabled(cfg):
        return {}
    loc = a.location
    plot = plots.own_plot_here(world, a) if plots.enabled(cfg) else None
    out = {}
    for kind, spec in catalog(cfg).items():
        if spec.get("place") == "home":
            if plot is None or (kind in ("house", "shelter") and plot.kind != "home"):
                continue
            if kind == "shelter" and plot.house >= 1:
                continue
            lvl = _plot_level(plot, kind) + 1
        else:
            if _is_private(world, loc) or (spec.get("at") and loc not in spec["at"]):
                continue
            b = _common_at(world, kind, loc)
            lvl = (b["level"] if b else 0) + 1
        if lvl <= len(spec["levels"]) and not _site_at(world, kind, loc) and _open(world, kind, lvl):
            out[kind] = lvl
    return out


def remaining(site: dict) -> dict[str, int]:
    return {k: v - site["given"].get(k, 0) for k, v in site["needs"].items() if site["given"].get(k, 0) < v}


def work_left(site: dict) -> float:
    return round(max(0.0, site["hours"] - site["work"]), 2)


def done_share(site: dict) -> float:
    need = sum(site["needs"].values()) + site["hours"]
    have = sum(min(v, site["given"].get(k, 0)) for k, v in site["needs"].items()) + min(site["work"], site["hours"])
    return round(have / need, 2) if need else 1.0


def _where(world: World, location: str) -> str:
    return world.locations[location].name if location in world.locations else location


def _level_text(cfg: dict, kind: str, lvl: int) -> str:
    return _name(cfg, kind) + (f" (level {lvl})" if lvl > 1 else "")


def effect_text(cfg: dict, kind: str, lvl: int) -> str:
    row = _row(cfg, kind, lvl)
    parts = []
    if kind == "house":
        parts.append(f"house level {lvl}")
    if row.get("roof"):
        parts.append("a roof to sleep under")
    if row.get("food_keeps_x"):
        what = "/".join(row["food_items"]) if row.get("food_items") else "food"
        parts.append(f"{what} in the owner's store keeps {row['food_keeps_x']}x as long" if spoilage.enabled(cfg)
                     else f"keeps {what} longer, but food does not spoil in this village, so it changes nothing")
    if row.get("sell_bonus"):
        parts.append(f"the trader pays {row['sell_bonus']:.0%} more")
    if row.get("defense"):
        parts.append(f"village defense +{row['defense']}")
    if row.get("workshop"):
        parts.append("a workshop for recipes that need it")
    if row.get("extra_per_batch"):
        parts.append(f"+{row['extra_per_batch']} to every batch made here")
    if row.get("makes"):
        feed = f" if fed {fmt_items(row['feed'])} from the owner's chest" if row.get("feed") else ""
        parts.append(f"makes {fmt_items(row['makes'])} a day{feed} (collect)")
    if row.get("opens") and progress.enabled(cfg):  # what village stages keep closed until one stands
        parts.append(f"opens {row['opens']}")
    return ", ".join(parts)


# ---------- actions ----------

class StartArgs(BaseModel):
    kind: str = Field(description="what to build, e.g. shelter, house, campfire, workbench")


@ACTIONS.action("start_building", "Open a building site here: your yard for home buildings, a common place for "
                "village ones. Then anyone can bring_materials and construct there.", StartArgs,
                available=lambda c, a: bool(startable(c.world, a)))
def start_building(ctx: Ctx, a: Agent, args: StartArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        raise ActionError("buildings are not built on sites in this village")
    kind = args.kind.strip().lower()
    opts = startable(w, a)
    if kind not in opts:
        if kind not in catalog(cfg):
            raise ActionError(f"unknown building '{args.kind}'; can start here: {', '.join(sorted(opts)) or 'nothing'}")
        if _site_at(w, kind, a.location):
            raise ActionError(f"a {_name(cfg, kind)} is already being built here ({_site_at(w, kind, a.location)['id']})")
        spec = catalog(cfg)[kind]
        if spec.get("place") == "home":
            raise ActionError(f"a {_name(cfg, kind)} is built in your own yard (your home) and only up to level "
                              f"{len(spec['levels'])}; can start here: {', '.join(sorted(opts)) or 'nothing'}")
        if spec.get("at") and a.location not in spec["at"]:
            raise ActionError(f"a {_name(cfg, kind)} is built at {', '.join(spec['at'])}")
        if progress.enabled(cfg):
            for key in (f"building:{kind}", f"building:{kind}@2", f"building:{kind}@3"):
                if not progress.unlocked(w, key):
                    raise ActionError(f"a {_name(cfg, kind)} cannot be started in this village yet: it needs "
                                      f"{progress._why(w, key)}")
        raise ActionError(f"a {_name(cfg, kind)} cannot be started here now; can start here: "
                          f"{', '.join(sorted(opts)) or 'nothing'}")
    mine = [s for s in sites(w).values() if s["started_by"] == a.name]
    cap = _c(cfg).get("max_open_sites", 2)
    if len(mine) >= cap:
        raise ActionError(f"you already started {len(mine)} unfinished sites ({', '.join(s['id'] for s in mine)}); "
                          f"at most {cap}")
    lvl = opts[kind]
    row = _levels(cfg, kind)[lvl - 1]
    home = catalog(cfg)[kind].get("place") == "home"
    site = {"id": w.new_id("site"), "kind": kind, "level": lvl, "location": a.location,
            "owner": w.plots[a.location].owner if home else None, "started_by": a.name, "started_day": w.day,
            "needs": level_items(cfg, row), "given": {}, "hours": row["hours"], "work": 0.0,
            "min_workers": int(row.get("min_workers", 1)), "workers": {}, "givers": {}, "recent": [], "pending": []}
    _mut(w)["sites"][site["id"]] = site
    together = (f"; work counts once at least {site['min_workers']} people work on it on the same day"
                if site["min_workers"] > 1 else "")
    ctx.emit("site_started", f"{a.name} started building a {_level_text(cfg, kind, lvl)} at {_where(w, a.location)} "
             f"({site['id']}). It needs {fmt_items(site['needs']) or 'no materials'} and {site['hours']} hours of "
             f"work{together}.", actor=a.name, location=a.location, visibility="public", site=site["id"],
             what=kind, level=lvl)


def _site(ctx: Ctx, a: Agent, sid: str) -> dict:
    s = sites(ctx.world).get(sid)
    if s is None:
        here = [x["id"] for x in sites(ctx.world).values() if x["location"] == a.location]
        raise ActionError(f"no building site '{sid}'; sites here: {', '.join(here) or 'none'}")
    if a.location != s["location"]:
        raise ActionError(f"site {sid} is at {s['location']}; go there first")
    return s


class BringArgs(BaseModel):
    site_id: str
    items: dict[str, int] = Field(description="materials from your inventory, e.g. {\"wood\": 4}")


@ACTIONS.action("bring_materials", "Give materials from your inventory to a building site where you are.", BringArgs,
                available=lambda c, a: any(s["location"] == a.location and remaining(s) for s in sites(c.world).values()))
def bring_materials(ctx: Ctx, a: Agent, args: BringArgs) -> None:
    s = _site(ctx, a, args.site_id)
    left = remaining(s)
    useful = {k: min(int(v), left.get(k, 0)) for k, v in args.items.items()}
    useful = {k: v for k, v in useful.items() if v > 0}
    if not useful:
        raise ActionError(f"site {s['id']} does not need that; it still needs {fmt_items(left) or 'no materials'}")
    if not ops.has_all(a.inventory, useful):
        lack = {k: v - ops.count(a.inventory, k) for k, v in useful.items() if ops.count(a.inventory, k) < v}
        raise ActionError(f"you do not have {fmt_items(lack)} more in your inventory")
    for k, v in useful.items():
        ops.burn(ctx.world, a.inventory, k, v)
        s["given"][k] = s["given"].get(k, 0) + v
    s["givers"][a.name] = s["givers"].get(a.name, 0) + sum(useful.values())
    rest = remaining(s)
    ctx.emit("site_supplied", f"{a.name} brought {fmt_items(useful)} to the {_level_text(ctx.cfg, s['kind'], s['level'])} "
             f"site ({s['id']}); still needed: {fmt_items(rest) or 'no materials'}, {_num(work_left(s))} hours of work.",
             actor=a.name, location=s["location"], visibility="location", site=s["id"], owner=s["owner"], items=useful)
    _maybe_finish(ctx, s)


class ConstructArgs(BaseModel):
    site_id: str


@ACTIONS.action("construct", "Work one hour on a building site where you are.", ConstructArgs,
                available=lambda c, a: any(s["location"] == a.location and work_left(s) > 0
                                           for s in sites(c.world).values()))
def construct(ctx: Ctx, a: Agent, args: ConstructArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    s = _site(ctx, a, args.site_id)
    if work_left(s) <= 0:
        raise ActionError(f"site {s['id']} needs no more work; it still needs {fmt_items(remaining(s))}")
    if w.day < a.sick_until_day:
        raise ActionError("you are sick and cannot work")
    since = _since(w)
    s["recent"] = [x for x in s["recent"] if x[0] >= since] + [[w.tick, a.name]]
    lost = [x for x in s["pending"] if x[0] < since]
    s["pending"] = [x for x in s["pending"] if x[0] >= since] + [[w.tick, a.name]]
    team = sorted({n for _, n in s["recent"]})
    what = _level_text(cfg, s["kind"], s["level"])
    if lost:
        ctx.emit("site_work_lost", f"{len(lost)} hour(s) of work on the {what} ({s['id']}) did not count: fewer "
                 f"than {s['min_workers']} people worked on it that day.",
                 to=sorted({n for _, n in lost} | {a.name}), site=s["id"])
    if len(team) < s["min_workers"]:
        ctx.emit("construct", f"{a.name} worked an hour on the {what} ({s['id']}). It counts once "
                 f"{s['min_workers'] - len(team)} more people work on it today.", actor=a.name,
                 location=s["location"], visibility="location", site=s["id"], owner=s["owner"], counted=False,
                 team=team)
        return
    c = _c(cfg)
    per = 1 + c.get("team_bonus", 0) * (min(len(team), c.get("team_max", 3)) - 1)
    for _, n in s["pending"]:
        s["work"] = round(s["work"] + per, 2)
        s["workers"][n] = round(s["workers"].get(n, 0) + per, 2)
    s["pending"] = []
    with_ = f" with {', '.join(n for n in team if n != a.name)}" if len(team) > 1 else ""
    ctx.emit("construct", f"{a.name} worked an hour on the {what} ({s['id']}){with_}; {_num(work_left(s))} hours of "
             f"work left.", actor=a.name, location=s["location"], visibility="location", site=s["id"],
             owner=s["owner"], counted=True, team=team, per_hour=per)
    _maybe_finish(ctx, s)


def _maybe_finish(ctx: Ctx, s: dict) -> None:
    if remaining(s) or work_left(s) > 0:
        return
    w, cfg = ctx.world, ctx.cfg
    del _mut(w)["sites"][s["id"]]
    place(w, s["kind"], s["location"], s["level"], builders=_builders(s))
    helpers = _builders(s)
    text = f"The {_level_text(cfg, s['kind'], s['level'])} at {_where(w, s['location'])} is finished"
    eff = effect_text(cfg, s["kind"], s["level"])
    text += f" ({eff})." if eff else "."
    text += " Built by: " + ", ".join(f"{n} ({_share(s, n)})" for n in helpers) + "."
    idle = []
    if s["owner"] is None:
        idle = sorted(n for n, o in w.agents.items() if o.status == "active" and n not in helpers)
        if idle:
            text += " Did not take part: " + ", ".join(idle) + "."
    ctx.emit("building_done", text, location=s["location"], visibility="public", site=s["id"], what=s["kind"],
             level=s["level"], owner=s["owner"], work=dict(s["workers"]), materials=dict(s["givers"]), idle=idle)


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def _share(s: dict, name: str) -> str:
    parts = []
    if s["workers"].get(name):
        parts.append(f"{_num(s['workers'][name])}h of work")
    if s["givers"].get(name):
        parts.append(f"{s['givers'][name]} materials")
    return " + ".join(parts)


def _builders(s: dict) -> list[str]:
    return sorted(set(s["workers"]) | set(s["givers"]))


def place(world: World, kind: str, location: str, level: int = 1, builders: list[str] | None = None) -> None:
    """Make `kind` stand at `location` at `level` (a finished site, or a start stage that begins with it)."""
    cfg = world.config
    if catalog(cfg)[kind].get("place") == "home":
        plot = world.plots[location]
        if kind == "house":
            if level >= 2 and level > plot.house:
                plot.cells += cfg["plots"]["house_bonus_cells"] * (level - max(plot.house, 1))
            plot.house = max(plot.house, level)
            return
        b = next((x for x in plot.buildings if x["kind"] == kind), None)
        if b is None:
            plot.buildings.append({"id": world.new_id("b"), "kind": kind, "built_day": world.day, "items": {},
                                   "level": level})
        else:
            b["level"] = max(int(b.get("level", 1)), level)
        return
    b = _common_at(world, kind, location)
    if b is None:
        _mut(world)["buildings"].append({"id": world.new_id("bld"), "kind": kind, "level": level,
                                         "location": location, "owner": None, "built_day": world.day,
                                         "builders": list(builders or [])})
    else:
        b["level"] = max(b["level"], level)
        b["builders"] = sorted(set(b.get("builders", [])) | set(builders or []))


def _guard(ctx: Ctx, actor: Agent, name: str) -> str | None:
    if name == "upgrade_house" and enabled(ctx.cfg) and "house" in catalog(ctx.cfg):
        return "houses here are built on a building site: start_building house at your home"
    return None


ACTIONS.guards.append(_guard)


def hidden_actions(cfg: dict) -> frozenset[str]:
    """Actions to leave out of the handbook: with houses built on a site, upgrade_house is always refused."""
    return frozenset({"upgrade_house"}) if enabled(cfg) and "house" in catalog(cfg) else frozenset()


# ---------- observation, prompt, log ----------

def _site_obs(world: World, s: dict) -> dict:
    out = {"id": s["id"], "building": s["kind"], "level": s["level"], "at": s["location"],
           "for": s["owner"] or "the village", "still_needs": remaining(s), "work_left_hours": work_left(s),
           "people_needed_on_the_same_day": s["min_workers"], "work_done_by": dict(s["workers"]),
           "materials_by": dict(s["givers"])}
    if s["min_workers"] > 1:  # who an hour of work here now would count with
        since = _since(world)
        if now := sorted({n for t, n in s["recent"] if t >= since}):
            out["worked_on_it_today"] = now
    return out


def observe(world: World, name: str) -> dict:
    cfg = world.config
    if not enabled(cfg):
        return {}
    a = world.agents[name]
    out: dict = {"building_sites": [_site_obs(world, s) for s in sites(world).values()]}
    here = startable(world, a)
    if here:
        out["can_start_building_here"] = {
            k: {"level": lvl, "items": level_items(cfg, _levels(cfg, k)[lvl - 1]),
                "hours": _levels(cfg, k)[lvl - 1]["hours"],
                "people_needed_on_the_same_day": _levels(cfg, k)[lvl - 1].get("min_workers", 1),
                "gives": effect_text(cfg, k, lvl)} for k, lvl in here.items()}
    if common(world):
        out["village_buildings"] = [{"building": b["kind"], "level": b["level"], "at": b["location"]}
                                    for b in common(world)]
    return out


def facts(cfg: dict) -> str:
    if not enabled(cfg):
        return ""
    rows = []
    rules = progress.rules(cfg) if progress.enabled(cfg) else {}
    for kind, spec in catalog(cfg).items():
        where = "your yard" if spec.get("place") == "home" else ("/".join(spec["at"]) if spec.get("at") else "a common place")
        lv = []
        for i, row in enumerate(spec["levels"], 1):
            opens = rules.get(f"building:{kind}@{i}" if i > 1 else f"building:{kind}") or {}
            when = f", from stage {opens['stage']}" if opens.get("stage") else ""
            ppl = f", {row['min_workers']} people" if row.get("min_workers", 1) > 1 else ""
            eff = effect_text(cfg, kind, i)
            lv.append(f"L{i}: {fmt_items(level_items(cfg, row))}, {row['hours']}h{ppl}{when}" + (f" -> {eff}" if eff else ""))
        rows.append(f"{kind} ({where}; " + "; ".join(lv) + ")")
    c = _c(cfg)
    return ("- Building: start_building opens a site where you stand, anyone can bring_materials and construct "
            "(1 hour of work) there. With 'N people', an hour counts once N different villagers work on the site on "
            f"the same day; hours nobody joined that day are lost. Each extra person working there that day adds "
            f"{c.get('team_bonus', 0):.0%} "
            f"to every hour (up to {c.get('team_max', 3)} people). The finished building belongs to the yard's "
            "owner (home buildings) or to the village. Catalog: " + "; ".join(rows) + ".")


def view(world: World) -> dict:
    """Log fields for the viewer: `sites` (spec format) and common `buildings`."""
    if not enabled(world.config):
        return {}
    since = _since(world)
    return {"sites": [{"id": s["id"], "kind": s["kind"], "level": s["level"], "location": s["location"],
                       "done": done_share(s), "workers": sorted({n for t, n in s["recent"] if t >= since})}
                      for s in sites(world).values()],
            "buildings": [{"id": b["id"], "kind": b["kind"], "level": b["level"], "location": b["location"]}
                          for b in common(world)]}
