"""Riding and pack animals, carts and the carry limit (config block `transport`, off unless `transport.enabled`).

«С нуля» plan task 17. Everything opens with the `village` stage when progress is on (`feature:transport` and
the `action:*` keys below); until then nothing here applies, not even the carry limit.

- **Carry limit.** A villager carries up to `carry` items at full pace (coins do not count, a cart counts 0).
  Carrying more, every road of a walk takes `1 / overloaded_pace` times as long.
- **Animals** (`kinds`: horse, donkey) are individuals in `world.transport["animals"]`:
  `{id, kind, owner, holder, location, strength, food, lent_to, due_day, overdue_told}`. A villager leads at most
  `lead_max` of them (`holder`); a led animal goes wherever its holder goes, an unled one stands where it was left
  (`location`). The one led gives its `speed` (roads per hour, the walk's extra roads are taken at the end of
  each hour) and adds its `carry`. A weak animal (strength <= `weak_at`) walks at the villager's pace and adds
  half its carry. A cart carried adds `cart.carry_led` while an animal is led, else `cart.carry_hand`.
- **Getting one.** `catch_animal(kind)`: a wild one at a place of its `habitat` (resources there; `habitats`
  overrides with {loc: {kind: n}}); `wild` of each kind per such place, one try per action with
  `catch_chance`. `buy_animal(kind)`: from the trader at the market once he comes (`feature:trader`),
  `price` coins (burned, like any trader sale), `trader_per_day` of each kind a day. A cart is a recipe
  (`cart.recipe` at a workbench with crafting on, else `cart.recipe_plain` at home).
- **Ownership.** Only the owner gives an animal away (`give_animal`) or lends it (`lend_animal(to, days)`:
  the borrower leads it, it stays the owner's; `return_animal` hands it back where the owner is or leaves it at
  the owner's home). Anyone can `take_animal` one that stands unled; one owned by someone else (and not lent
  to the taker) is seen by everyone there as taken (`witness` events) and the owner hears of it. The owner can
  take their own animal back from whoever leads it at the same place.
- **Upkeep** (the day's last hour, like animals.py): each animal eats `eats_per_night` food units from what
  was fed to it (`feed_animal`, `food` units per item, at most `trough_max`), or grazes free where it is when
  the place has one of `graze_resources`. Fed and standing at its owner's home with a `stable` stall free
  (construction on; without construction the home counts), it regains `stable_rest` strength; unfed it loses
  1. At 0 it runs off back to the wild. A loan past its due day is told to both once. `cut_hay` gathers
  `hay_per_hour` hay at a grazing place.

The engine calls `setup` (new_world), `end_of_hour` and `observe`; run.py logs `view`.
"""

from __future__ import annotations

import random

from pydantic import BaseModel, Field

from . import actions, clock, construction, crafting, ops, progress
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, World

FEATURE = "feature:transport"
ACTION_NAMES = ("catch_animal", "buy_animal", "take_animal", "leave_animal", "lend_animal", "return_animal",
                "give_animal", "feed_animal", "cut_hay")
progress.DEFAULT_UNLOCKS.setdefault(FEATURE, {"stage": "village"})
for _n in ACTION_NAMES:
    progress.DEFAULT_UNLOCKS.setdefault(f"action:{_n}", {"stage": "village"})
progress.DEFAULT_UNLOCKS.setdefault("recipe:cart", {"stage": "village"})
progress.DEFAULT_UNLOCKS.setdefault("building:stable", {"stage": "village"})
progress.DEFAULT_UNLOCKS.setdefault("building:stable@2", {"stage": "town"})


def _c(cfg: dict) -> dict:
    return cfg.get("transport") or {}


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def active(world: World) -> bool:
    """On and opened (with progress on: from the village stage)."""
    return enabled(world.config) and bool(world.transport) and progress.unlocked(world, FEATURE)


def hidden_actions(cfg: dict) -> frozenset[str]:
    """Actions to leave out of the handbook when transport is off."""
    return frozenset() if enabled(cfg) else frozenset(ACTION_NAMES)


def _kinds(cfg: dict) -> dict:
    return _c(cfg)["kinds"]


