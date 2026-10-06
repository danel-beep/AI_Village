"""Crafting chains, workshops and tools (config block `crafting`, off by default; «С нуля» plan, task 7).

Off, nothing changes: `cfg["recipes"]` and the one generic `tool` work as in every mode before. On:

- the recipes of `crafting.recipes` join `cfg["recipes"]` at config time (`resolve`, idempotent like
  population.resolve), so raw goods become materials (wood -> plank, clay -> brick, ore -> iron, hide ->
  leather, grain -> flour) and materials become tools and food (bread now needs flour);
- a recipe with `building` is made only where a workshop of that kind stands (`workshops_at`), and only by
  someone who may use it: a workshop in a private yard serves its owner's household, a village one everyone.
  `more_at` gives a by-hand recipe a bigger batch at a workshop (a mill grinds more flour). "At home" recipes
  can also be made by a campfire (`home_also_at`). A recipe locked by progress (`recipe:<id>`) is refused;
  recipes that need a workshop register `{"building": kind}` in progress.DEFAULT_UNLOCKS below;
- tools (`crafting.tools`): the carried tool with the highest multiplier that fits a resource is used for an
  hour of work and wears out after its `hours`; `needs_tool` resources cannot be gathered by hand;
- the owner of a workshop with a trade (`workshops`: smithy -> smith ...) takes that trade if they have none
  (labor.workshop_trades, checked every hour).

Workshops are found in private yards (`Plot.buildings`, owner = plot owner), in fixed map locations whose id
is a workshop kind (today's `smithy`, owner None), in `world.construction["buildings"]` (construction.py:
{kind, level, location, owner}) and in any `WORKSHOP_SOURCES` a later module appends
(`fn(world, location) -> [{"kind", "owner", "level", "users"?}]`; `users` None = everyone).
Observation (on): `tools` (wear left), `workshops_here`, `crafts_here`. Prompt facts: `facts(cfg)`.
State: `Agent.tool_wear_by` (hours of use per tool kind; the generic `tool` keeps `Agent.tool_wear`).
"""

from __future__ import annotations

import math
from typing import Callable

from . import labor, ops, progress
from .ops import Ctx
from .registry import ActionError
from .state import Agent, World

WORKSHOP_SOURCES: list[Callable[[World, str], list[dict]]] = []


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("crafting", {}).get("enabled"))


def _c(cfg: dict) -> dict:
    return cfg["crafting"]


# ---------- config ----------

def _normalize(rid: str, r: dict, workshops: dict) -> dict:
    r = dict(r)
    r.setdefault("output", 1)
    r.setdefault("profession", None)
    r.setdefault("hours", 0)
    if not r.get("building") and r.get("where") in workshops:  # legacy: "made at the smithy"
        r["building"] = r["where"]
    r.setdefault("building", None)
    r["where"] = r["building"] or r.get("where") or "anywhere"
    return r


def resolve(cfg: dict) -> dict:
    """Called by config.make_config: merge crafting items and recipes into the global tables. Idempotent: a
    replayed log header (already merged) goes through make_config again, over the defaults, and comes out the same."""
    c = cfg.get("crafting") or {}
    if not c.get("enabled"):
        return cfg
    for item, spec in c.get("items", {}).items():
        cfg["items"].setdefault(item, dict(spec))
    shops = c.get("workshops", {})
    for rid, r in c.get("recipes", {}).items():
        cfg["recipes"][rid] = {**cfg["recipes"].get(rid, {}), **r}  # inputs replaced whole, not merged
    cfg["recipes"] = {rid: _normalize(rid, r, shops) for rid, r in cfg["recipes"].items()}
    for prof in shops.values():
        if prof:
            cfg["professions"].setdefault(prof, [])
    return cfg


