"""Village structures built together: well, bridge, watchtower, wall, each with levels 1..3.

Rules, in the order an agent meets them:
- The mayor can start building or upgrading a structure at any time with `propose_build` (no vote: the
  village votes with its hands). While there is no mayor (or no government), any villager can.
  If no project is open for `council_idle_days`, the village council suggests the cheapest next one.
- A project needs items (wood, stone, ...), coins and `labor` (hours of work). Villagers bring items and
  coins with `contribute` and work on it with `build_work` at the square; the mayor can pay from the
  treasury with `fund_project`. Every gift and every hour is public, and the finished project names who
  helped and who did not.
- A finished level is permanent and does something (config `works.catalog`): the well gives water at the
  square and, from level 2, slows fires; the bridge makes the trader pay more; the watchtower makes
  thefts easier to notice; the wall is the village's `defense` against raids.

This module imports no other game module except ops/registry/state/population, so actions.py, plots.py
and engine.py can call its effect helpers without import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, Field

from . import ops, population, progress
from .ops import Ctx, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, Project, World

SITE = "square"
NOT_ITEMS = ("labor", "coins")

# Other modules' buildings add to these effects: fn(world) -> number (construction.py: palisade, market square).
DEFENSE_SOURCES: list = []
SELL_BONUS_SOURCES: list = []


# ---------- queries and effects ----------

def _w(cfg: dict) -> dict:
    return cfg.get("works") or {}


def enabled(cfg: dict) -> bool:
    return bool(_w(cfg).get("enabled"))


WORKS = "feature:works"  # progress.DEFAULT_UNLOCKS: a town_hall


def catalog(cfg: dict) -> dict:
    return _w(cfg).get("catalog", {})


def level(world: World, structure: str) -> int:
    return world.works.levels.get(structure, 0)


def _per_level(world: World, structure: str, key: str) -> float:
    spec = catalog(world.config).get(structure) or {}
    return level(world, structure) * spec.get(key, 0)


def defense(world: World) -> int:
    """Village defense against raids: the wall's level times `defense_per_level` (0 without a wall)."""
    return int(_per_level(world, "wall", "defense_per_level")) + sum(int(f(world)) for f in DEFENSE_SOURCES)


def sell_factor(world: World, side: str) -> float:
    """Trader price multiplier from the bridge: more buyers come, so the trader pays more (side 'sell')."""
    if side != "sell":
        return 1.0
    return 1.0 + _per_level(world, "bridge", "sell_bonus_per_level") + sum(f(world) for f in SELL_BONUS_SOURCES)


def notice_bonus(world: World) -> float:
    """Added to steal_notice_chance: the watchtower's lookouts."""
    return _per_level(world, "watchtower", "notice_bonus_per_level")


def fire_grow_bonus(world: World) -> int:
    """Extra hours between fire growth steps: the well from level 2 (water is close at hand)."""
    spec = catalog(world.config).get("well") or {}
    return max(0, level(world, "well") - 1) * spec.get("fire_grow_hours_per_level", 0)


def remaining(p: Project) -> dict:
    return {k: v - p.contributed.get(k, 0) for k, v in p.needs.items() if p.contributed.get(k, 0) < v}


def open_projects(world: World) -> list[Project]:
    return [p for p in world.projects.values() if not p.done]


def needs_for(cfg: dict, structure: str, lvl: int) -> dict:
    need = dict(catalog(cfg)[structure]["levels"][lvl - 1])
    if (cfg.get("population") or {}).get("scale_projects", True):
        k = population.resource_scale(cfg)
        need = {i: max(1, round(q * k)) for i, q in need.items()}
    return need


def next_options(world: World) -> dict[str, int]:
    """Structures that can be started now -> the level the project would build."""
    busy = {p.structure for p in open_projects(world) if p.structure}
    return {s: level(world, s) + 1 for s, spec in catalog(world.config).items()
            if s not in busy and level(world, s) < len(spec["levels"])}


def _mayor(world: World) -> str | None:
    return world.governance.mayor if (world.config.get("governance") or {}).get("enabled") else None


@dataclass
class Holder:
    """Who pays from a treasury: the coin holder (`.coins`), how texts name it, and a callback that remembers a
    spend (what, coins) for those who keep its books (None: nothing to remember)."""
    purse: Any
    label: str
    note: Callable[[str, int], None] | None = None


# fn(world, name) -> Holder | None. polity.py: the holder of a polity's treasury.
HOLDERS: list = []


def holder(world: World, name: str) -> Holder | None:
    """The treasury `name` can pay from: the mayor's village treasury, or a polity's for its holder."""
    for fn in HOLDERS:
        if (h := fn(world, name)) is not None:
            return h
    if _mayor(world) == name and not (world.config.get("polity") or {}).get("enabled"):
        return Holder(world.governance, "the treasury")
    return None