def _rng(world: World) -> random.Random:
    return random.Random(f"{world.config['seed']}:{world.tick}:transport")


# ---------- setup ----------

def habitats(world: World) -> dict[str, dict[str, int]]:
    """{loc: {kind: n}} where wild animals can be caught: the config's `habitats`, else by resources."""
    c = _c(world.config)
    if c.get("habitats"):
        return {loc: dict(v) for loc, v in c["habitats"].items() if loc in world.locations}
    out: dict[str, dict[str, int]] = {}
    for lid in sorted(world.locations):
        res = world.config["locations"].get(lid, {}).get("resources", {})
        for kind, k in sorted(_kinds(world.config).items()):
            if int(k.get("wild", 0)) > 0 and any(r in res for r in k.get("habitat", [])):
                out.setdefault(lid, {})[kind] = int(k["wild"])
    return out


def setup(world: World) -> None:
    cfg = world.config
    if not enabled(cfg):
        return
    c = _c(cfg)
    for item, spec in sorted(c.get("items", {}).items()):  # hay, cart: added unless the config has them
        cfg["items"].setdefault(item, dict(spec))
    cart = c.get("cart") or {}
    if "cart" not in cfg["recipes"] and (cart.get("recipe") or cart.get("recipe_plain")):
        if crafting.enabled(cfg):
            cfg["recipes"]["cart"] = crafting._normalize("cart", cart["recipe"], cfg["crafting"].get("workshops", {}))
        else:
            cfg["recipes"]["cart"] = dict(cart["recipe_plain"])
    world.transport = {"animals": {}, "wild": habitats(world), "pace": {}, "sold": {}}


# ---------- queries ----------

def animals(world: World) -> dict[str, dict]:
    return (world.transport or {}).get("animals", {})


def where(world: World, an: dict) -> str | None:
    if an["holder"]:
        h = world.agents.get(an["holder"])
        return h.location if h else an["location"]
    return an["location"]


def led_by(world: World, name: str) -> list[dict]:
    return [an for _, an in sorted(animals(world).items()) if an["holder"] == name]


def _weak(cfg: dict, an: dict) -> bool:
    return an["strength"] <= int(_c(cfg)["weak_at"])


def speed(world: World, name: str) -> float:
    """Roads per hour while walking: the best animal led, slowed by an overload."""
    cfg = world.config
    best = 1.0
    for an in led_by(world, name):
        if not _weak(cfg, an):
            best = max(best, float(_kinds(cfg)[an["kind"]]["speed"]))
    if load(world.agents[name]) > capacity(world, name):
        best *= float(_c(cfg)["overloaded_pace"])
    return best


def load(a: Agent) -> int:
    return sum(n for item, n in a.inventory.items() if item != "cart" and n > 0)


def capacity(world: World, name: str) -> int:
    cfg, c = world.config, _c(world.config)
    led = led_by(world, name)
    cap = int(c["carry"])
    for an in led:
        extra = int(_kinds(cfg)[an["kind"]]["carry"])
        cap += extra // 2 if _weak(cfg, an) else extra
    if ops.count(world.agents[name].inventory, "cart") > 0:
        cap += int(c["cart"]["carry_led"] if led else c["cart"]["carry_hand"])
    return cap


def _graze(world: World, loc: str | None) -> bool:
    res = world.config["locations"].get(loc or "", {}).get("resources", {})
    return any(r in res for r in _c(world.config).get("graze_resources", []))


def _stalls(world: World, owner: str) -> int:
    """Stalls at the owner's home: a stable's `stalls`; with no stable building in the game, the home itself."""
    cfg = world.config
    if not (construction.enabled(cfg) and "stable" in construction.catalog(cfg)):
        return 10 ** 6
    a = world.agents.get(owner)
    lvl = construction.has_building(world, "stable", location=a.home) if a else 0
    if not lvl:
        return 0
    return int(construction.catalog(cfg)["stable"]["levels"][lvl - 1].get("stalls", 0))


def _label(an: dict) -> str:
    return f"{an['kind']} {an['id']}"


