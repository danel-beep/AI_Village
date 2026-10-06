"""Food that goes bad (config block `spoilage`).

Each owner's food is one store: their bag, the chests they own and what they list on the market board.
The store keeps batches per item, `[expire_day, qty]`, oldest first. Nothing hooks the many ways items
move: every hour and at dawn the batches are reconciled with what the owner actually holds. Units above
the tracked total are new (they keep `days` from the day they came); units missing were used up, oldest
first. Batches whose day has come are burned. Moving food between one's own bag, chests and listings
keeps its age; food that changes hands starts fresh with its new owner.
"""

from __future__ import annotations

from . import ops
from .state import World


def _c(cfg: dict) -> dict:
    return cfg.get("spoilage", {})


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def storage_factor(world: World, owner: str) -> float:
    """How much longer food keeps in this owner's store (a granary or smokehouse will raise it)."""
    return 1.0


def life(world: World, owner: str, item: str) -> int:
    """Days a unit of `item` keeps for `owner`; 0 = never spoils."""
    days = _c(world.config).get("days", {}).get(item, 0)
    return max(1, round(days * storage_factor(world, owner))) if days else 0


def _stores(world: World, owner: str) -> list[dict]:
    """Item dicts of the owner's store, in the order spoiled units are taken: chests, listings, bag."""
    out = [c.items for c in sorted(world.chests.values(), key=lambda c: c.id) if c.owner == owner]
    out += [s.items for s in sorted(world.sales.values(), key=lambda s: s.id) if s.seller == owner]
    a = world.agents.get(owner)
    if a is not None:
        out.append(a.inventory)
    return out


def _owners(world: World) -> list[str]:
    names = {a.name for a in world.agents.values() if a.status != "dead"}
    names |= {c.owner for c in world.chests.values() if c.owner}
    return sorted(names)


def reconcile(batches: list, have: int, new_expire: int) -> list:
    """Batches matching `have` units: missing units leave oldest first, extra units join as `new_expire`."""
    out = [list(b) for b in batches]
    extra = have - sum(q for _, q in out)
    while extra < 0 and out:
        take = min(-extra, out[0][1])
        out[0][1] -= take
        extra += take
        if out[0][1] == 0:
            out.pop(0)
    if extra > 0:
        if out and out[-1][0] == new_expire:
            out[-1][1] += extra
        else:
            out.append([new_expire, extra])
            out.sort(key=lambda b: b[0])
    return out


def _held(stores: list[dict], item: str) -> int:
    return sum(ops.count(s, item) for s in stores)


def _sync(world: World, gained_day: int) -> None:
    """Match every store's batches with what it holds now; new units count as got on `gained_day`."""
    book: dict = {}
    for owner in _owners(world):
        stores = _stores(world, owner)
        kept = {}
        for item in sorted(_c(world.config).get("days", {})):
            days = life(world, owner, item)
            have = _held(stores, item)
            if days and have:
                kept[item] = reconcile(world.spoilage.get(owner, {}).get(item, []), have, gained_day + days)
        if kept:
            book[owner] = kept
    world.spoilage = book


def end_of_hour(ctx: ops.Ctx) -> None:
    """Hourly bookkeeping, so food used and food got on the same day are told apart (oldest is used first)."""
    if enabled(ctx.world.config):
        _sync(ctx.world, ctx.world.day)


def after_night(ctx: ops.Ctx) -> None:
    """At dawn (after the day has turned): throw out what has run out of days."""
    w = ctx.world
    if not enabled(w.config):
        return
    _sync(w, w.day - 1)
    for owner, kept in list(w.spoilage.items()):
        stores = _stores(w, owner)
        gone = {}
        for item, batches in list(kept.items()):
            bad = sum(q for d, q in batches if d <= w.day)
            if not bad:
                continue
            left = bad
            for s in stores:
                n = min(left, ops.count(s, item))
                if n:
                    ops.burn(w, s, item, n)
                    left -= n
            gone[item] = bad
            kept[item] = [b for b in batches if b[0] > w.day]
            if not kept[item]:
                del kept[item]
        if not kept:
            del w.spoilage[owner]
        a = w.agents.get(owner)
        if gone and a is not None and a.status != "dead":
            ctx.emit("spoiled", f"Overnight some of your food went bad and was thrown out: {ops.fmt_items(gone)}.",
                     to=[owner], items=gone)


def observe(world: World, name: str) -> dict:
    """What of mine goes bad at the next dawn (food got today is not in it: it keeps its full days)."""
    if not enabled(world.config):
        return {}
    stores = _stores(world, name)
    soon = {}
    for item in sorted(_c(world.config).get("days", {})):
        days = life(world, name, item)
        have = _held(stores, item)
        if not days or not have:
            continue
        batches = reconcile(world.spoilage.get(name, {}).get(item, []), have, world.day + days)
        n = sum(q for d, q in batches if d <= world.day + 1)
        if n:
            soon[item] = n
    return {"spoils_next_dawn": soon}


def facts(cfg: dict) -> str:
    if not enabled(cfg):
        return ""
    days = _c(cfg).get("days", {})
    keep = ", ".join(f"{i} {d}" for i, d in sorted(days.items(), key=lambda x: (x[1], x[0])) if i in cfg["items"])
    return (f"- Food goes bad. Days it keeps: {keep}; other goods keep forever. The days count from the day the food "
            "came to you (your bag, your chests and your market listings are one store, moving food between them "
            "does not change its age; food you get from someone else counts from the day you got it). Food whose days "
            "are over is gone at dawn. \"spoils_next_dawn\" shows what of yours goes bad at the next dawn.")