def _register_unlocks() -> None:
    """Workshop recipes open with their workshop when progress is on."""
    from .config import DEFAULT_CONFIG
    c = DEFAULT_CONFIG["crafting"]
    every = {**DEFAULT_CONFIG["recipes"], **c["recipes"]}
    for rid, r in every.items():
        kind = r.get("building") or (r.get("where") if r.get("where") in c["workshops"] else None)
        if kind:
            progress.DEFAULT_UNLOCKS.setdefault(f"recipe:{rid}", {"building": kind})


_register_unlocks()


def makes(cfg: dict, kind: str) -> list[str]:
    """Recipes a workshop kind makes (or makes more of): for building catalogues and the prompt."""
    return [rid for rid, r in cfg["recipes"].items() if r.get("building") == kind or kind in r.get("more_at", {})]


# ---------- workshops ----------

def workshops_at(world: World, location: str) -> list[dict]:
    """Workshops standing at a location: [{"kind", "owner", "level", "users"}] (`users` None = everyone)."""
    cfg = world.config
    kinds = _c(cfg).get("workshops", {})
    out: list[dict] = []
    if location in kinds and location in world.locations:
        out.append({"kind": location, "owner": None, "level": 1, "users": None})
    plot = world.plots.get(location)
    if plot is not None and plot.owner:
        from . import plots
        users = plots.household(world, plot)
        for b in plot.buildings:
            if b["kind"] in kinds:
                out.append({"kind": b["kind"], "owner": plot.owner, "level": int(b.get("level", 1)), "users": users})
    for b in _constructed(world):  # construction.py (task 3): finished buildings with a place and an owner
        if b.get("location") == location and b.get("kind") in kinds:
            owner = b.get("owner")
            out.append({"kind": b["kind"], "owner": owner, "level": int(b.get("level", 1)),
                        "users": _household(world, owner) if owner else None})
    for fn in WORKSHOP_SOURCES:
        out.extend(fn(world, location))
    return out


def _constructed(world: World) -> list[dict]:
    return list((getattr(world, "construction", None) or {}).get("buildings", []))


def _household(world: World, owner: str) -> list[str]:
    spouses = {n for m in world.kin.marriages.values() if owner in m.spouses for n in m.spouses}
    return sorted({owner} | spouses)


def owned_workshops(world: World) -> list[tuple[str, str]]:
    """(owner, kind) of every private workshop, in a stable order."""
    kinds = _c(world.config).get("workshops", {})
    out = []
    for home in sorted(world.plots):
        plot = world.plots[home]
        out += [(plot.owner, b["kind"]) for b in plot.buildings if plot.owner and b["kind"] in kinds]
    out += [(b["owner"], b["kind"]) for b in _constructed(world) if b.get("owner") and b.get("kind") in kinds]
    for loc in sorted(world.locations):
        for fn in WORKSHOP_SOURCES:
            out += [(w["owner"], w["kind"]) for w in fn(world, loc) if w.get("owner")]
    return out


def _may_use(w: dict, name: str) -> bool:
    return w.get("users") is None or name in w["users"]


def usable_kinds(world: World, a: Agent) -> set[str]:
    return {w["kind"] for w in workshops_at(world, a.location) if _may_use(w, a.name)}


# ---------- crafting ----------

def _ins(r: dict) -> str:
    return " + ".join(f"{n} {k}" for k, n in r["inputs"].items())


def _output(r: dict, kinds: set[str]) -> int:
    more = [n for k, n in r.get("more_at", {}).items() if k in kinds]
    return max([r["output"], *more])


def where_error(world: World, a: Agent, rid: str, r: dict) -> str | None:
    """Why `a` cannot make recipe `rid` where they stand (None = they can)."""
    c = _c(world.config)
    if r["where"] == "home":
        if a.location == a.home or usable_kinds(world, a) & set(c.get("home_also_at", [])):
            return None
        also = " or by a " + " or a ".join(c["home_also_at"]) if c.get("home_also_at") else ""
        return f"{rid} is made at your home{also}"
    kind = r.get("building")
    if kind:
        here = [w for w in workshops_at(world, a.location) if w["kind"] == kind]
        if not here:
            return f"{rid} is made at a {kind}; there is no {kind} here"
        if not any(_may_use(w, a.name) for w in here):
            return f"the {kind} here belongs to {here[0]['owner']}; only their household uses it"
        return None
    if r["where"] not in ("anywhere", "") and a.location != r["where"]:
        return f"{rid} can only be made at the {r['where']}"
    return None