def _brief(world: World, an: dict, me: str) -> dict:
    out = {"id": an["id"], "animal": an["kind"], "strength": f"{an['strength']}/{_c(world.config)['strength_max']}",
           "fed_food_left": an["food"]}
    if an["owner"] != me:
        out["owner"] = an["owner"]
    if an["holder"]:
        out["led_by"] = an["holder"]
    else:
        out["at"] = an["location"]
    if an["lent_to"]:
        out["lent_to"], out["due_day"] = an["lent_to"], an["due_day"]
    return out


# ---------- actions ----------

def _can(ctx: Ctx, a: Agent) -> bool:
    return active(ctx.world)


def _need_active(ctx: Ctx) -> None:
    if not active(ctx.world):
        raise ActionError("there are no riding or pack animals in this village yet")


def _kind(ctx: Ctx, raw: str) -> str:
    k = raw.strip().lower()
    if k not in _kinds(ctx.cfg):
        raise ActionError(f"unknown animal '{raw}' (animals: {', '.join(_kinds(ctx.cfg))})")
    return k


def _hands_free(ctx: Ctx, a: Agent) -> None:
    if len(led_by(ctx.world, a.name)) >= int(_c(ctx.cfg)["lead_max"]):
        raise ActionError("you already lead as many animals as you can; leave_animal first")


def _new_animal(ctx: Ctx, a: Agent, kind: str) -> dict:
    c = _c(ctx.cfg)
    an = {"id": ctx.world.new_id(kind), "kind": kind, "owner": a.name, "holder": a.name, "location": None,
          "strength": int(c["strength_start"]), "food": 0, "lent_to": None, "due_day": None, "overdue_told": False}
    ctx.world.transport["animals"][an["id"]] = an
    return an


def _person_here(ctx: Ctx, a: Agent, name: str) -> Agent:
    b = ctx.world.agents.get(name)
    if b is None or b.status == "dead":
        raise ActionError(f"no villager named {name}")
    if b.name == a.name:
        raise ActionError("that is you")
    if b.location != a.location:
        raise ActionError(f"{b.name} is not here")
    return b


def _my_led(ctx: Ctx, a: Agent, owned: bool = True) -> dict:
    led = led_by(ctx.world, a.name)
    if owned:
        led = [an for an in led if an["owner"] == a.name]
    if not led:
        raise ActionError("you lead no animal of your own" if owned else "you lead no animal")
    return led[0]


class KindArgs(BaseModel):
    animal: str = Field(description="horse or donkey")


@ACTIONS.action("catch_animal", "Try to catch a wild horse or donkey here (one try; caught, it is yours and you "
                "lead it).", KindArgs,
                available=lambda c, a: _can(c, a) and bool(c.world.transport["wild"].get(a.location)))
def catch_animal(ctx: Ctx, a: Agent, args: KindArgs) -> None:
    _need_active(ctx)
    kind = _kind(ctx, args.animal)
    wild = ctx.world.transport["wild"].get(a.location, {})
    if not wild.get(kind):
        seen = ", ".join(f"{k} x{v}" for k, v in sorted(wild.items()) if v) or "none"
        raise ActionError(f"there is no wild {kind} here (wild animals here: {seen})")
    _hands_free(ctx, a)
    if ctx.rng.random() >= float(_kinds(ctx.cfg)[kind]["catch_chance"]):
        ctx.emit("catch_miss", f"{a.name} tried to catch a wild {kind} and it got away.", actor=a.name,
                 location=a.location, visibility="location", animal=kind)
        return
    wild[kind] -= 1
    an = _new_animal(ctx, a, kind)
    ctx.emit("animal_caught", f"{a.name} caught a wild {kind} ({an['id']}).", actor=a.name, location=a.location,
             visibility="location", animal=kind, id=an["id"])


@ACTIONS.action("buy_animal", "Buy a horse or donkey from the trader at the market; you lead it home.", KindArgs,
                available=lambda c, a: _can(c, a) and a.location == "market"
                and progress.unlocked(c.world, "feature:trader"))
