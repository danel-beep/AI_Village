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

No professions (`labor.mastery`, the «С нуля» mode; Danel 2026-10-08): nobody has a trade, everyone gathers and
makes everything, and the reasons to split the work come from the world again:

- mastery per kind of work: every hour of fishing, farming, smithing ... raises that kind's own level
  (`mastery.levels`); a level gives more per hour of gathering, more items per craft, more grain per garden
  bed, a surer strike at a hunt. With `work_hours_per_day` nobody reaches a high level in everything, so doing
  one thing a lot and swapping for the rest pays; a kind of work left alone for days is slowly forgotten;
- a bigger house, a better household: each house level gives `house_bonus_pct`% more from one's own yard
  (garden beds, animals) and from what one makes at home or at one's own workshop;
- everyone sees who is best at what (`villagers[].best_at`), the way a village knows its fisherman.

State: `Agent.worked_today`, `Agent.skill_hours`, `Agent.mastery` / `practiced` / `carry`, `World.trader_day`
(reset at dawn by `new_day`).
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


def no_professions(cfg: dict) -> bool:
    """Everyone does everything; skill is mastery per kind of work (config `labor.mastery`)."""
    return enabled(cfg) and bool(cfg["labor"].get("mastery", {}).get("enabled"))


VILLAGER = "villager"  # everyone's "profession" with no professions


def setup_config(cfg: dict) -> None:
    """engine.new_world, after modes.bare_start: with no professions nobody has a trade at any start stage,
    so the start is the same for everyone (yards, kits). Idempotent."""
    if not no_professions(cfg):
        return
    cfg["labor"]["own_trade_only"] = False
    for a in cfg["agents"]:
        a["profession"] = VILLAGER
    cfg.setdefault("places", {})["enabled"] = False  # no trade places to hold or lose
    cfg.setdefault("crafting", {})["owner_takes_trade"] = False


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
    """`accept` and `give` work from anywhere: the goods are carried, like a delivered order."""
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
    """Extra units per hour of work from skill (own trade only) or from mastery of that kind of work."""
    if no_professions(cfg):
        act = gather_activity(cfg, resource)
        return mastery_level(cfg, a, act) * _m(cfg)["gather_bonus"] if act else 0
    if not enabled(cfg) or not is_own(cfg, a, resource):
        return 0
    return level(cfg, a.skill_hours) * cfg["labor"]["skill_bonus"]


def after_work_hour(ctx: Ctx, a: Agent, resource: str) -> None:
    """Count one hour of work: today's hours and, at one's own trade, skill (with a level-up message)."""
    cfg = ctx.cfg
    if not enabled(cfg) or resource == "water":
        return
    a.worked_today += 1
    if no_professions(cfg):
        if act := gather_activity(cfg, resource):
            practice(ctx, a, act)
        return
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


# ---------- mastery per kind of work (no professions) ----------

def _m(cfg: dict) -> dict:
    return cfg["labor"]["mastery"]


def gather_activity(cfg: dict, resource: str) -> str | None:
    return next((k for k, goods in _m(cfg)["gather"].items() if resource in goods), None)


def craft_activity(cfg: dict, r: dict) -> str:
    """The kind of work a recipe is (where it is made: a smithy is smithing, home is cooking ...)."""
    return r.get("activity") or _m(cfg)["craft"].get(r.get("building") or r.get("where") or "", "handwork")


def activities(cfg: dict) -> list[str]:
    m = _m(cfg)
    return list(dict.fromkeys([*m["gather"], *m["craft"].values(), "handwork", "hunting"]))


def mastery_level(cfg: dict, a: Agent, act: str) -> int:
    if not no_professions(cfg):
        return 0
    return sum(a.mastery.get(act, 0) >= h for h in _m(cfg)["levels"])


def practice(ctx: Ctx, a: Agent, act: str, hours: int = 1) -> None:
    """`hours` of `act` done today: mastery grows (a public message at each new level)."""
    if not no_professions(ctx.cfg) or hours <= 0:
        return
    before = mastery_level(ctx.cfg, a, act)
    a.mastery[act] = a.mastery.get(act, 0) + hours
    a.practiced[act] = ctx.world.day
    now = mastery_level(ctx.cfg, a, act)
    if now > before:
        ctx.emit("skill_up", f"{a.name} reached {act} mastery level {now}.", actor=a.name, visibility="public",
                 level=now, activity=act)


def mastery_gate(cfg: dict, a: Agent, rid: str, r: dict) -> str | None:
    """Why `a` cannot make `rid` yet: its kind of work is below the level it needs (`mastery.requires`)."""
    need = _m(cfg).get("requires", {}).get(rid, 0) if no_professions(cfg) else 0
    act = craft_activity(cfg, r) if need else ""
    if need and (lv := mastery_level(cfg, a, act)) < need:
        return (f"{rid} needs {act} mastery level {need} (yours: {lv}); simpler {act} work teaches it "
                f"({_m(cfg)['levels'][need - 1]} hours)")
    return None


def extra(a: Agent, key: str, base: int, pct: int) -> int:
    """Bonus items for `base` items at +`pct`%: whole items now, the fraction kept in `a.carry[key]` for the
    next time (so +25% on single loaves is one more loaf every fourth batch)."""
    if base <= 0 or pct <= 0:
        return 0
    total = base * pct + a.carry.get(key, 0)
    a.carry[key] = total % 100
    return total // 100


def craft_pct(cfg: dict, a: Agent, act: str, house: int) -> int:
    """% more items from a craft: mastery of its kind and, made in one's own household, the house level."""
    if not no_professions(cfg):
        return 0
    m = _m(cfg)
    return mastery_level(cfg, a, act) * m["craft_bonus_pct"] + house * m["house_bonus_pct"]


