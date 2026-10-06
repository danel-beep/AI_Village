"""Division of labour (config block `labor`, off by default; the "crafts" economy mode turns it on).

The final live run showed why villagers never needed each other: anyone could gather anything (a profession
only made it 3x faster) and the trader bought and sold any amount at any time, so every villager lived alone
with the trader as the only partner. This module makes neighbours necessary through world rules only:

- own trade: only a villager whose profession owns a good (config `professions`) gathers it, and only a
  farmer sows grain; goods no profession owns (berries, water) stay open to everyone;
- limited time: at most `work_hours_per_day` hours of work a day, so nobody can do every job;
- skill: hours worked at your own trade raise your level (`skill_levels`), each level gives `skill_bonus`
  more units per hour, so specialists get better than anyone else could be;
- a limited trader: each day he buys at most `trader_buys_per_day` of each item from the whole village and
  sells at most `trader_sells_per_day` (per 5 villagers), first come first served.

State: `Agent.worked_today`, `Agent.skill_hours`, `World.trader_day` (reset at dawn by `new_day`).
"""

from __future__ import annotations

import math

from . import population
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, World


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("labor", {}).get("enabled"))


def _own_trade(cfg: dict) -> bool:
    return enabled(cfg) and cfg["labor"].get("own_trade_only", True)


def trade_of(cfg: dict, resource: str) -> list[str]:
    """Professions that own this good ([] = free for everyone)."""
    return [p for p, goods in cfg["professions"].items() if resource in goods]


def may_gather(cfg: dict, a: Agent, resource: str) -> str | None:
    """Why `a` may not gather `resource` under the own-trade rule, or None."""
    if not _own_trade(cfg):
        return None
    owners = trade_of(cfg, resource)
    if owners and a.profession not in owners:
        return f"only a {' or a '.join(owners)} can gather {resource}"
    return None


def free_goods(cfg: dict, a: Agent, here: list[str]) -> list[str]:
    return [r for r in here if may_gather(cfg, a, r) is None]


# ---------- time and skill ----------

def hours_left(cfg: dict, a: Agent) -> int | None:
    """Hours of work `a` may still do today (None = no limit)."""
    cap = cfg["labor"].get("work_hours_per_day", 0) if enabled(cfg) else 0
    return max(0, cap - a.worked_today) if cap else None


def level(cfg: dict, hours: int) -> int:
    return sum(hours >= h for h in cfg["labor"]["skill_levels"])


def is_own(cfg: dict, a: Agent, resource: str) -> bool:
    return resource in cfg["professions"].get(a.profession, [])


def bonus(cfg: dict, a: Agent, resource: str) -> int:
    """Extra units per hour of work from skill (own trade only)."""
    if not enabled(cfg) or not is_own(cfg, a, resource):
        return 0
    return level(cfg, a.skill_hours) * cfg["labor"]["skill_bonus"]


def after_work_hour(ctx: Ctx, a: Agent, resource: str) -> None:
    """Count one hour of work: today's hours and, at one's own trade, skill (with a level-up message)."""
    cfg = ctx.cfg
    if not enabled(cfg) or resource == "water":
        return
    a.worked_today += 1
    if is_own(cfg, a, resource):
        before = level(cfg, a.skill_hours)
        a.skill_hours += 1
        now = level(cfg, a.skill_hours)
        if now > before:
            ctx.emit("skill_up", f"{a.name} is now a level-{now} {a.profession}: +{now * cfg['labor']['skill_bonus']} "
                     f"per hour of work.", actor=a.name, visibility="public", level=now)


def skill_info(cfg: dict, a: Agent) -> dict:
    lv = level(cfg, a.skill_hours)
    steps = cfg["labor"]["skill_levels"]
    out = {"level": lv, "hours_at_your_trade": a.skill_hours, "extra_per_hour": lv * cfg["labor"]["skill_bonus"]}
    if lv < len(steps):
        out["next_level_after_hours"] = steps[lv]
    return out


# ---------- the trader's daily limits ----------

