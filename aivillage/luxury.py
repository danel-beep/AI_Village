"""Things worth having beyond food (wants research, idea 3): feasts and goods others can see.

- **Feast** (`host_feast`): the host shares food with every awake villager here (at least `min_guests`).
  The food is split equally between guests and host, each guest's feeling about the host rises by
  `family.on_event.feast`, and the whole village hears who hosted whom. Once a day per host.
- **Goods on view**: in `here.people`, each person shows the items in `visible_items` they carry
  (a ring, a weapon, a tool), so what others own is seen when meeting them.

Config block `luxury` (off by default; on in the «Обычный» mode). Plain facts only: tests/test_neutrality.py.
"""

from __future__ import annotations

from pydantic import BaseModel

from . import ops
from .actions import ItemMap, _items_known, _need
from .ops import Ctx, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, World


def _c(cfg: dict) -> dict:
    return cfg.get("luxury") or {}


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def _guests(world: World, a: Agent) -> list[Agent]:
    return [o for o in world.agents.values() if o.name != a.name and o.status == "active"
            and o.location == a.location and not o.asleep]


class FeastArgs(BaseModel):
    items: ItemMap


def _can_feast(ctx: Ctx, a: Agent) -> bool:
    return enabled(ctx.cfg) and len(_guests(ctx.world, a)) >= _c(ctx.cfg)["min_guests"]


@ACTIONS.action("host_feast", "Share food from your inventory with everyone awake here: it is split equally "
                "between them and you; they all see who fed them, and the village hears of it (once a day).",
                FeastArgs, available=_can_feast)
def host_feast(ctx: Ctx, a: Agent, args: FeastArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        raise ActionError("there are no feasts in this village")
    if a.feast_day == w.day:
        raise ActionError("you already hosted a feast today")
    guests = _guests(w, a)
    if len(guests) < _c(cfg)["min_guests"]:
        raise ActionError(f"a feast needs at least {_c(cfg)['min_guests']} awake people here besides you")
    _items_known(ctx, args.items)
    not_food = [k for k in args.items if not cfg["items"][k].get("food")]
    if not_food:
        raise ActionError(f"not food: {', '.join(not_food)}")
    if not args.items:
        raise ActionError("a feast needs food: items is empty")
    _need(a.inventory, args.items)
    total = sum(cfg["items"][k]["food"] * n for k, n in args.items.items())
    each = total // (len(guests) + 1)
    if each < _c(cfg)["min_food_each"]:
        raise ActionError(f"that is {each} satiety each for {len(guests) + 1} people; a feast gives at least "
                          f"{_c(cfg)['min_food_each']} each")
    for k, n in args.items.items():
        ops.burn(w, a.inventory, k, n)
    for o in guests + [a]:
        o.satiety = min(cfg["satiety_max"], o.satiety + each)
    a.feast_day = w.day
    names = ", ".join(o.name for o in guests)
    ctx.emit("feast", f"{a.name} hosted a feast at {a.location} for {names} ({fmt_items(args.items)}, "
             f"+{each} satiety each).", actor=a.name, location=a.location, visibility="public",
             to=[o.name for o in guests], guests=[o.name for o in guests], food=dict(args.items))


def show_goods(world: World, obs: dict) -> None:
    """Add what each person here visibly carries to `here.people` (engine.observe calls this)."""
    if not enabled(world.config):
        return
    seen = _c(world.config).get("visible_items", [])
    for p in obs["here"]["people"]:
        inv = world.agents[p["name"]].inventory
        goods = {k: ops.count(inv, k) for k in seen if ops.count(inv, k) > 0}
        if goods:
            p["carries"] = goods


def facts(cfg: dict) -> str:
    if not enabled(cfg):
        return ""
    c = _c(cfg)
    return (f"- Feasts: host_feast needs at least {c['min_guests']} awake people here besides you and food giving "
            f"at least {c['min_food_each']} satiety to each of you. Goods on view: \"here.people\" shows the "
            f"{', '.join(c.get('visible_items', []))} each person carries.")
