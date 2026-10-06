"""Trade places (config block `places`; on in the crafts mode), after the jobs in The Escapist.

Each profession has a limited number of places: ceil(`spare` x villagers x the profession's share of
`population.profession_weights`), a few more than villagers in total. Rules, nothing else:

- `change_trade(profession)` at the square takes a free place of another trade: skill starts again from 0,
  and the next change is possible after `change_cooldown_days`;
- whoever has not worked at their own trade (gathered its goods, made its recipes, sown or harvested its
  crops, buying inputs for its recipes) for `idle_days` days loses the place at dawn and becomes a laborer (`LABORER`: no trade goods,
  free goods and village work only) until they take a free place again;
- the law "revoke_place" (governance.py) takes a person's place by vote.

So a villager can want a rival to miss work: that frees a place. No new way to hurt anyone is added.
State: `Agent.trade_day` (last day of work at the trade; gathering is counted in `labor.after_work_hour`), `Agent.trade_since_day` (day the place was taken).
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from . import labor, ops, population
from .ops import Ctx, Event
from .registry import ACTIONS, ActionError
from .state import Agent, World

LABORER = "laborer"
SITE = "square"


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("places", {}).get("enabled"))


def _p(cfg: dict) -> dict:
    return cfg["places"]


def trades(cfg: dict) -> list[str]:
    return sorted(cfg["professions"])


def capacity(cfg: dict, prof: str) -> int:
    weights = (cfg.get("population") or {}).get("profession_weights") or {}
    w = {p: float(weights.get(p, 1)) for p in trades(cfg)}
    total = sum(w.values()) or 1.0
    return max(1, math.ceil(_p(cfg)["spare"] * population.size(cfg) * w.get(prof, 1.0) / total))


def holders(world: World, prof: str) -> list[str]:
    return sorted(a.name for a in world.agents.values() if a.profession == prof and a.status != "dead")


def free(world: World, prof: str) -> int:
    return max(0, capacity(world.config, prof) - len(holders(world, prof)))


def table(world: World) -> dict:
    return {p: {"places": capacity(world.config, p), "taken": len(holders(world, p))} for p in trades(world.config)}


def _last_work(a: Agent) -> int:
    return max(a.trade_day, a.trade_since_day, 1)


def days_idle(world: World, a: Agent) -> int:
    return world.day - _last_work(a)


# ---------- noticing work at one's trade ----------

def _own_recipe(cfg: dict, a: Agent, recipe: str) -> bool:
    r = cfg["recipes"].get(recipe) or {}
    return bool(r.get("profession")) and r["profession"] == a.profession


def _on_event(ctx: Ctx, ev: Event, names: list[str]) -> None:
    """ops.EVENT_HOOKS: a craft of one's own trade's recipe, or sowing / harvesting one's own crop."""
    if not enabled(ctx.cfg) or not ev.actor or ev.kind not in ("craft", "plant", "collect"):
        return
    a = ctx.world.agents.get(ev.actor)
    if a is None or a.profession == LABORER:
        return
    own = labor.trade_of(ctx.cfg, "grain")
    if (ev.kind == "craft" and _own_recipe(ctx.cfg, a, ev.data.get("recipe", ""))) or \
            (ev.kind in ("plant", "collect") and a.profession in own):
        a.trade_day = ctx.world.day


ops.EVENT_HOOKS.append(_on_event)


def note_supply(world: World, a: Agent, items: dict) -> None:
    """Getting inputs for one's own trade's recipes (buying ore and wood as a smith) is work at the trade too:
    a smith waiting for ore no longer loses the place for days without a forge (economy audit, item 6)."""
    cfg = world.config
    if not enabled(cfg) or a.profession == LABORER or not items:
        return
    inputs = {k for r in cfg["recipes"].values() if r.get("profession") == a.profession for k in r["inputs"]}
    if inputs & {k for k, n in items.items() if n > 0}:
        a.trade_day = world.day


# ---------- actions ----------

class ChangeTradeArgs(BaseModel):
    profession: str


@ACTIONS.action("change_trade", "Take a free place in another trade at the square: from then on you gather and "
                "make that trade's goods instead of your own, with skill from zero.", ChangeTradeArgs,
                available=lambda c, a: enabled(c.cfg) and a.location == SITE
                and any(p != a.profession and free(c.world, p) for p in trades(c.cfg)))
def change_trade(ctx: Ctx, a: Agent, args: ChangeTradeArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        raise ActionError("trades have no places in this village")
    if a.location != SITE:
        raise ActionError(f"trade places are taken at the {SITE}")
    prof = args.profession.strip().lower()
    if prof not in cfg["professions"]:
        raise ActionError(f"no such trade '{args.profession}'; trades: {', '.join(trades(cfg))}")
    if prof == a.profession:
        raise ActionError(f"you are already a {prof}")
    if not free(w, prof):
        raise ActionError(f"all {capacity(cfg, prof)} {prof} places are taken: {', '.join(holders(w, prof))}")
    wait = _p(cfg).get("change_cooldown_days", 0)
    if a.profession != LABORER and a.trade_since_day and w.day < a.trade_since_day + wait:
        raise ActionError(f"you took your place on day {a.trade_since_day}; you can change it from day "
                          f"{a.trade_since_day + wait}")
    old = a.profession
    a.profession, a.skill_hours, a.trade_since_day, a.trade_day = prof, 0, w.day, w.day
    ctx.emit("trade_changed", f"{a.name} took a {prof} place" + (f" (was a {old})." if old != LABORER else "."),
             actor=a.name, visibility="public", profession=prof, was=old)


def lose_place(ctx: Ctx, a: Agent, why: str) -> None:
    old = a.profession
    a.profession, a.skill_hours = LABORER, 0
    ctx.emit("place_lost", f"{a.name} lost their place as a {old}: {why}. A {old} place is free.",
             visibility="public", person=a.name, profession=old)


def after_night(ctx: Ctx) -> None:
    """Dawn: whoever did not work at their trade for `idle_days` days loses the place."""
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        return
    idle = _p(cfg).get("idle_days", 0)
    if not idle:
        return
    for a in sorted(w.agents.values(), key=lambda x: x.name):
        if a.status != "dead" and a.profession != LABORER and days_idle(w, a) > idle:
            lose_place(ctx, a, f"no work at the trade for {idle} days")


# ---------- what villagers see ----------

def observe(world: World, name: str) -> dict:
    if not enabled(world.config):
        return {}
    a = world.agents[name]
    out = {"trade_places": table(world)}
    if a.profession == LABORER:
        out["your_place"] = "none (laborer)"
    else:
        idle = _p(world.config)["idle_days"]
        out["your_place"] = {"trade": a.profession, "days_without_work_at_it": max(0, days_idle(world, a)),
                             "lost_after_days": idle}
    return out


def facts(cfg: dict) -> str:
    if not enabled(cfg):
        return ""
    p = _p(cfg)
    caps = ", ".join(f"{t} {capacity(cfg, t)}" for t in trades(cfg))
    return (f"- Trade places: each trade has a limited number of places ({caps}); \"trade_places\" shows how many "
            f"are taken. change_trade at the square takes a free place in another trade (skill starts from zero; "
            f"next change after {p['change_cooldown_days']} days). Whoever does no work at their trade (gathering "
            f"its goods, making its recipes, sowing or harvesting its crop, getting inputs for its recipes) for {p['idle_days']} days loses the "
            f"place at dawn and is a laborer ({labor.laborer_text(cfg)}) until taking a free place. The "
            f"law revoke_place takes a person's place by vote.")