def craft(ctx: Ctx, a: Agent, rid: str, times: int) -> None:
    """The `craft` action with crafting on (actions.craft hands over here)."""
    cfg, w = ctx.cfg, ctx.world
    r = cfg["recipes"].get(rid)
    known = [k for k in cfg["recipes"] if progress.unlocked(w, f"recipe:{k}")]
    if r is None:
        raise ActionError(f"unknown recipe '{rid}'; known: {', '.join(known)}")
    if rid not in known:
        raise ActionError(f"nobody in the village can make {rid} yet; known: {', '.join(known)}")
    if why := where_error(w, a, rid, r):
        raise ActionError(why)
    if r["profession"] and a.profession != r["profession"]:
        raise ActionError(f"only a {r['profession']} can make {rid}")
    need = {k: v * times for k, v in r["inputs"].items()}
    missing = {k: v - ops.count(a.inventory, k) for k, v in need.items() if ops.count(a.inventory, k) < v}
    if missing:
        raise ActionError(f"{rid} x{times} needs {ops.fmt_items(need)}; you lack {ops.fmt_items(missing)}")
    for k, v in need.items():
        ops.burn(w, a.inventory, k, v)
    out = _output(r, usable_kinds(w, a)) * times
    ops.mint(w, a.inventory, rid, out)
    hours = int(r.get("hours") or 0) * times  # 0: any batch fits in the action's hour
    if hours > 1:
        a.task = {"kind": "craft", "recipe": rid, "hours_left": hours - 1}
    ctx.emit("craft", f"{a.name} made {out} {rid}.", actor=a.name, location=a.location,
             visibility="location", recipe=rid, amount=out)


def continue_task(ctx: Ctx, a: Agent) -> None:
    """engine.continue_task: one more hour at the bench (the goods were made when the batch started)."""
    a.task["hours_left"] -= 1
    if a.task["hours_left"] <= 0:
        a.task = None


# ---------- tools ----------

def _tools(cfg: dict) -> dict:
    return _c(cfg).get("tools", {})


def durability(cfg: dict, tool: str) -> int:
    h = _tools(cfg)[tool].get("hours")
    return int(h if h is not None else cfg["tool_durability_hours"])


def tool_for(cfg: dict, a: Agent, resource: str) -> tuple[str | None, float]:
    """The carried tool used for an hour of `resource` (highest multiplier, ties by name) and its multiplier."""
    best: tuple[str | None, float] = (None, 1.0)
    for t in sorted(_tools(cfg)):
        spec = _tools(cfg)[t]
        if ops.count(a.inventory, t) <= 0 or not ("*" in spec["fits"] or resource in spec["fits"]):
            continue
        if best[0] is None or spec["multiplier"] > best[1]:
            best = (t, float(spec["multiplier"]))
    return best


def scale(amount: int, multiplier: float) -> int:
    return int(math.floor(amount * multiplier + 0.5))


def missing_tool(cfg: dict, a: Agent, resource: str) -> str | None:
    if resource not in _c(cfg).get("needs_tool", []) or tool_for(cfg, a, resource)[0]:
        return None
    fits = [t for t, s in sorted(_tools(cfg).items()) if resource in s["fits"] or "*" in s["fits"]]
    return f"{resource} is not gathered by hand; it takes one of: {', '.join(fits)}"


