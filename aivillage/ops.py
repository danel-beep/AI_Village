"""Low-level operations shared by actions, god events and the engine.

Every change to items or coins goes through these helpers, so the ledger stays exact:
`mint`/`burn` change the world total, `move_items`/`move_coins` only move things around.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .state import Agent, World

Items = dict[str, int]


@dataclass
class Event:
    tick: int
    day: int
    hour: int
    kind: str
    text: str
    actor: str | None = None
    location: str | None = None
    # public: everyone; location: everyone awake at `location` + `to`; private: only `to`
    visibility: str = "private"
    to: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


# Called as hook(ctx, event, recipients) after every emit. Social modules register here.
EVENT_HOOKS: list = []


class Ctx:
    """Everything an action or god event needs during one tick."""

    def __init__(self, world: World, rng: random.Random):
        self.world = world
        self.rng = rng
        self.cfg = world.config
        self.events: list[Event] = []

    def emit(self, kind: str, text: str, *, actor: str | None = None, location: str | None = None,
             visibility: str = "private", to: list[str] | None = None, **data) -> Event:
        w = self.world
        ev = Event(w.tick, w.day, w.hour, kind, text, actor, location, visibility, list(to or []), data)
        self.events.append(ev)
        names = deliver(w, ev)
        for hook in EVENT_HOOKS:
            hook(self, ev, names)
        return ev


def recipients(world: World, ev: Event) -> list[str]:
    if ev.visibility == "public":
        names = [a.name for a in world.agents.values() if a.status != "dead"]
    elif ev.visibility == "location":
        names = [a.name for a in world.agents.values()
                 if a.status == "active" and a.location == ev.location and not a.asleep]
        names += [n for n in ev.to if n not in names]
    else:
        names = list(ev.to)
    return names


def deliver(world: World, ev: Event) -> list[str]:
    limit = world.config["inbox_size"]
    stamp = f"[day {ev.day} {ev.hour:02d}:00] "
    names = recipients(world, ev)
    for name in names:
        a = world.agents.get(name)
        if a is None:
            continue
        a.inbox.append(stamp + ev.text)
        if len(a.inbox) > limit:
            del a.inbox[: len(a.inbox) - limit]
    return names


# ---- items ----

def count(items: Items, item: str) -> int:
    return items.get(item, 0)


def has_all(items: Items, need: Items) -> bool:
    return all(count(items, k) >= v for k, v in need.items())


def _add(items: Items, item: str, n: int) -> None:
    if n == 0:
        return
    items[item] = items.get(item, 0) + n
    if items[item] == 0:
        del items[item]
    assert items.get(item, 0) >= 0, f"negative {item}"


def mint(world: World, items: Items, item: str, n: int) -> None:
    _add(items, item, n)
    world.ledger[item] = world.ledger.get(item, 0) + n


def burn(world: World, items: Items, item: str, n: int) -> None:
    assert count(items, item) >= n, f"burn {n} {item} from {items}"
    _add(items, item, -n)
    world.ledger[item] = world.ledger.get(item, 0) - n


def move_items(src: Items, dst: Items, need: Items) -> None:
    assert has_all(src, need), f"move {need} from {src}"
    for k, v in need.items():
        _add(src, k, -v)
        _add(dst, k, v)


# ---- coins (agents and chests both have a `coins` attribute) ----

def mint_coins(world: World, holder, n: int) -> None:
    holder.coins += n
    world.ledger["coins"] = world.ledger.get("coins", 0) + n


def burn_coins(world: World, holder, n: int) -> None:
    assert holder.coins >= n
    holder.coins -= n
    world.ledger["coins"] = world.ledger.get("coins", 0) - n


def move_coins(src, dst, n: int) -> None:
    assert src.coins >= n >= 0
    src.coins -= n
    dst.coins += n


def fmt_items(items: Items) -> str:
    return ", ".join(f"{v} {k}" for k, v in sorted(items.items())) or "nothing"


def can_act(a: Agent) -> bool:
    return a.status == "active" and not a.asleep