def buy_animal(ctx: Ctx, a: Agent, args: KindArgs) -> None:
    _need_active(ctx)
    if a.location != "market" or not progress.unlocked(ctx.world, "feature:trader"):
        raise ActionError("the trader sells animals at the market")
    kind = _kind(ctx, args.animal)
    sold = ctx.world.transport["sold"]
    per_day = int(_c(ctx.cfg)["trader_per_day"])
    if sold.get(kind, 0) >= per_day:
        raise ActionError(f"the trader has no more {kind}s today ({per_day} a day)")
    price = int(_kinds(ctx.cfg)[kind]["price"])
    if a.coins < price:
        raise ActionError(f"a {kind} costs {price} coins, you have {a.coins}")
    _hands_free(ctx, a)
    sold[kind] = sold.get(kind, 0) + 1
    ops.burn_coins(ctx.world, a, price)
    an = _new_animal(ctx, a, kind)
    ctx.emit("animal_bought", f"{a.name} bought a {kind} ({an['id']}) from the trader for {price} coins.",
             actor=a.name, location=a.location, visibility="location", animal=kind, id=an["id"], price=price)


class AnimalArgs(BaseModel):
    animal: str = Field(description="animal id, e.g. horse12")


def _animal(ctx: Ctx, aid: str) -> dict:
    an = animals(ctx.world).get(aid.strip())
    if an is None:
        raise ActionError(f"no animal '{aid}'")
    return an


@ACTIONS.action("take_animal", "Lead an animal standing here (your own, or one lent to you; the owner can also take "
                "theirs back from whoever leads it here). Leading someone else's animal away is seen by everyone "
                "here and the owner hears of it.", AnimalArgs,
                available=lambda c, a: _can(c, a) and any(where(c.world, an) == a.location and an["holder"] != a.name
                                                          for an in animals(c.world).values()))
def take_animal(ctx: Ctx, a: Agent, args: AnimalArgs) -> None:
    _need_active(ctx)
    w = ctx.world
    an = _animal(ctx, args.animal)
    if where(w, an) != a.location:
        raise ActionError(f"{an['id']} is not here")
    if an["holder"] == a.name:
        raise ActionError(f"you already lead {an['id']}")
    _hands_free(ctx, a)
    if an["holder"]:
        if an["owner"] != a.name:
            raise ActionError(f"{an['holder']} leads {an['id']}")
        was = an["holder"]
        an["holder"], an["location"], an["lent_to"], an["due_day"] = a.name, None, None, None
        ctx.emit("animal_reclaimed", f"{a.name} took back their {_label(an)} from {was}.", actor=a.name,
                 location=a.location, visibility="location", to=[was], id=an["id"], animal=an["kind"], holder=was)
        return
    an["holder"], an["location"] = a.name, None
    if an["owner"] == a.name or an["lent_to"] == a.name:
        ctx.emit("animal_led", f"{a.name} is leading {_label(an)}.", actor=a.name, location=a.location,
                 visibility="location", id=an["id"], animal=an["kind"])
        return
    owner = an["owner"]
    ctx.emit("animal_taken", f"{a.name} led away {owner}'s {_label(an)} from {w.locations[a.location].name}.",
             actor=a.name, location=a.location, visibility="location", to=[owner], id=an["id"], animal=an["kind"],
             owner=owner)
    for b in sorted(w.agents.values(), key=lambda x: x.name):  # bystanders saw a theft (reputation.py)
        if b.name not in (a.name, owner) and b.status == "active" and b.location == a.location and not b.asleep:
            ctx.emit("witness", f"You saw {a.name} lead away {owner}'s {an['kind']}.", to=[b.name], thief=a.name,
                     victim=owner, animal=an["kind"])


@ACTIONS.action("leave_animal", "Leave the animal you lead standing here.",
                available=lambda c, a: _can(c, a) and bool(led_by(c.world, a.name)))
def leave_animal(ctx: Ctx, a: Agent, args: BaseModel) -> None:
    _need_active(ctx)
    an = _my_led(ctx, a, owned=False)
    an["holder"], an["location"] = None, a.location
    ctx.emit("animal_left", f"{a.name} left {_label(an)} at {ctx.world.locations[a.location].name}.", actor=a.name,
             location=a.location, visibility="location", id=an["id"], animal=an["kind"])