def quota(cfg: dict, item: str, side: str) -> int | None:
    """How many of `item` the trader buys ("buy") or sells ("sell") a day for the whole village (None = any)."""
    if not enabled(cfg):
        return None
    table = cfg["labor"].get("trader_buys_per_day" if side == "buy" else "trader_sells_per_day") or {}
    base = table.get(item, table.get("default"))
    if base is None:
        return None
    return math.ceil(base * population.resource_scale(cfg))


def trader_left(world: World, item: str, side: str) -> int | None:
    q = quota(world.config, item, side)
    if q is None:
        return None
    done = world.trader_day["bought" if side == "buy" else "sold"].get(item, 0)
    return max(0, q - done)


def trader_deal(world: World, item: str, qty: int, side: str) -> None:
    """Check and count a deal. side "buy": the trader buys from a villager (villager sells);
    "sell": the trader sells to a villager. Raises ActionError when today's limit is reached."""
    left = trader_left(world, item, side)
    if left is None:
        return
    if qty > left:
        what = "buy" if side == "buy" else "sell"
        raise ActionError(f"today the trader will {what} only {left} more {item} (limit {quota(world.config, item, side)}"
                          f" a day for the whole village; it resets at dawn)")
    book = world.trader_day["bought" if side == "buy" else "sold"]
    book[item] = book.get(item, 0) + qty


def new_day(world: World) -> None:
    world.trader_day = {"bought": {}, "sold": {}}
    for a in world.agents.values():
        a.worked_today = 0


# ---------- guard, observation, prompt, viewer ----------

def _sow_guard(ctx: Ctx, a: Agent | None, name: str) -> str | None:
    if name == "plant" and a is not None and may_gather(ctx.cfg, a, "grain"):
        return may_gather(ctx.cfg, a, "grain").replace("gather", "sow")
    return None


ACTIONS.guards.append(_sow_guard)


def observe(world: World, name: str) -> dict:
    cfg = world.config
    if not enabled(cfg):
        return {}
    a = world.agents[name]
    items = [i for i, v in cfg["items"].items() if v.get("tradable", True)]
    return {
        "work_today": {"hours_left": hours_left(cfg, a), "your_skill": skill_info(cfg, a)},
        "trader_today": {"will_buy": {i: trader_left(world, i, "buy") for i in items},
                         "has_for_sale": {i: trader_left(world, i, "sell") for i in items}},
    }


def facts(cfg: dict) -> str:
    lab = cfg["labor"]
    lines = []
    if lab.get("own_trade_only", True):
        owned = "; ".join(f"{p}: {', '.join(g)}" for p, g in cfg["professions"].items() if g)
        free = sorted({r for l in cfg["locations"].values() for r in l.get("resources", {})}
                      - {r for g in cfg["professions"].values() for r in g})
        lines.append(f"- Trades: only a villager of that profession can gather (or sow) these goods: {owned}. "
                     f"Free for everyone: {', '.join(free)}.")
    if lab.get("work_hours_per_day"):
        lines.append(f"- You can work (gather) at most {lab['work_hours_per_day']} hours a day.")
    steps = lab["skill_levels"]
    lines.append(f"- Skill: hours of work at your own trade raise your level (level 1/2/3 after "
                 f"{'/'.join(map(str, steps))} hours); each level gives +{lab['skill_bonus']} per hour of work.")
    buy, sell = lab.get("trader_buys_per_day") or {}, lab.get("trader_sells_per_day") or {}
    if buy or sell:
        lines.append("- The trader deals in limited amounts each day for the whole village (first come, first "
                     "served; resets at dawn): \"trader_today\" shows how many of each item he will still buy "
                     "and still has for sale today.")
    return "\n".join(lines)


def view(world: World) -> dict:
    """Viewer: each villager's skill level and hours worked today; the trader's limits left today."""
    cfg = world.config
    if not enabled(cfg):
        return {}
    return {"skills": {a.name: {"level": level(cfg, a.skill_hours), "hours": a.skill_hours,
                                "worked_today": a.worked_today} for a in world.agents.values()},
            "trader_day": world.trader_day}
