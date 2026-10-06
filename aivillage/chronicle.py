"""Visible wealth and the village chronicle (config block `chronicle`; on in the crafts mode).

The final run showed miners getting ten times richer while nobody noticed: wealth was invisible. Now, the same
facts for everyone and no advice about what to do with them:

- `wealth`: every living villager's rough level (coins + base value of goods, home chest included):
  poor / modest / well-off / rich, by the thresholds in `tiers`;
- every `every_days` days at dawn a public "chronicle" event sums up the period: average coins earned from the
  trader and council orders by trade, trade changes and lost places, how many deals, gifts, loans and repaid
  loans there were (counts only), public defaults and reported thefts (names), who was praised on the honor
  board (honors.py; names), who worked most on village
  projects. The last report stays in the observation as `last_chronicle`.

State: `World.chronicle` (counts and earnings by trade since the last report; earnings come from
taxes.record_income).
"""

from __future__ import annotations

from . import ops
from .ops import Ctx, Event
from .state import World

LEVELS = ("poor", "modest", "well-off", "rich")
COUNTED = {"trade": "deals", "give": "gifts", "lend": "loans", "repay": "repayments"}


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("chronicle", {}).get("enabled"))


def _c(cfg: dict) -> dict:
    return cfg["chronicle"]


# ---------- wealth ----------

def worth(world: World, name: str) -> int:
    cfg, a = world.config, world.agents[name]
    value = lambda items: sum(cfg["items"].get(k, {}).get("value", 0) * v for k, v in items.items())  # noqa: E731
    chest = world.chests.get(f"chest_{name}")
    total = a.coins + value(a.inventory)
    if chest is not None:
        total += chest.coins + value(chest.items)
    return total


def level(cfg: dict, worth_: int) -> str:
    return LEVELS[sum(worth_ >= t for t in _c(cfg)["tiers"])]


# ---------- counting ----------

def _book(world: World) -> dict:
    c = world.chronicle
    if not c:
        c.update({"since_day": world.day, "counts": {}, "changes": [], "lost": [], "defaults": [], "thefts": [],
                  "build": {}, "earned": {}})
    return c


def earned(world: World, a, n: int) -> None:
    """taxes.record_income: `a` got `n` coins from the trader or a council order, at their current trade."""
    if enabled(world.config):
        by = _book(world).setdefault("earned", {}).setdefault(a.profession, {})
        by[a.name] = by.get(a.name, 0) + n


def _on_event(ctx: Ctx, ev: Event, names: list[str]) -> None:
    if not enabled(ctx.cfg):
        return
    k = ev.kind
    if k in COUNTED:
        b = _book(ctx.world)
        b["counts"][COUNTED[k]] = b["counts"].get(COUNTED[k], 0) + 1
    elif k == "trade_changed":
        _book(ctx.world)["changes"].append(f"{ev.actor} ({ev.data.get('was')} -> {ev.data.get('profession')})")
    elif k == "place_lost":
        _book(ctx.world)["lost"].append(f"{ev.data.get('person')} ({ev.data.get('profession')})")
    elif k == "default" and ev.visibility == "public":
        d = ctx.world.debts.get(ev.data.get("debt", ""))
        who = ev.actor or (d.borrower if d is not None else None)
        if who:
            _book(ctx.world)["defaults"].append(who)
    elif k == "theft_report":
        thief = ev.data.get("thief") or ev.data.get("person")
        if thief:
            _book(ctx.world)["thefts"].append(thief)
    elif k == "praise" and ev.data.get("person"):
        _book(ctx.world).setdefault("praised", []).append(ev.data["person"])
    elif k == "build_work" and ev.actor:
        b = _book(ctx.world)["build"]
        b[ev.actor] = b.get(ev.actor, 0) + 1


ops.EVENT_HOOKS.append(_on_event)


# ---------- the report ----------

def _names(xs: list[str]) -> str:
    seen: dict[str, int] = {}
    for x in xs:
        seen[x] = seen.get(x, 0) + 1
    return ", ".join(f"{n} x{c}" if c > 1 else n for n, c in seen.items())


def report(world: World) -> str:
    b, cfg = _book(world), world.config
    alive = [a for a in world.agents.values() if a.status != "dead"]
    earned = b.get("earned", {})
    avg = ", ".join(f"{p} {sum(v.values()) // len(v)} ({len(v)})" for p, v in sorted(earned.items()) if v)
    parts = [f"Village chronicle, days {b['since_day']}-{world.day - 1}. Coins earned from the trader and council "
             "orders, average per villager who earned any, by the trade they had then (villagers): "
             f"{avg or 'nobody earned any'}."]
    counts = b["counts"]
    parts.append("Between villagers: " + ", ".join(f"{counts.get(v, 0)} {v}" for v in COUNTED.values()) + ".")
    if b["changes"]:
        parts.append(f"Changed trade: {', '.join(b['changes'])}.")
    if b["lost"]:
        parts.append(f"Lost their place: {', '.join(b['lost'])}.")
    if b["defaults"]:
        parts.append(f"Did not repay on time: {_names(b['defaults'])}.")
    if b["thefts"]:
        parts.append(f"Reported for theft: {_names(b['thefts'])}.")
    if b.get("praised"):
        parts.append(f"Praised on the honor board: {_names(b['praised'])}.")
    if b["build"]:
        top = sorted(b["build"].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        parts.append("Hours on village projects: " + ", ".join(f"{n} {h}" for n, h in top) + ".")
    levels = {}
    for a in alive:
        levels.setdefault(level(cfg, worth(world, a.name)), []).append(a.name)
    parts.append("Wealth: " + "; ".join(f"{lv} {', '.join(sorted(levels[lv]))}" for lv in LEVELS if lv in levels) + ".")
    return " ".join(parts)


def after_night(ctx: Ctx) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        return
    if not w.chronicle:  # nothing counted yet: the period began on the day that just ended
        _book(w)["since_day"] = w.day - 1
    every = _c(cfg)["every_days"]
    if w.day - w.chronicle["since_day"] < every:
        return
    text = report(w)
    ctx.emit("chronicle", text, visibility="public")
    w.chronicle.clear()
    _book(w)["last"] = text


# ---------- what villagers see ----------

def observe(world: World, name: str) -> dict:
    cfg = world.config
    if not enabled(cfg):
        return {}
    out = {"wealth": {a.name: level(cfg, worth(world, a.name))
                      for a in sorted(world.agents.values(), key=lambda x: x.name) if a.status != "dead"}}
    if world.chronicle.get("last"):
        out["last_chronicle"] = world.chronicle["last"]
    return out


def facts(cfg: dict) -> str:
    if not enabled(cfg):
        return ""
    t = _c(cfg)["tiers"]
    return (f"- \"wealth\" is every villager's rough wealth (coins and goods at base value, home chest included): "
            f"poor under {t[0]}, modest under {t[1]}, well-off under {t[2]}, rich from {t[2]}. Every "
            f"{_c(cfg)['every_days']} days at dawn the public village chronicle sums up the period: coins earned from "
            "the trader and council orders by trade, trade changes and lost places, numbers of deals, gifts, loans "
            "and repayments, public defaults and reported thefts, " + ("who was praised on the honor board, "
            if (cfg.get("honors") or {}).get("enabled") else "") + "hours on village projects, everyone's wealth.")