def wear(ctx: Ctx, a: Agent, tool: str | None) -> None:
    """One hour of use; the tool breaks at its durability."""
    if tool is None:
        return
    used = (a.tool_wear if tool == "tool" else a.tool_wear_by.get(tool, 0)) + 1
    if used >= durability(ctx.cfg, tool):
        used = 0
        ops.burn(ctx.world, a.inventory, tool, 1)
        ctx.emit("tool_broke", f"Your {tool} wore out and broke.", to=[a.name], tool=tool)
    if tool == "tool":
        a.tool_wear = used
    elif used:
        a.tool_wear_by[tool] = used
    else:
        a.tool_wear_by.pop(tool, None)


# ---------- hourly, observation, facts ----------

def end_of_hour(ctx: Ctx) -> None:
    if not enabled(ctx.cfg) or not _c(ctx.cfg).get("owner_takes_trade", True):
        return
    labor.workshop_trades(ctx, owned_workshops(ctx.world))


def observe(world: World, name: str) -> dict:
    cfg = world.config
    if not enabled(cfg):
        return {}
    a = world.agents[name]
    out: dict = {}
    tools = {}
    for t in sorted(_tools(cfg)):
        if ops.count(a.inventory, t) > 0:
            used = a.tool_wear if t == "tool" else a.tool_wear_by.get(t, 0)
            tools[t] = f"{durability(cfg, t) - used} of {durability(cfg, t)} work hours left in the one in use"
    if tools:
        out["tools"] = tools
    here = workshops_at(world, a.location)
    if here:
        out["workshops_here"] = [{"kind": w["kind"], "owner": w["owner"] or "village",
                                  "you_may_use": _may_use(w, name)} for w in here]
        kinds = usable_kinds(world, a)
        crafts = {}
        for rid, r in cfg["recipes"].items():
            if (r.get("building") in kinds or set(r.get("more_at", {})) & kinds) \
                    and progress.unlocked(world, f"recipe:{rid}"):
                crafts[rid] = f"{_ins(r)} -> {_output(r, kinds)} {rid}"
        if crafts:
            out["crafts_here"] = crafts
    return out


def facts(cfg: dict) -> list[str]:
    """Prompt cheat-sheet lines (llm.world_facts) with crafting on: recipes, workshops, tools."""
    hand, shop = [], []
    for rid, r in cfg["recipes"].items():
        who = f", only a {r['profession']}" if r["profession"] else ""
        more = "".join(f", {n} at a {k}" for k, n in r.get("more_at", {}).items())
        hrs = f", {r['hours']} h each" if (r.get("hours") or 0) > 1 else ""
        line = f"{rid}: {_ins(r)} -> {r['output']}{more}{who}{hrs}"
        if r.get("building"):
            shop.append(f"{line} (at a {r['building']})")
        else:
            hand.append(line + (" (at home)" if r["where"] == "home" else ""))
    c = _c(cfg)
    lines = [f"- Craft by hand: {'; '.join(hand)}."]
    if shop:
        lines.append(f"- Craft at a workshop (a workshop in a private yard serves its owner's household): "
                     f"{'; '.join(shop)}.")
    if c.get("home_also_at"):
        lines.append(f"- Recipes made at home can also be made by a {' or a '.join(c['home_also_at'])}.")
    trades = ", ".join(f"{k} -> {p}" for k, p in c.get("workshops", {}).items() if p)
    if trades and c.get("owner_takes_trade", True):
        lines.append(f"- The owner of a workshop without a trade takes its trade: {trades}.")
    tl = []
    for t, s in _tools(cfg).items():
        fits = ", ".join(s["fits"]).replace("*", "everything")
        what = f"x{s['multiplier']} for {fits}" if s["multiplier"] != 1 else f"sowing {fits} (the bed's tool bonus)"
        tl.append(f"{t} {what}, {durability(cfg, t)} h")
    lines.append(f"- Tools (of the carried ones that fit, the one with the highest multiplier is used; it breaks "
                 f"after its hours of work): {'; '.join(tl)}.")
    if c.get("needs_tool"):
        lines.append(f"- Not gathered by hand: {', '.join(c['needs_tool'])}.")
    return lines
