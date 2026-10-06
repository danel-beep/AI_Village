"""Finite map objects: trees, field beds, berry bushes, fish shoals, rocks.

A location resource with `"slots": n` in its config is split into n objects of equal capacity
(`max // n`). `loc.resources[r]` stays the total the agents see and always equals
`sum(loc.slots[r])` (checked by invariants). The viewer draws each slot: a tree with 0 wood is
a stump, a bed with 0 grain is bare soil, a partly refilled bed is a growing crop.

- Gathering finishes the most-used object first (an axe stays on one tree until it falls).
- Night regrowth spreads one unit at a time over the emptiest objects, so several beds
  sprout together and pass through visible growth stages; planted beds are skipped.
- With `regrowth.from_remainder` on, the nightly regrowth follows what is left (`regen`): a full forest
  regrows at its rate, a half-cut one at half, a cleared one only at the `floor` share. Off = flat rate.
- A resource with `"plant"` in its config can be sown: an empty bed becomes `planted` and is
  full (ripe) on `ripe_day`, whatever the regrowth number. Anyone can harvest a ripe bed.

Pure and deterministic, like the rest of the engine.
"""

from __future__ import annotations

from .state import Location


def capacity(spec: dict) -> int:
    return max(1, spec["max"] // spec["slots"])


def init(loc: Location, specs: dict) -> None:
    for r, s in specs.items():
        if not s.get("slots"):
            continue
        cap, left, row = capacity(s), loc.resources.get(r, 0), []
        for _ in range(s["slots"]):
            row.append(min(cap, left))
            left -= row[-1]
        loc.slots[r] = row
        loc.resources[r] = sum(row)


def take(loc: Location, r: str, qty: int) -> list[tuple[int, int]]:
    """Remove up to qty units of r. Returns [(slot, units_taken)]; resources stays in sync."""
    row = loc.slots.get(r)
    if row is None:
        qty = min(qty, loc.resources.get(r, 0))
        loc.resources[r] = loc.resources.get(r, 0) - qty
        return [(-1, qty)] if qty else []
    out = []
    while qty > 0:
        live = [i for i, v in enumerate(row) if v > 0]
        if not live:
            break
        i = min(live, key=lambda k: (row[k], k))
        n = min(qty, row[i])
        row[i] -= n
        qty -= n
        out.append((i, n))
    loc.resources[r] = sum(row)
    return out


def regen(cfg: dict, loc: Location, r: str, spec: dict) -> int:
    """Tonight's regrowth of r before the season multiplier: the flat `regen`, or with
    `regrowth.from_remainder` on, `regen` x the share left (at least `floor`, at least 1 unit)."""
    base, top = spec["regen"], spec["max"]
    rg = cfg.get("regrowth") or {}
    if not rg.get("from_remainder") or base <= 0 or base >= top:  # water refills whole either way
        return base
    share = max(rg.get("floor", 0.1), loc.resources.get(r, 0) / top)
    return max(1, int(base * min(1.0, share) + 0.5))


def grow(loc: Location, r: str, amount: int, cap: int, limit: int) -> None:
    """Add `amount` units of regrowth (capped by `limit` total), emptiest unplanted slot first."""
    row = loc.slots.get(r)
    if row is None:
        loc.resources[r] = min(limit, loc.resources.get(r, 0) + amount)
        return
    planted = {int(k) for k, p in loc.planted.items() if p["resource"] == r}
    amount = min(amount, limit - sum(row))
    while amount > 0:
        open_ = [i for i, v in enumerate(row) if v < cap and i not in planted]
        if not open_:
            break
        i = min(open_, key=lambda k: (row[k], k))
        row[i] += 1
        amount -= 1
    loc.resources[r] = sum(row)


def clear(loc: Location, r: str) -> None:
    """Everything of r is gone (winter frost, drought): crops die, planted beds included."""
    if r in loc.slots:
        loc.slots[r] = [0] * len(loc.slots[r])
    for k in [k for k, p in loc.planted.items() if p["resource"] == r]:
        del loc.planted[k]
    loc.resources[r] = 0


def scale(loc: Location, r: str, keep: float) -> None:
    """Keep a fraction of r in every object (drought halves the field)."""
    if r not in loc.slots:
        loc.resources[r] = int(loc.resources.get(r, 0) * keep)
        return
    loc.slots[r] = [int(v * keep) for v in loc.slots[r]]
    loc.resources[r] = sum(loc.slots[r])


def free_beds(loc: Location, r: str) -> list[int]:
    return [i for i, v in enumerate(loc.slots.get(r, [])) if v == 0 and str(i) not in loc.planted]


def ripen(loc: Location, day: int, cap_of: dict[str, int]) -> list[tuple[int, dict]]:
    """Fill planted beds whose ripe_day has come. Returns [(slot, planting)]."""
    done = []
    for k in sorted(loc.planted, key=int):
        p = loc.planted[k]
        if day >= p["ripe_day"]:
            loc.slots[p["resource"]][int(k)] = cap_of[p["resource"]]
            done.append((int(k), p))
            del loc.planted[k]
    for r in {p["resource"] for _, p in done}:
        loc.resources[r] = sum(loc.slots[r])
    return done


def snapshot(loc: Location, specs: dict) -> dict:
    """What the viewer needs to draw this location's objects (cap = units in a full object)."""
    return {"slots": {r: list(v) for r, v in loc.slots.items()},
            "cap": {r: capacity(specs[r]) for r in loc.slots},
            "planted": {k: dict(p) for k, p in loc.planted.items()}}
