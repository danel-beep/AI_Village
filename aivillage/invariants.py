"""Checks that must hold after every tick. Tests and the runner call `check(world)`."""

from __future__ import annotations

from collections import Counter

from .plots import holdings as plot_holdings, used_cells
from .state import World


class InvariantError(AssertionError):
    pass


def holdings(world: World) -> Counter:
    total: Counter = Counter()
    for a in world.agents.values():
        total.update(a.inventory)
        total["coins"] += a.coins
    for c in world.chests.values():
        total.update(c.items)
        total["coins"] += c.coins
    for loc in world.locations.values():
        total.update(loc.ground)
    total["coins"] += world.governance.coins
    total.update(plot_holdings(world))
    return total


def check(world: World) -> None:
    errors: list[str] = []
    cfg = world.config

    # 1. Conservation: nothing appears or disappears outside mint/burn.
    held = holdings(world)
    for key in set(held) | set(world.ledger):
        if held.get(key, 0) != world.ledger.get(key, 0):
            errors.append(f"conservation: {key} held={held.get(key, 0)} ledger={world.ledger.get(key, 0)}")

    # 2. No negatives, no zero entries, only known items.
    def bag(where: str, items: dict) -> None:
        for k, v in items.items():
            if v <= 0:
                errors.append(f"{where}: {k}={v}")
            if k not in cfg["items"]:
                errors.append(f"{where}: unknown item {k}")

    for h, p in world.plots.items():
        for b in p.buildings:
            bag(f"plot {h} {b['id']}", b["items"])
        if used_cells(cfg, p) > p.cells or h not in world.locations:
            errors.append(f"plot {h}: {used_cells(cfg, p)} cells used of {p.cells}")
    for a in world.agents.values():
        bag(f"agent {a.name}", a.inventory)
        if a.coins < 0:
            errors.append(f"agent {a.name}: coins {a.coins}")
        if not 0 <= a.satiety <= cfg["satiety_max"]:
            errors.append(f"agent {a.name}: satiety {a.satiety}")
        if not 0 <= a.health <= cfg["health_max"]:
            errors.append(f"agent {a.name}: health {a.health}")
        if a.location not in world.locations:
            errors.append(f"agent {a.name}: bad location {a.location}")
        if a.status == "active" and a.health == 0:
            errors.append(f"agent {a.name}: active with 0 health")
        if a.task is not None and a.task.get("kind") not in ("move", "work"):
            errors.append(f"agent {a.name}: bad task {a.task}")
    for c in world.chests.values():
        bag(f"chest {c.id}", c.items)
        if c.coins < 0:
            errors.append(f"chest {c.id}: coins {c.coins}")
    for loc in world.locations.values():
        bag(f"ground {loc.id}", loc.ground)
        for r, v in loc.resources.items():
            if v < 0:
                errors.append(f"location {loc.id}: {r}={v}")
        for r, row in loc.slots.items():
            if min(row, default=0) < 0 or sum(row) != loc.resources.get(r):
                errors.append(f"location {loc.id}: {r} objects {row} do not sum to {loc.resources.get(r)}")
        for k, p in loc.planted.items():
            if loc.slots.get(p["resource"], [])[int(k)] != 0:
                errors.append(f"location {loc.id}: sown bed {k} is not empty")
        for n in loc.neighbors:
            if n not in world.locations or loc.id not in world.locations[n].neighbors:
                errors.append(f"road {loc.id}->{n} is not two-way")

    g = world.governance
    if g.coins < 0:
        errors.append(f"treasury: coins {g.coins}")
    for n in [g.mayor, *g.candidates, *g.votes, *g.exiled]:
        if n is not None and n not in world.agents:
            errors.append(f"governance: unknown villager {n}")

    # 3. Time
    if not cfg["day_start_hour"] <= world.hour < cfg["day_end_hour"]:
        errors.append(f"hour {world.hour} outside the day")

    if errors:
        raise InvariantError("; ".join(errors))