def can_propose(world: World, name: str) -> bool:
    mayor = _mayor(world)
    return mayor == name if mayor else True


# ---------- actions ----------

class ProposeBuildArgs(BaseModel):
    structure: str = Field(description="well | bridge | watchtower | wall")


@ACTIONS.action("propose_build", "Mayor (anyone while there is no mayor): start building or upgrading a village "
                "structure (well, bridge, watchtower, wall). Villagers then contribute and build_work at the square.",
                ProposeBuildArgs,
                available=lambda c, a: enabled(c.cfg) and can_propose(c.world, a.name)
                and len(open_projects(c.world)) < _w(c.cfg).get("max_open", 2) and bool(next_options(c.world)))
def propose_build(ctx: Ctx, a: Agent, args: ProposeBuildArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        raise ActionError("this village does not build together")
    if not can_propose(w, a.name):
        raise ActionError(f"only the mayor ({_mayor(w)}) can start a village project")
    if len(open_projects(w)) >= _w(cfg).get("max_open", 2):
        raise ActionError(f"at most {_w(cfg).get('max_open', 2)} village projects can be open at once; "
                          "finish one first")
    opts = next_options(w)
    s = args.structure.strip().lower()
    if s not in opts:
        if s in catalog(cfg) and any(p.structure == s for p in open_projects(w)):
            raise ActionError(f"the {s} is already being built")
        if s in catalog(cfg):
            raise ActionError(f"the {s} is already at its highest level")
        raise ActionError(f"unknown structure '{args.structure}'; can build: {', '.join(sorted(opts))}")
    open_project(ctx, s, opts[s], a.name)


def open_project(ctx: Ctx, structure: str, lvl: int, by: str) -> Project:
    w, cfg = ctx.world, ctx.cfg
    spec = catalog(cfg)[structure]
    name = spec["name"] if lvl == 1 else f"{spec['name']} (level {lvl})"
    p = Project(f"{structure}_{lvl}", name, needs_for(cfg, structure, lvl), structure=structure, level=lvl,
                proposer=by, opened_day=w.day)
    w.projects[p.id] = p
    who = "The village council suggests" if by == "council" else \
        f"Mayor {by} starts" if by == _mayor(w) else f"{by} starts"
    ctx.emit("work_started", f"{who} a village project ({p.id}): {name}, {describe_effect(cfg, structure, lvl)} "
             f"It needs {fmt_items(p.needs)}. Bring items and coins with contribute and work with build_work "
             f"at the {SITE}.", actor=None if by == "council" else by, visibility="public", project=p.id,
             structure=structure, level=lvl)
    return p


def describe_effect(cfg: dict, structure: str, lvl: int) -> str:
    spec = catalog(cfg).get(structure, {})
    if structure == "well":
        if lvl == 1:
            return f"water can be drawn at the {spec.get('water_at', SITE)}."
        return f"fires spread {(lvl - 1) * spec.get('fire_grow_hours_per_level', 0)} hours slower."
    if structure == "bridge":
        return f"the trader pays {lvl * spec.get('sell_bonus_per_level', 0):.0%} more for what you sell."
    if structure == "watchtower":
        return f"thefts are noticed {lvl * spec.get('notice_bonus_per_level', 0):.0%} more often."
    if structure == "wall":
        return f"village defense {lvl * spec.get('defense_per_level', 0)} against raids."
    return ""


def _project(ctx: Ctx, pid: str) -> Project:
    p = ctx.world.projects.get(pid)
    if p is None or p.done:
        ids = ", ".join(x.id for x in open_projects(ctx.world)) or "none"
        raise ActionError(f"no open project '{pid}'; open: {ids}")
    return p


class BuildWorkArgs(BaseModel):
    project_id: str


@ACTIONS.action("build_work", "Work one hour on a village project at the square (it needs labor).", BuildWorkArgs,
                available=lambda c, a: a.location == SITE
                and any(remaining(p).get("labor") for p in open_projects(c.world)))
def build_work(ctx: Ctx, a: Agent, args: BuildWorkArgs) -> None:
    if a.location != SITE:
        raise ActionError(f"village projects are built at the {SITE}")
    p = _project(ctx, args.project_id)
    if not remaining(p).get("labor"):
        raise ActionError(f"{p.name} needs no more work; it still needs {fmt_items(remaining(p)) or 'nothing'}")
    if ctx.world.day < a.sick_until_day:
        raise ActionError("you are sick and cannot work")
    p.contributed["labor"] = p.contributed.get("labor", 0) + 1
    p.labor[a.name] = p.labor.get(a.name, 0) + 1
    p.contributors[a.name] = p.contributors.get(a.name, 0) + 1
    ctx.emit("build_work", f"{a.name} worked an hour on {p.name}.", actor=a.name, visibility="public", project=p.id)
    maybe_finish(ctx, p)


class FundArgs(BaseModel):
    project_id: str
    coins: int = Field(gt=0, le=10000)


@ACTIONS.action("fund_project", "Treasury holder only (the mayor, or whoever holds a polity's treasury): pay coins "
                "from the treasury into a village project.", FundArgs,
                available=lambda c, a: enabled(c.cfg) and (h := holder(c.world, a.name)) is not None
                and h.purse.coins > 0 and any(remaining(p).get("coins") for p in open_projects(c.world)))
def fund_project(ctx: Ctx, a: Agent, args: FundArgs) -> None:
    h = holder(ctx.world, a.name)
    if h is None:
        raise ActionError("only the mayor or a polity's treasury holder can pay from a treasury")
    p = _project(ctx, args.project_id)
    n = min(args.coins, remaining(p).get("coins", 0), h.purse.coins)
    if n <= 0:
        raise ActionError(f"{p.name} needs no coins" if not remaining(p).get("coins") else "the treasury is empty")
    ops.burn_coins(ctx.world, h.purse, n)  # paid to the hired craftsmen
    p.contributed["coins"] = p.contributed.get("coins", 0) + n
    if h.note:
        h.note(f"{p.name} (fund_project by {a.name})", n)
    who = f"Mayor {a.name}" if h.purse is ctx.world.governance else a.name
    ctx.emit("fund_project", f"{who} paid {n} coins from {h.label} into {p.name}.", actor=a.name,
             visibility="public", project=p.id, coins=n)
    maybe_finish(ctx, p)


def contribute(ctx: Ctx, a: Agent, p: Project, items: dict) -> dict:
    """actions.contribute: take what the project still needs from the agent (items and 'coins')."""
    left = remaining(p)
    if "labor" in items and len(items) == 1:
        raise ActionError("labor is given with build_work")
    useful = {k: min(v, left.get(k, 0)) for k, v in items.items() if k != "labor"}
    useful = {k: v for k, v in useful.items() if v > 0}
    if not useful:
        raise ActionError(f"{p.name} does not need that; it needs {fmt_items(left)}")
    if useful.get("coins", 0) > a.coins:
        raise ActionError(f"you have only {a.coins} coins")
    goods = {k: v for k, v in useful.items() if k != "coins"}
    if not ops.has_all(a.inventory, goods):
        raise ActionError(f"you do not have {fmt_items(goods)}")
    for k, v in goods.items():
        ops.burn(ctx.world, a.inventory, k, v)
    if useful.get("coins"):
        ops.burn_coins(ctx.world, a, useful["coins"])
    for k, v in useful.items():
        p.contributed[k] = p.contributed.get(k, 0) + v
    p.contributors[a.name] = p.contributors.get(a.name, 0) + sum(useful.values())
    return useful


def _split_by_work(cfg: dict) -> bool:
    return _w(cfg).get("reward_split") == "contribution"


def reward_pool(w: World, reward: int) -> int:
    return reward * sum(1 for o in w.agents.values() if o.status != "dead")


def reward_shares(w: World, p: Project, reward: int) -> dict[str, int]:
    """Coins each villager gets when `p` is done. "everyone" (default): `reward` to every living villager.
    "contribution" (`works.reward_split`, the crafts mode): the same pool (`reward` x the living) shared by what
    each one gave (items, coins and hours, as counted in `contributors`); the idle get nothing (economy audit:
    a bridge paid 20 to each of 6-7 villagers out of 10 who never brought a log)."""
    alive = {n for n, o in w.agents.items() if o.status != "dead"}
    if not reward:
        return {}
    if not _split_by_work(w.config):
        return {n: reward for n in sorted(alive)}
    given = {n: c for n, c in p.contributors.items() if n in alive and c > 0}
    total, pool = sum(given.values()), reward_pool(w, reward)
    if not total:
        return {}
    shares = {n: pool * c // total for n, c in given.items()}
    rest = pool - sum(shares.values())  # largest remainders first, then by name
    for n in sorted(given, key=lambda n: (-(pool * given[n] % total), n))[:rest]:
        shares[n] += 1
    return {n: c for n, c in sorted(shares.items()) if c}


def maybe_finish(ctx: Ctx, p: Project) -> None:
    if remaining(p):
        return
    w, cfg = ctx.world, ctx.cfg
    p.done = True
    w.works.quiet_since = w.day
    reward = cfg.get("projects", {}).get(p.id, {}).get("reward_coins_each", 0)
    shares = reward_shares(w, p, reward)
    for n, c in shares.items():
        ops.mint_coins(w, w.agents[n], c)
    helped = sorted(p.contributors, key=lambda n: (-p.contributors[n], n))
    idle = sorted(n for n, o in w.agents.items() if o.status == "active" and n not in p.contributors)
    text = f"{p.name} is finished!"
    if p.structure:
        w.works.levels[p.structure] = max(level(w, p.structure), p.level or 1)
        apply_level(w, p.structure)
        text += " " + describe_effect(cfg, p.structure, level(w, p.structure)).capitalize()
    if reward and _split_by_work(cfg):
        text += (f" The reward of {reward_pool(w, reward)} coins is shared by contribution: "
                 + (", ".join(f"{n} {c}" for n, c in sorted(shares.items(), key=lambda x: (-x[1], x[0])))
                    or "nobody") + ".")
    elif reward:
        text += f" Every villager receives {reward} coins."
    if helped:
        text += " Built by: " + ", ".join(f"{n} ({p.contributors[n]})" for n in helped) + "."
    if idle:
        text += " Did not help: " + ", ".join(idle) + "."
    ctx.emit("project_done", text, visibility="public", project=p.id, structure=p.structure,
             level=level(w, p.structure) if p.structure else None, helpers=dict(p.contributors), idle=idle)


def apply_level(w: World, structure: str) -> None:
    if structure == "well" and level(w, "well") >= 1:
        site = catalog(w.config)["well"].get("water_at", SITE)
        if site in w.locations:
            w.locations[site].resources["water"] = 999


# ---------- engine hooks ----------

def after_night(ctx: Ctx) -> None:
    if not enabled(ctx.cfg):
        return
    w = ctx.world
    apply_level(w, "well")  # the well refills overnight
    if not progress.unlocked(w, WORKS):  # «С нуля»: no village projects before a town hall
        return
    if open_projects(w):
        w.works.quiet_since = w.day
        return
    idle = _w(ctx.cfg).get("council_idle_days", 0)
    opts = next_options(w)
    if not idle or not opts or w.day - w.works.quiet_since < idle:
        return
    cost = {s: sum(needs_for(ctx.cfg, s, lvl).values()) for s, lvl in opts.items()}
    s = min(sorted(opts), key=lambda k: cost[k])
    open_project(ctx, s, opts[s], "council")


def board(world: World) -> list[dict]:
    return [{"id": p.id, "name": p.name, "needs": p.needs, "contributed": p.contributed,
             "still_needs": remaining(p), "helpers": dict(p.contributors),
             **({"structure": p.structure, "level": p.level, "started_by": p.proposer, "since_day": p.opened_day}
                if p.structure else {}), **_reward_note(world, p)}
            for p in open_projects(world)]


def _reward_note(world: World, p: Project) -> dict:
    """Shared by contribution, the reward is a rule people can act on, so the board says it."""
    reward = world.config.get("projects", {}).get(p.id, {}).get("reward_coins_each", 0)
    if not reward or not _split_by_work(world.config):
        return {}
    return {"reward_when_done": f"{reward_pool(world, reward)} coins, shared by how much each one gave"}


def observe(world: World, name: str) -> dict:
    if not enabled(world.config):
        return {}
    if not progress.unlocked(world, WORKS):  # «С нуля»: nothing can be started before a town hall
        built = {s: lvl for s in catalog(world.config) if (lvl := level(world, s))}
        return {"village_structures": {"built": built}} if built else {}
    return {"village_structures": {
        "built": {s: level(world, s) for s in catalog(world.config)},
        "can_start": {s: {"level": lvl, "needs": needs_for(world.config, s, lvl),
                          "effect": describe_effect(world.config, s, lvl)}
                      for s, lvl in next_options(world).items()},
        "you_can_start": can_propose(world, name),
    }}


def facts(cfg: dict) -> str:
    from .governance import opens_note, polity_on  # governance -> actions -> works: import here
    fund = ("; a polity's treasury holder can fund_project from its treasury" if polity_on(cfg)
            else "; the mayor can fund_project from the treasury")
    return (f"- Village structures{opens_note(cfg, WORKS)}: the mayor (anyone while there is no mayor) can propose_build a well, bridge, "
            "watchtower or wall, or upgrade one (levels 1-3). Each needs items, coins and labor: contribute items "
            f"and coins and build_work (one hour) at the square{fund}. "
            "Everyone sees who helped and who did not. Finished levels stay: well = water at the square, slower "
            "fires; bridge = the trader pays more; watchtower = thefts noticed more often; wall = defense against "
            "raids.")


def view(world: World) -> dict:
    return {"levels": dict(world.works.levels), "open": board(world)}