class LendArgs(BaseModel):
    to: str = Field(description="villager here")
    days: int = Field(2, ge=1, le=14, description="due back after this many days")


@ACTIONS.action("lend_animal", "Hand the animal you lead to another villager here for some days; it stays yours.",
                LendArgs, available=lambda c, a: _can(c, a) and any(an["owner"] == a.name
                                                                    for an in led_by(c.world, a.name)))
def lend_animal(ctx: Ctx, a: Agent, args: LendArgs) -> None:
    _need_active(ctx)
    an = _my_led(ctx, a)
    b = _person_here(ctx, a, args.to)
    _hands_free(ctx, b)
    due = ctx.world.day + args.days
    an.update(holder=b.name, location=None, lent_to=b.name, due_day=due, overdue_told=False)
    ctx.emit("animal_lent", f"{a.name} lent their {_label(an)} to {b.name} until day {due}.", actor=a.name,
             location=a.location, visibility="location", to=[b.name], id=an["id"], animal=an["kind"],
             borrower=b.name, due_day=due)


@ACTIONS.action("return_animal", "Give back the animal you lead to its owner: to them if they are here, else it "
                "stays at the owner's home when you are there.",
                available=lambda c, a: _can(c, a) and any(an["owner"] != a.name for an in led_by(c.world, a.name)))
def return_animal(ctx: Ctx, a: Agent, args: BaseModel) -> None:
    _need_active(ctx)
    w = ctx.world
    led = [an for an in led_by(w, a.name) if an["owner"] != a.name]
    if not led:
        raise ActionError("you lead no animal of someone else")
    an = led[0]
    owner = w.agents.get(an["owner"])
    late = bool(an["due_day"] is not None and w.day > an["due_day"])
    if owner is not None and owner.location == a.location and owner.status != "dead":
        _hands_free(ctx, owner)
        an["holder"] = owner.name
    elif owner is not None and a.location == owner.home:
        an["holder"], an["location"] = None, a.location
    else:
        raise ActionError(f"{an['owner']} is not here; you can return it at {an['owner']}'s home")
    an.update(lent_to=None, due_day=None, overdue_told=False)
    ctx.emit("animal_returned", f"{a.name} returned {an['owner']}'s {_label(an)}" + (" after the due day." if late
             else "."), actor=a.name, location=a.location, visibility="location", to=[an["owner"]], id=an["id"],
             animal=an["kind"], owner=an["owner"], late=late)


class ToArgs(BaseModel):
    to: str = Field(description="villager here")


@ACTIONS.action("give_animal", "Give the animal you lead, and its ownership, to another villager here.", ToArgs,
                available=lambda c, a: _can(c, a) and any(an["owner"] == a.name for an in led_by(c.world, a.name)))
def give_animal(ctx: Ctx, a: Agent, args: ToArgs) -> None:
    _need_active(ctx)
    an = _my_led(ctx, a)
    b = _person_here(ctx, a, args.to)
    _hands_free(ctx, b)
    an.update(owner=b.name, holder=b.name, location=None, lent_to=None, due_day=None, overdue_told=False)
    ctx.emit("animal_given", f"{a.name} gave their {_label(an)} to {b.name}.", actor=a.name, location=a.location,
             visibility="location", to=[b.name], id=an["id"], animal=an["kind"], receiver=b.name)


class FeedArgs(BaseModel):
    item: str = Field(description="food the animal eats, e.g. hay or grain")
    qty: int = Field(1, ge=1, le=20)
    animal: str | None = Field(None, description="animal id here; default: the one you lead")


@ACTIONS.action("feed_animal", "Put food from your inventory in an animal's trough (the animal you lead, or one "
                "here); it eats from it at night.", FeedArgs,
                available=lambda c, a: _can(c, a) and any(where(c.world, an) == a.location
                                                          for an in animals(c.world).values()))