def house_pct(cfg: dict, house: int) -> int:
    return house * _m(cfg)["house_bonus_pct"] if no_professions(cfg) else 0


def bed_bonus(cfg: dict, a: Agent) -> int:
    return mastery_level(cfg, a, "farming") * _m(cfg)["bed_bonus"] if no_professions(cfg) else 0


def hunt_bonus(cfg: dict, a: Agent) -> int:
    return mastery_level(cfg, a, "hunting") * _m(cfg)["hunt_bonus"] if no_professions(cfg) else 0


def best_at(cfg: dict, a: Agent) -> str | None:
    """What the village knows `a` for: the kind of work with the most mastery, from level 1 on."""
    if not no_professions(cfg) or not a.mastery:
        return None
    act = max(sorted(a.mastery), key=a.mastery.get)
    return act if mastery_level(cfg, a, act) >= 1 else None


def mastery_info(cfg: dict, a: Agent) -> dict:
    m, steps = _m(cfg), _m(cfg)["levels"]
    out = {}
    for act in sorted(a.mastery, key=lambda k: (-a.mastery[k], k)):
        lv = mastery_level(cfg, a, act)
        d = {"level": lv, "hours": a.mastery[act]}
        if lv < len(steps):
            d["next_level_after_hours"] = steps[lv]
        out[act] = d
    return out


def _forget(world: World) -> None:
    m = _m(world.config)
    after, per = int(m.get("forget_after_days", 0)), int(m.get("forget_per_day", 0))
    if not after or not per:
        return
    for a in world.agents.values():
        for act in sorted(a.mastery):
            if world.day - a.practiced.get(act, 0) > after:
                a.mastery[act] = max(0, a.mastery[act] - per)
                if a.mastery[act] == 0:
                    del a.mastery[act]
                    a.practiced.pop(act, None)


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
    if no_professions(world.config):
        _forget(world)


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
    if no_professions(cfg):
        out = {"work_today": {"hours_left": hours_left(cfg, a), "your_mastery": mastery_info(cfg, a)}}
    else:
        out = {"work_today": {"hours_left": hours_left(cfg, a), "your_skill": skill_info(cfg, a)}}
    if trader_here(world):
        out["trader_today"] = {"will_buy": {i: trader_left(world, i, "buy") for i in items},
                               "has_for_sale": {i: trader_left(world, i, "sell") for i in items}}
    return out


def facts(cfg: dict) -> str:
    lab = cfg["labor"]
    lines = []
    if no_professions(cfg):
        lines.append("- There are no professions: everyone may gather, sow, hunt and make everything.")
    elif lab.get("own_trade_only", True):
        owned = "; ".join(f"{p}: {', '.join(g)}" for p, g in cfg["professions"].items() if g)
        free = sorted({r for l in cfg["locations"].values() for r in l.get("resources", {})}
                      - {r for g in cfg["professions"].values() for r in g})
        lines.append(f"- Trades: only a villager of that profession can gather (or sow) these goods: {owned}. "
                     f"Free for everyone: {', '.join(free)}.")
    if lab.get("trade_anywhere"):
        lines.append("- Trades and gifts are carried: an offer can be accepted from anywhere, a gift (give) reaches the "
                     "receiver wherever they are, and the goods change hands at once.")
    if lab.get("work_hours_per_day"):
        lines.append(f"- You can work (gather) at most {lab['work_hours_per_day']} hours a day.")
    if no_professions(cfg):
        lines += mastery_facts(cfg)
    else:
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


def mastery_facts(cfg: dict) -> list[str]:
    m = _m(cfg)
    kinds = "; ".join(f"{k} ({', '.join(g)})" for k, g in m["gather"].items())
    crafts: dict[str, list[str]] = {}
    for where, act in m["craft"].items():
        crafts.setdefault(act, []).append(where)
    made = "; ".join(f"{act} (at {', '.join(w)})" for act, w in crafts.items())
    lines = [f"- Mastery: each kind of work has its own. Gathering: {kinds}. Making: {made}; anything else is "
             f"handwork. And hunting. Every hour at a kind of work raises its mastery (level 1-{len(m['levels'])} "
             f"after {'/'.join(map(str, m['levels']))} hours). Each level gives +{m['gather_bonus']} per hour of "
             f"gathering, +{m['craft_bonus_pct']}% items made, +{m['bed_bonus']} grain per garden bed (farming), "
             f"+{m['hunt_bonus']} to every strike (hunting). A kind of work left alone for more than "
             f"{m['forget_after_days']} days loses {m['forget_per_day']} hours of mastery a day. \"work_today\" "
             f"shows yours; \"villagers\" shows what each person is best at."]
    if req := m.get("requires"):
        lines.append("- Fine things need mastery first: " + ", ".join(
            f"{rid} ({craft_activity(cfg, cfg['recipes'][rid])} {n})" for rid, n in req.items()
            if rid in cfg["recipes"]) + ".")
    if m.get("house_bonus_pct"):
        lines.append(f"- Household: each level of your house gives +{m['house_bonus_pct']}% to what your own yard "
                     "makes (garden beds, animals) and to what you make at home or at your own workshop.")
    return lines


def view(world: World) -> dict:
    """Viewer: each villager's skill level and hours worked today; the trader's limits left today."""
    cfg = world.config
    if not enabled(cfg):
        return {}
    if no_professions(cfg):
        skills = {a.name: {"mastery": dict(sorted(a.mastery.items())), "best_at": best_at(cfg, a),
                           "worked_today": a.worked_today} for a in world.agents.values()}
    else:
        skills = {a.name: {"level": level(cfg, a.skill_hours), "hours": a.skill_hours,
                           "worked_today": a.worked_today} for a in world.agents.values()}
    return {"skills": skills, "trader_day": world.trader_day}
