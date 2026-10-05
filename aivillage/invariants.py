"""Checks that must hold after every tick. Tests and the runner call `check(world)`."""

from __future__ import annotations

from collections import Counter

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
        for n in loc.neighbors:
            if n not in world.locations or loc.id not in world.locations[n].neighbors:
                errors.append(f"road {loc.id}->{n} is not two-way")

    # 3. Time
    if not cfg["day_start_hour"] <= world.hour < cfg["day_end_hour"]:
        errors.append(f"hour {world.hour} outside the day")

    if errors:
        raise InvariantError("; ".join(errors))