def feed_animal(ctx: Ctx, a: Agent, args: FeedArgs) -> None:
    _need_active(ctx)
    c = _c(ctx.cfg)
    if args.animal:
        an = _animal(ctx, args.animal)
        if where(ctx.world, an) != a.location:
            raise ActionError(f"{an['id']} is not here")
    else:
        an = _my_led(ctx, a, owned=False)
    item = args.item.strip().lower()
    per = c["food"].get(item)
    if not per:
        raise ActionError(f"animals here eat {', '.join(sorted(c['food']))}, not {item}")
    room = int(c["trough_max"]) - an["food"]
    qty = min(args.qty, max(0, -(-room // int(per))))
    if qty <= 0:
        raise ActionError(f"the trough of {an['id']} is full ({an['food']}/{c['trough_max']})")
    if ops.count(a.inventory, item) < qty:
        raise ActionError(f"you have {ops.count(a.inventory, item)} {item}")
    ops.burn(ctx.world, a.inventory, item, qty)
    an["food"] = min(int(c["trough_max"]), an["food"] + qty * int(per))
    ctx.emit("animal_fed", f"{a.name} fed {qty} {item} to {_label(an)} (trough {an['food']}/{c['trough_max']}).",
             actor=a.name, location=a.location, visibility="location", id=an["id"], item=item, qty=qty)


@ACTIONS.action("cut_hay", "Cut hay here for an hour (where animals can graze).",
                available=lambda c, a: _can(c, a) and _graze(c.world, a.location))
def cut_hay(ctx: Ctx, a: Agent, args: BaseModel) -> None:
    _need_active(ctx)
    if not _graze(ctx.world, a.location):
        raise ActionError("there is no grass to cut here")
    if ctx.world.day < a.sick_until_day:
        raise ActionError("you are sick and cannot work")
    n = int(_c(ctx.cfg)["hay_per_hour"])
    ops.mint(ctx.world, a.inventory, "hay", n)
    ctx.emit("work", f"You cut {n} hay.", actor=a.name, location=a.location, to=[a.name], resource="hay", amount=n)


# ---------- hourly: pace; nightly: upkeep ----------

def end_of_hour(ctx: Ctx) -> None:
    w = ctx.world
    if not enabled(ctx.cfg) or not w.transport:
        return
    if active(w):
        _pace(ctx)
    if w.hour + 1 >= ctx.cfg["day_end_hour"]:
        _night(ctx)


def _pace(ctx: Ctx) -> None:
    """Walkers on a move task: faster ones take extra roads at the end of the hour, overloaded ones wait."""
    w = ctx.world
    pace = w.transport["pace"]
    for name in sorted(w.agents):
        a = w.agents[name]
        t = a.task
        if a.status != "active" or a.asleep or not t or t.get("kind") != "move" or not t.get("path"):
            pace.pop(name, None)
            continue
        credit = pace.get(name, 0) + round(speed(w, name) * 100) - 100
        while credit >= 100 and t["path"]:
            actions.step_move(ctx, a, t["path"].pop(0))
            credit -= 100
        if not t["path"]:
            a.task = None
            credit = 0
        while credit <= -100:
            a.busy_until += clock.per_hour(ctx.cfg)
            credit += 100
        if credit:
            pace[name] = credit
        else:
            pace.pop(name, None)


def _night(ctx: Ctx) -> None:
    w, c = ctx.world, _c(ctx.cfg)
    w.transport["sold"] = {}
    rng = _rng(w)
    eats = int(c["eats_per_night"])
    stalls_used: dict[str, int] = {}
    for aid in sorted(animals(w)):
        an = w.transport["animals"][aid]
        loc = where(w, an)
        tell = sorted({an["owner"]} | ({an["holder"]} if an["holder"] else set()))
        fed = an["food"] >= eats
        if fed:
            an["food"] -= eats
        else:
            fed = _graze(w, loc)
        owner = w.agents.get(an["owner"])
        stabled = False
        if owner is not None and loc == owner.home:
            used = stalls_used.get(owner.name, 0)
            if used < _stalls(w, owner.name):
                stalls_used[owner.name] = used + 1
                stabled = True
        top = int(c["strength_max"])
        if fed and stabled and an["strength"] < top:
            an["strength"] = min(top, an["strength"] + int(c["stable_rest"]))
        elif not fed:
            an["strength"] -= 1
            if an["strength"] <= 0:
                _run_off(ctx, rng, an, loc, tell)
                continue
            ctx.emit("animal_hungry", f"{_label(an)} went hungry tonight (strength {an['strength']}/{top}).",
                     to=tell, id=an["id"], animal=an["kind"], strength=an["strength"])
        if an["lent_to"] and an["due_day"] is not None and w.day >= an["due_day"] and not an["overdue_told"] \
                and an["holder"] != an["owner"]:
            an["overdue_told"] = True
            ctx.emit("animal_overdue", f"{an['owner']}'s {_label(an)} lent to {an['lent_to']} was due back on day "
                     f"{an['due_day']}.", to=sorted({an["owner"], an["lent_to"]}), id=an["id"], animal=an["kind"],
                     owner=an["owner"], borrower=an["lent_to"], due_day=an["due_day"])


def _run_off(ctx: Ctx, rng: random.Random, an: dict, loc: str | None, tell: list[str]) -> None:
    w = ctx.world
    del w.transport["animals"][an["id"]]
    homes = sorted(lid for lid, v in w.transport["wild"].items() if an["kind"] in v) or \
        sorted(lid for lid, v in habitats(w).items() if an["kind"] in v)
    if homes:
        back = loc if loc in homes else rng.choice(homes)
        wild = w.transport["wild"].setdefault(back, {})
        wild[an["kind"]] = wild.get(an["kind"], 0) + 1
    ctx.emit("animal_ran_off", f"{an['owner']}'s {_label(an)} grew too weak from hunger and ran off to the wild.",
             to=tell, id=an["id"], animal=an["kind"], owner=an["owner"])


# ---------- observation, prompt, log ----------

def observe(world: World, name: str) -> dict:
    if not active(world):
        return {}
    a = world.agents[name]
    cap = capacity(world, name)
    out: dict = {"carrying": {"items": load(a), "full_pace_up_to": cap}}
    mine = [_brief(world, an, name) for _, an in sorted(animals(world).items())
            if an["owner"] == name or an["holder"] == name]
    if mine:
        out["your_animals"] = mine
    here = [_brief(world, an, name) for _, an in sorted(animals(world).items())
            if where(world, an) == a.location and an["owner"] != name and an["holder"] != name]
    if here:
        out["animals_here"] = here
    wild = {k: v for k, v in sorted(world.transport["wild"].get(a.location, {}).items()) if v}
    if wild:
        out["wild_animals_here"] = wild
    return {"transport": out}


def facts(cfg: dict) -> str | None:
    if not enabled(cfg):
        return None
    c = _c(cfg)
    kinds = "; ".join(f"{k}: {v['speed']:g} roads an hour, carries {v['carry']} more, {v['price']} coins at the "
                      f"trader" for k, v in c["kinds"].items())
    foods = ", ".join(sorted(c["food"]))
    return (f"- Transport (from the village stage): a villager carries {c['carry']} items at full pace (coins do not "
            f"count); with more, every road takes {1 / float(c['overloaded_pace']):g} times as long. A horse or donkey "
            f"led along walks faster and carries more ({kinds}); a cart adds {c['cart']['carry_led']} with an animal, "
            f"{c['cart']['carry_hand']} by hand. Wild ones are caught where they roam (\"wild_animals_here\"). Every "
            f"night an animal eats {c['eats_per_night']} from its trough ({foods}) or grazes where there is grass; "
            f"unfed it loses strength, weak it walks at a person's pace, at 0 it runs off. Fed in a stable at the "
            f"owner's home it regains strength. A lent animal stays its owner's; leading away someone else's animal "
            f"is seen by those present and the owner hears of it.")


def view(world: World) -> dict:
    if not enabled(world.config) or not world.transport:
        return {}
    return {"transport": {"animals": [{"id": an["id"], "kind": an["kind"], "owner": an["owner"],
                                       "holder": an["holder"], "location": where(world, an),
                                       "strength": an["strength"]} for _, an in sorted(animals(world).items())],
                          "wild": world.transport["wild"]}}
