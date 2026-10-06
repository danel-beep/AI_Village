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
  sells at most `trader_sells_per_day` (per 5 villagers), first come first served;
- one purse per trade: with `trader_coins_per_trade` he also spends at most that many coins a day (per 5
  villagers) on the goods of one trade, so the miner's stone, ore and gold share one budget instead of
  three item limits (the economy audit: three limits made miners 4.5x richer than anyone else).

With village stages on (progress.py, the «С нуля» mode) the trader comes once a market square stands
(`feature:trader`): until then there are no trader prices or limits in the observation, so the only trade is
between villagers (the buy/sell actions are locked by progress itself).

State: `Agent.worked_today`, `Agent.skill_hours`, `World.trader_day` (reset at dawn by `new_day`).
"""

from __future__ import annotations

import math

from . import population, progress
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, World


TRADER = "feature:trader"  # progress.DEFAULT_UNLOCKS: a market_square


def trader_here(world: World) -> bool:
    """Has the trader come to the village? Always with village stages off."""
    return progress.unlocked(world, TRADER)


def trader_fact(cfg: dict) -> str:
    from .governance import opens_note  # governance -> actions -> labor: import here
    return (f"- The trader{opens_note(cfg, TRADER)} is only at the market. trader_prices \"a/b\" means you BUY from the "
            "trader at a coins, SELL to the trader at b coins. Coins only enter the village when someone sells to the "
            "trader.")


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
    if owners and a.profession == "laborer" and resource in cfg["labor"].get("laborer_goods", []):
        return None  # a laborer without a place gathers these too, at the base rate (no skill)
    if owners and a.profession not in owners:
        return f"only a {' or a '.join(owners)} can gather {resource}"
    return None


def laborer_text(cfg: dict) -> str:
    """What a villager without a trade place may do, for the rules line."""
    extra = cfg["labor"].get("laborer_goods") or []
    return f"free goods, {', '.join(extra)} and village work" if extra else "free goods and village work only"


def free_goods(cfg: dict, a: Agent, here: list[str]) -> list[str]:
    return [r for r in here if may_gather(cfg, a, r) is None]


def trade_anywhere(cfg: dict) -> bool:
    """`accept` works from anywhere: the goods of a trade are carried both ways, like a delivered order."""
    return enabled(cfg) and bool(cfg["labor"].get("trade_anywhere"))


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
        a.trade_day = ctx.world.day  # places.py: work at one's own trade keeps the place
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


def purse_of(cfg: dict, item: str) -> str | None:
    """The trade whose purse pays for `item` (its first owner in `professions`), None for goods nobody owns."""
    return (trade_of(cfg, item) or [None])[0]


def coins_left(world: World, trade: str | None) -> int | None:
    """Coins the trader will still pay today for the goods of `trade` (None = no purse for it)."""
    cfg = world.config
    per = cfg["labor"].get("trader_coins_per_trade")
    if not enabled(cfg) or not per or trade is None:
        return None
    cap = math.ceil(per * population.resource_scale(cfg))
    return max(0, cap - world.trader_day.get("spent", {}).get(trade, 0))


def trader_left(world: World, item: str, side: str) -> int | None:
    q = quota(world.config, item, side)
    left = None if q is None else max(0, q - world.trader_day["bought" if side == "buy" else "sold"].get(item, 0))
    purse = coins_left(world, purse_of(world.config, item)) if side == "buy" else None
    if purse is None:
        return left
    from . import pricing  # pricing imports works, which imports actions
    n, cap = 0, 99 if left is None else left
    while n < cap and pricing.total(world, item, "sell", n + 1) <= purse:
        n += 1
    return n


def trader_deal(world: World, item: str, qty: int, side: str, coins: int = 0) -> None:
    """Check and count a deal. side "buy": the trader buys from a villager (villager sells) for `coins`;
    "sell": the trader sells to a villager. Raises ActionError when today's limit is reached."""
    left = trader_left(world, item, side)
    if left is None:
        return
    if qty > left:
        what = "buy" if side == "buy" else "sell"
        trade = purse_of(world.config, item) if side == "buy" else None
        purse = coins_left(world, trade)
        if purse is not None:
            goods = ", ".join(world.config["professions"][trade])
            raise ActionError(f"today the trader will buy only {left} more {item}: he spends at most "
                              f"{purse} more coins on {trade} goods ({goods}) today for the whole village; "
                              f"it resets at dawn")
        raise ActionError(f"today the trader will {what} only {left} more {item} (limit {quota(world.config, item, side)}"
                          f" a day for the whole village; it resets at dawn)")
    book = world.trader_day["bought" if side == "buy" else "sold"]
    book[item] = book.get(item, 0) + qty
    trade = purse_of(world.config, item) if side == "buy" else None
    if coins_left(world, trade) is not None:
        spent = world.trader_day.setdefault("spent", {})
        spent[trade] = spent.get(trade, 0) + coins


def workshop_trades(ctx: Ctx, owned: list[tuple[str, str]]) -> None:
    """crafting.end_of_hour: the owner of a workshop who has no trade yet takes the workshop's trade
    (config `crafting.workshops`: smithy -> smith ...). The first workshop in `owned` order decides."""
    c = ctx.cfg["crafting"]
    untrained = set(c.get("untrained", []))
    for owner, kind in owned:
        a = ctx.world.agents.get(owner)
        trade = c["workshops"].get(kind)
        if not trade or a is None or a.status == "dead" or (a.profession or "") not in untrained:
            continue
        a.profession, a.skill_hours = trade, 0
        ctx.emit("trade_changed", f"{a.name} took the {trade} trade with the {kind}.", actor=a.name,
                 profession=trade, workshop=kind)


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
    out = {"work_today": {"hours_left": hours_left(cfg, a), "your_skill": skill_info(cfg, a)}}
    if trader_here(world):
        out["trader_today"] = {"will_buy": {i: trader_left(world, i, "buy") for i in items},
                               "has_for_sale": {i: trader_left(world, i, "sell") for i in items}}
    return out


def facts(cfg: dict) -> str:
    lab = cfg["labor"]
    lines = []
    if lab.get("own_trade_only", True):
        owned = "; ".join(f"{p}: {', '.join(g)}" for p, g in cfg["professions"].items() if g)
        free = sorted({r for l in cfg["locations"].values() for r in l.get("resources", {})}
                      - {r for g in cfg["professions"].values() for r in g})
        lines.append(f"- Trades: only a villager of that profession can gather (or sow) these goods: {owned}. "
                     f"Free for everyone: {', '.join(free)}.")
    if lab.get("trade_anywhere"):
        lines.append("- Trades are carried: an offer can be accepted from anywhere and the goods change hands at once.")
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
    if lab.get("trader_coins_per_trade"):
        lines.append("- He spends a limited number of coins a day on the goods of each trade, shared by all "
                     "its goods (a miner's stone, ore and gold come out of one purse).")
    return "\n".join(lines)


def view(world: World) -> dict:
    """Viewer: each villager's skill level and hours worked today; the trader's limits left today."""
    cfg = world.config
    if not enabled(cfg):
        return {}
    return {"skills": {a.name: {"level": level(cfg, a.skill_hours), "hours": a.skill_hours,
                                "worked_today": a.worked_today} for a in world.agents.values()},
            "trader_day": world.trader_day}
