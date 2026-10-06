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

Secret recipes (`crafting.secrets`, «С нуля» plan task 19; needs crafting on): a recipe not in `secrets.common`
is known only to whoever worked it out or was taught it (`Agent.known_recipes`). A recipe no living villager
knows can be worked out by the first who makes it (`discover_hours` more at the bench); once someone alive knows
it, others learn it only by `teach` (free at once, or for a price the learner pays with `learn`; the learner may
teach it on). With `rediscover` on, anyone may still work it out alone. Observation: `recipes_you_know`,
`lessons_offered`. Pending lessons: `Agent.lesson_offers` on the learner.
"""

from __future__ import annotations

import math
from typing import Annotated, Callable

from pydantic import BaseModel, Field

from . import clock, labor, ops, progress
from .ops import Ctx
from .registry import ACTIONS, ActionError
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
    discovering = False
    if secret(cfg, rid) and rid not in a.known_recipes:
        if (who := knowers(w, rid)) and not _s(cfg).get("rediscover"):
            raise ActionError(f"you do not know how to make {rid}; it is known to {', '.join(who)}, "
                              f"who can teach it")
        discovering = True
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
    if discovering:
        hours = max(hours, 1) + int(_s(cfg).get("discover_hours", 0))
        _learn(a, rid)
        ctx.emit("discover", f"{a.name} worked out how to make {rid}.", actor=a.name, location=a.location,
                 visibility="location", recipe=rid)
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
    out.update(_secrets_observe(world, a))
    here = workshops_at(world, a.location)
    if here:
        out["workshops_here"] = [{"kind": w["kind"], "owner": w["owner"] or "village",
                                  "you_may_use": _may_use(w, name)} for w in here]
        kinds = usable_kinds(world, a)
        crafts = {}
        for rid, r in cfg["recipes"].items():
            if (r.get("building") in kinds or set(r.get("more_at", {})) & kinds) \
                    and progress.unlocked(world, f"recipe:{rid}") and may_make(world, a, rid):
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
    if secrets_on(cfg):
        s = _s(cfg)
        common = [rid for rid in cfg["recipes"] if not secret(cfg, rid)]
        alone = ("anyone may also work it out alone the same way" if s.get("rediscover") else
                 "once someone alive knows it, others learn it only when someone who knows teaches them")
        lines.append(f"- Recipes known to everyone: {', '.join(common) or 'none'}. Every other recipe is known only "
                     f"to whoever worked it out or was taught it. A recipe no living villager knows is worked out by "
                     f"the first who makes it ({s.get('discover_hours', 0)} h more at it); {alone}. "
                     f"A villager who knows a recipe can teach it to a person here, free or for a price.")
    return lines


# ---------- secret recipes (task 19) ----------

def _s(cfg: dict) -> dict:
    return _c(cfg).get("secrets") or {}


def secrets_on(cfg: dict) -> bool:
    return enabled(cfg) and bool(_s(cfg).get("enabled"))


def secret(cfg: dict, rid: str) -> bool:
    """Is this recipe known only to some? (False with secrets off.)"""
    return secrets_on(cfg) and rid in cfg["recipes"] and rid not in _s(cfg).get("common", [])


def knowers(world: World, rid: str) -> list[str]:
    """Living villagers who know a secret recipe, by name."""
    return sorted(n for n, x in world.agents.items() if x.status != "dead" and rid in x.known_recipes)


def may_make(world: World, a: Agent, rid: str) -> bool:
    """Knowledge alone: known to everyone, known to `a`, or still free to work out."""
    cfg = world.config
    if not secret(cfg, rid) or rid in a.known_recipes:
        return True
    return bool(_s(cfg).get("rediscover")) or not knowers(world, rid)


def _learn(a: Agent, rid: str) -> None:
    if rid not in a.known_recipes:
        a.known_recipes = sorted([*a.known_recipes, rid])


def _open_lessons(world: World, a: Agent) -> list[dict]:
    """Lessons offered to `a` that have not run out (expired ones are dropped)."""
    a.lesson_offers = [o for o in a.lesson_offers if o["expires_tick"] > world.tick]
    return a.lesson_offers


def _price_text(price: dict) -> str:
    return ops.fmt_items(price) if price else "nothing"


def _secrets_observe(world: World, a: Agent) -> dict:
    if not secrets_on(world.config):
        return {}
    out: dict = {}
    if a.known_recipes:
        out["recipes_you_know"] = list(a.known_recipes)
    lessons = [o for o in a.lesson_offers if o["expires_tick"] > world.tick]
    if lessons:
        out["lessons_offered"] = [{"teacher": o["teacher"], "recipe": o["recipe"], "price": _price_text(o["price"])}
                                  for o in lessons]
    return out


Price = dict[str, Annotated[int, Field(gt=0, le=1000)]]


class TeachArgs(BaseModel):
    person: str = Field(description="a person here")
    recipe: str
    price: Price = Field(default_factory=dict, description="what they pay you to learn (items, 'coins' for money); "
                                                           "empty = free, they learn at once")


def _can_teach(ctx: Ctx, a: Agent) -> bool:
    return secrets_on(ctx.cfg) and bool(a.known_recipes)


@ACTIONS.action("teach", "Teach a person here a recipe you know. Free: they know it at once. With a price: they "
                "learn it when they pay it with learn.", TeachArgs, available=_can_teach)
def teach(ctx: Ctx, a: Agent, args: TeachArgs) -> None:
    cfg, w = ctx.cfg, ctx.world
    if not secrets_on(cfg):
        raise ActionError("every recipe here is known to everyone")
    other = w.agents.get(args.person)
    if other is None or other.status == "dead":
        raise ActionError(f"no villager named '{args.person}'")
    if other.name == a.name:
        raise ActionError("you cannot teach yourself")
    if other.location != a.location or other.status != "active":
        raise ActionError(f"{other.name} must be here to learn")
    if not secret(cfg, args.recipe):
        raise ActionError(f"'{args.recipe}' is not a recipe known only to some")
    if args.recipe not in a.known_recipes:
        raise ActionError(f"you do not know how to make {args.recipe}")
    if args.recipe in other.known_recipes:
        raise ActionError(f"{other.name} already knows {args.recipe}")
    for k in args.price:
        if k != "coins" and k not in cfg["items"]:
            raise ActionError(f"unknown item '{k}'")
    price = dict(args.price)
    if not price:
        _learn(other, args.recipe)
        ctx.emit("teach", f"{a.name} taught {other.name} how to make {args.recipe}.", actor=a.name,
                 location=a.location, visibility="location", to=[other.name], recipe=args.recipe,
                 learner=other.name, price={})
        return
    lessons = [o for o in _open_lessons(w, other) if not (o["teacher"] == a.name and o["recipe"] == args.recipe)]
    lessons.append({"teacher": a.name, "recipe": args.recipe, "price": price,
                    "expires_tick": w.tick + clock.hours(cfg, cfg["offer_ttl_ticks"])})
    other.lesson_offers = lessons
    ctx.emit("lesson_offer", f"{a.name} offers to teach you how to make {args.recipe} for {_price_text(price)} "
             f"(learn to accept).", actor=a.name, to=[other.name], recipe=args.recipe, price=price)
    ctx.emit("lesson_offer", f"You offered to teach {other.name} how to make {args.recipe} for "
             f"{_price_text(price)}.", actor=a.name, to=[a.name], recipe=args.recipe, price=price)


class LearnArgs(BaseModel):
    teacher: str
    recipe: str


@ACTIONS.action("learn", "Pay the price of a lesson offered to you and learn the recipe. The teacher must be here.",
                LearnArgs, available=lambda c, a: secrets_on(c.cfg) and bool(_open_lessons(c.world, a)))
def learn(ctx: Ctx, a: Agent, args: LearnArgs) -> None:
    w = ctx.world
    lesson = next((o for o in _open_lessons(w, a) if o["teacher"] == args.teacher and o["recipe"] == args.recipe),
                  None)
    if lesson is None:
        raise ActionError(f"no open lesson from '{args.teacher}' on '{args.recipe}' for you")
    t = w.agents[lesson["teacher"]]
    if t.status != "active" or t.location != a.location:
        raise ActionError(f"{t.name} must be here to teach you")
    if args.recipe not in t.known_recipes:
        a.lesson_offers.remove(lesson)
        raise ActionError(f"{t.name} does not know {args.recipe}; lesson cancelled")
    price = lesson["price"]
    goods = {k: v for k, v in price.items() if k != "coins"}
    if not ops.has_all(a.inventory, goods) or a.coins < price.get("coins", 0):
        raise ActionError(f"the lesson costs {_price_text(price)}; you do not have it")
    ops.move_items(a.inventory, t.inventory, goods)
    ops.move_coins(a, t, price.get("coins", 0))
    a.lesson_offers.remove(lesson)
    _learn(a, args.recipe)
    ctx.emit("teach", f"{t.name} taught {a.name} how to make {args.recipe} for {_price_text(price)}.",
             actor=a.name, location=a.location, visibility="location", to=[t.name], recipe=args.recipe,
             learner=a.name, teacher=t.name, price=price)
