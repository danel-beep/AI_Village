"""The world engine: a deterministic function (world, decisions, god events) -> (world', events).

It knows nothing about LLMs. Agents (LLM or scripted) only see `observe()` output and
only act through `step()` decisions.
"""

from __future__ import annotations

import random
import re
from typing import Any

from . import actions as _actions  # noqa: F401  (registers actions)
from . import god as _god  # noqa: F401  (registers god events)
from . import clock, conflict, crises, dice, family, governance, land, mapgen, ops, plots, reputation, seasons, tiles, works
from .actions import step_move, work_hour
from .config import make_config
from .ops import Ctx, Event, fmt_items
from .registry import ACTIONS, GOD, ActionError
from .state import Agent, Chest, Fire, Location, Order, Project, World

# A decision is what an agent returns each turn:
# {"thought": str, "action": {"name": str, "args": {...}}, "say": str | None}
Decision = dict[str, Any]
GodEvent = dict[str, Any]  # {"name": str, "args": {...}}


def new_world(config: dict | None = None) -> World:
    cfg = make_config(config)
    if clock.tick_minutes(cfg) not in clock.ALLOWED:
        raise ValueError(f"tick_minutes must be one of {clock.ALLOWED}, got {cfg.get('tick_minutes')}")
    if cfg["map"].get("procedural") and "layout" not in cfg["map"]:
        cfg = mapgen.generate(cfg)  # a replayed log already carries its map, so it is never re-rolled
    if "layout" in cfg["map"]:  # a generated map has its own lots; the hand-made map's ones must not leak in
        for lid in [k for k, s in cfg["locations"].items() if "lot" in s and k not in cfg["map"]["layout"]["places"]]:
            del cfg["locations"][lid]
    w = World(config=cfg, hour=cfg["day_start_hour"])
    for lid, spec in cfg["locations"].items():
        res = {r: v["start"] for r, v in spec.get("resources", {}).items()}
        w.locations[lid] = Location(lid, spec["name"], list(spec["neighbors"]), res)
        tiles.init(w.locations[lid], spec.get("resources", {}))
    land.setup(w)
    for spec in cfg["agents"]:
        name = spec["name"]
        home = f"home_{name}"
        links = cfg["map"].get("homes", {}).get(name, ["square"])
        w.locations[home] = Location(home, f"{name}'s house", list(links))
        for to in links:
            w.locations[to].neighbors.append(home)
        a = Agent(name=name, profession=spec["profession"], home=home, location=home,
                  satiety=cfg["satiety_start"], health=cfg["health_max"])
        w.agents[name] = a
        start = cfg["map"].get("start", {}).get(name, {})  # mapgen's unfair start, if any
        ops.mint_coins(w, a, start.get("coins", cfg["start_coins"]))
        for item, n in sorted(start.get("items", {}).items()):
            ops.mint(w, a.inventory, item, n)
        w.chests[f"chest_{name}"] = Chest(f"chest_{name}", name, home)
        plots.setup(w, spec, home)
    for pid, spec in cfg["projects"].items():
        w.projects[pid] = Project(pid, spec["name"], dict(spec["needs"]), structure=spec.get("structure"),
                                  level=1 if spec.get("structure") else 0, proposer="council")
    for a in w.agents.values():
        a.busy_until = w.tick + wake_offset(w, a.name)
    return w


def rng_for(world: World, salt: str = "") -> random.Random:
    return random.Random(f"{world.config['seed']}:{world.tick}:{salt}")


def wake_offset(world: World, name: str) -> int:
    """Ticks a villager sleeps in after dawn, so the village does not think in one chorus.
    0 in the hourly mode; its own rng stream, so it never shifts any other random draw."""
    q = clock.per_hour(world.config)
    return rng_for(world, f"wake:{name}").randrange(q) if q > 1 else 0


def needs_decision(world: World, name: str) -> bool:
    a = world.agents[name]
    return ops.can_act(a) and a.task is None and world.tick >= a.busy_until


def waiting_agents(world: World) -> list[str]:
    return [n for n in sorted(world.agents) if needs_decision(world, n)]


# ---------- observation ----------

def observe(world: World, name: str, consume_inbox: bool = True) -> dict:
    """What the agent knows right now. This is the ONLY input an agent gets."""
    a = world.agents[name]
    ctx = Ctx(world, rng_for(world, "observe"))
    loc = world.locations[a.location]
    cfg = world.config
    people = [{"name": o.name, "asleep": o.asleep} for o in world.agents.values()
              if o.name != name and o.status == "active" and o.location == a.location]
    chest = world.chests[f"chest_{name}"]
    chests_here = [{"owner": c.owner, "locked": c.locked,
                    **({"items": c.items, "coins": c.coins} if ops.can_act(a) and
                       (c.owner == name or name in c.shared_with) else {})}
                   for c in world.chests.values() if c.location == a.location]
    every = cfg["tax_every_days"]
    beds = plant_info(world, loc)
    obs = {
        "time": {"day": world.day, "hour": world.hour, "minute": world.minute, "day_ends_at": cfg["day_end_hour"],
                 "next_tax_day": ((world.day - 1) // every + 1) * every + 1, "tax": governance.tax_amount(world),
                 **seasons.time_info(cfg, world.day)},
        "you": {
            "name": a.name, "profession": a.profession, "home": a.home, "location": a.location,
            "satiety": a.satiety, "health": a.health, "coins": a.coins, "inventory": dict(a.inventory),
            "tool_wear": a.tool_wear, "sick": world.day < a.sick_until_day,
            "evicted": world.day < a.evicted_until_day, "task": a.task,
            "your_chest": {"items": chest.items, "coins": chest.coins, "locked": chest.locked,
                           "shared_with": chest.shared_with},
            "chests_shared_with_you": [c.owner for c in world.chests.values() if name in c.shared_with],
        },
        "here": {
            "id": loc.id, "name": loc.name, "roads_to": loc.neighbors, "resources": dict(loc.resources),
            "ground": dict(loc.ground), "people": people, "chests": chests_here,
            "on_fire": loc.id in world.fires,
            **({"beds": beds} if beds else {}),
        },
        "fires": [{"house": f.location, "water_needed": f.water_needed, "hours_left": f.ticks_left}
                  for f in world.fires.values()],
        "news": list(a.inbox),
        "offers_to_you": [vars(o) for o in world.offers.values() if o.to == name],
        "your_offers": [vars(o) for o in world.offers.values() if o.sender == name],
        "board": {
            "debts": [vars(d) for d in world.debts.values() if d.status != "repaid"],
            "orders": [vars(o) for o in world.orders.values() if o.status == "open"],
            "projects": works.board(world),
            "trader_prices": {i: {"buy": max(1, int(v["value"] * cfg["npc_sell_ratio"]
                                                    * crises.price_factor(world, i, "buy")
                                                    * works.sell_factor(world, "buy"))),
                                  "sell": max(1, int(v["value"] * cfg["npc_buy_ratio"]
                                                     * crises.price_factor(world, i, "sell")
                                                     * works.sell_factor(world, "sell")))}
                              for i, v in cfg["items"].items() if v.get("tradable", True)},
            "recipes": cfg["recipes"],
            "villagers": [{"name": o.name, "profession": o.profession, "status": o.status}
                          for o in world.agents.values()],
        },
        "relations": family.observe(world, name),
        "last_error": a.last_error,
        "available_actions": ACTIONS.available(ctx, a) if ops.can_act(a) else [],
    }
    obs.update(reputation.observe(world, name))
    obs.update(plots.observe(world, name))
    obs.update(crises.observe(world, name))
    obs.update(land.observe(world, name))
    obs.update(dice.observe(world, name))
    obs.update(works.observe(world, name))
    if governance.enabled(cfg):
        obs["government"] = governance.observe(world, name)
    if consume_inbox:
        a.inbox.clear()
        a.last_error = None
    return obs


def plant_info(world: World, loc) -> dict:
    """Sowable resources here: free beds and what the agent's own sown beds are doing."""
    out = {}
    for r, s in world.config["locations"].get(loc.id, {}).get("resources", {}).items():
        if "plant" in s:
            out[r] = {"free_beds": len(tiles.free_beds(loc, r)),
                      "growing": sorted(p["ripe_day"] for p in loc.planted.values() if p["resource"] == r),
                      "seed": s["plant"]["seed"], "ripe_after_nights": s["plant"]["days"],
                      "harvest_per_bed": tiles.capacity(s)}
    return out


# ---------- step ----------

def step(world: World, decisions: dict[str, Decision], god_events: list[GodEvent] | None = None) -> list[Event]:
    """Advance the world by one tick (`tick_minutes`). Mutates `world` in place and returns the events.

    Each action keeps its agent busy for `action_minutes` (clock.action_ticks); a running task makes one
    step (a walk hop, an hour of work) whenever the agent is free again. Hourly upkeep (hunger, fire,
    offers, laws, estates) runs in the last tick of every hour, the night in the last tick of the day."""
    ctx = Ctx(world, rng_for(world))
    for g in god_events or []:
        try:
            GOD.run(ctx, None, g["name"], g.get("args"))
        except ActionError as e:
            ctx.emit("god_error", f"[god] {g['name']} failed: {e}")

    deliver_mail(ctx)

    order = sorted(world.agents)
    ctx.rng.shuffle(order)
    for name in order:
        a = world.agents[name]
        if not ops.can_act(a):
            continue
        dec = decisions.get(name)
        if dec is not None:
            a.task = None  # a fresh decision interrupts any running task
            run_decision(ctx, a, dec)
        elif a.task is not None and world.tick >= a.busy_until:
            continue_task(ctx, a)
            a.busy_until = world.tick + clock.per_hour(world.config)

    wake_busy_agents(ctx)
    minutes = clock.tick_minutes(world.config)
    hour_over = world.minute + minutes >= 60
    if hour_over:
        end_of_hour(ctx)
    world.tick += 1
    if not hour_over:
        world.minute += minutes
        return ctx.events
    world.minute = 0
    world.hour += 1
    if world.hour >= world.config["day_end_hour"]:
        night(ctx)
    return ctx.events


def run_decision(ctx: Ctx, a: Agent, dec: Decision) -> None:
    say = dec.get("say")
    if say:
        try:
            ACTIONS.run(ctx, a, "say", {"text": str(say)})
        except ActionError:
            pass
    act = dec.get("action") or {"name": "wait"}
    if not isinstance(act, dict):
        act = {"name": "wait"}
    name = str(act.get("name", "wait"))
    try:
        ACTIONS.run(ctx, a, name, act.get("args") if isinstance(act.get("args"), dict) else {})
    except ActionError as e:
        a.last_error = f"{act.get('name')}: {e}"
        a.task = None
        name = "error"
        ctx.emit("error", f"Your action failed: {a.last_error}", actor=a.name, to=[a.name],
                 action=act, invalid=True)
    if name == "wait" and say:  # only talking: as quick as `say`, so the answer can come soon
        name = "say"
    a.busy_until = ctx.world.tick + clock.action_ticks(ctx.cfg, name)


def continue_task(ctx: Ctx, a: Agent) -> None:
    t = a.task
    if t["kind"] == "move":
        nxt = t["path"].pop(0)
        step_move(ctx, a, nxt)
        if not t["path"]:
            a.task = None
    elif t["kind"] == "work":
        got = work_hour(ctx, a, t["resource"])
        t["hours_left"] -= 1
        if t["hours_left"] <= 0 or got == 0:
            a.task = None
    else:  # unknown task kinds never block an agent forever
        a.task = None


def deliver_mail(ctx: Ctx) -> None:
    w = ctx.world
    due = [m for m in w.mail if m.deliver_tick <= w.tick]
    w.mail = [m for m in w.mail if m.deliver_tick > w.tick]
    for m in due:
        ctx.emit("letter", f'Letter from {m.sender}: "{m.text}"', actor=m.sender, to=[m.to])
        interrupt(w, m.to)


def interrupt(world: World, name: str) -> None:
    a = world.agents.get(name)
    if a is not None and a.task is not None:
        a.task = None


# Which events make a busy agent (one with a running task) stop and think.
# Every interrupt costs one model call, so only events addressed to the agent wake it:
#   "direct"  - names in `ev.to` (the addressee), never bystanders who merely see it
#   "heard"   - everyone who received the event (village-wide emergencies)
#   "mention" - receivers whose name appears in what was said
# Events not listed here still reach the inbox and are read at the next decision.
WAKE_RULES: dict[str, str] = {
    "whisper": "direct", "letter": "direct", "offer": "direct", "trade": "direct", "decline": "direct",
    "give": "direct", "lend": "direct", "gift": "direct",
    "steal_attempt": "direct", "witness": "direct", "robbed": "direct", "take_shared": "direct",
    "fire": "heard",
    "proposal": "direct", "proposal_refused": "direct", "wedding": "direct", "divorce": "direct",
    "inheritance": "direct",
    "fight": "direct", "arson_seen": "direct", "land_offer": "direct", "land_sold": "direct",
    "dice_challenge": "direct", "dice": "direct",
    "say": "mention",
}


def wake_targets(world: World, ev: Event, rules: dict[str, str] | None = None) -> list[str]:
    mode = (WAKE_RULES if rules is None else rules).get(ev.kind)
    if mode == "direct":
        names = list(ev.to)
    elif mode == "heard":
        names = ops.recipients(world, ev)
    elif mode == "mention":
        said = str(ev.data.get("text_raw", ev.text))
        names = [n for n in ops.recipients(world, ev)
                 if re.search(rf"\b{re.escape(n)}\b", said, re.IGNORECASE)]
    else:
        return []
    return [n for n in names if n != ev.actor]


def wake_busy_agents(ctx: Ctx) -> None:
    for ev in ctx.events:
        for n in wake_targets(ctx.world, ev):
            interrupt(ctx.world, n)


def end_of_hour(ctx: Ctx) -> None:
    w, cfg = ctx.world, ctx.cfg
    governance.end_of_hour(ctx)
    for a in w.agents.values():
        if a.status != "active":
            continue
        was = a.satiety
        loss = cfg["satiety_loss_asleep_per_hour"] if a.asleep else cfg["satiety_loss_per_hour"]
        a.satiety = max(0, a.satiety - loss)
        if a.satiety == 0:
            a.health = max(0, a.health - cfg["starving_health_loss_per_hour"])
            ctx.emit("starving", "You are starving and losing health! Eat something.", to=[a.name])
            if was > 0:  # wake once when hunger starts, not every hour after
                interrupt(w, a.name)
    for f in list(w.fires.values()):
        burn_for(ctx, f, 1)
    for o in list(w.offers.values()):
        if o.expires_tick <= w.tick:
            del w.offers[o.id]
    land.expire_offers(w)
    check_health(ctx)
    family.after_hour(ctx)


def burn_for(ctx: Ctx, f: Fire, hours: int) -> None:
    """The fire burns `hours` more: it grows every fire_grow_hours and takes the house when time is up."""
    cfg = ctx.cfg
    grow = cfg["fire_grow_hours"] + works.fire_grow_bonus(ctx.world)
    before = f.water_needed
    for _ in range(hours):
        f.hours += 1
        f.ticks_left -= 1
        if grow and f.hours % grow == 0:
            f.water_needed = min(cfg["fire_water_max"], f.water_needed + 1)
    if f.ticks_left <= 0:
        burn_house(ctx, f.location)
    elif f.water_needed > before:
        name = ctx.world.locations[f.location].name
        ctx.emit("fire_grows", f"The fire at {name} is spreading: it now needs {f.water_needed} buckets of water, "
                 f"{f.ticks_left} hours before it burns down.", location=f.location, visibility="location",
                 house=f.location, water_needed=f.water_needed, hours_left=f.ticks_left)


def burn_house(ctx: Ctx, home: str) -> None:
    w = ctx.world
    w.fires.pop(home, None)
    for c in w.chests.values():
        if c.location == home:
            lost = dict(c.items)
            for k, v in lost.items():
                ops.burn(w, c.items, k, v)
            coins = c.coins
            ops.burn_coins(w, c, coins)
            ctx.emit("house_burned", f"{w.locations[home].name} burned down. The chest and everything in it "
                     f"({fmt_items(lost)}, {coins} coins) is gone.", visibility="public", home=home)


def check_health(ctx: Ctx) -> None:
    w, cfg = ctx.world, ctx.cfg
    for a in w.agents.values():
        if a.status != "active" or a.health > 0:
            continue
        a.task, a.asleep = None, False
        if cfg["death_mode"] == "death":
            a.status = "dead"
            ctx.emit("death", f"{a.name} has died.", visibility="public")
            continue
        for k, v in list(a.inventory.items()):
            ops.burn(w, a.inventory, k, v - v // 2)
        a.status, a.status_until_day = "hospital", w.day + cfg["hospital_days"]
        ctx.emit("hospital", f"{a.name} collapsed and was taken to the hospital for {cfg['hospital_days']} days.",
                 visibility="public")


def night(ctx: Ctx) -> None:
    w, cfg = ctx.world, ctx.cfg
    w.hour = cfg["day_end_hour"]
    for f in list(w.fires.values()):
        burn_for(ctx, f, cfg["fire_night_hours"])
    for a in w.agents.values():
        if a.status != "active":
            continue
        a.satiety = max(0, a.satiety - cfg["satiety_loss_night"])
        if a.satiety == 0:
            a.health = max(0, a.health - cfg["starving_health_loss_night"])
        elif (a.location == a.home and w.day >= a.evicted_until_day
              and a.satiety >= cfg["health_regen_min_satiety"]):
            a.health = min(cfg["health_max"], a.health + cfg["health_regen_night_at_home"] + plots.health_bonus(w, a))
    check_health(ctx)

    w.day += 1
    w.hour = cfg["day_start_hour"]
    seasons.new_day(ctx)
    governance.new_day(ctx)
    crises.new_day(ctx, rng_for(w, "crises"))
    for loc in w.locations.values():
        spec = cfg["locations"].get(loc.id, {}).get("resources", {})
        if w.day < loc.drought_until_day:
            continue
        for r, s in spec.items():
            if crises.blocks_regrowth(w, loc.id, r):
                continue
            cap = tiles.capacity(s) if s.get("slots") else s["max"]
            tiles.grow(loc, r, seasons.regen(cfg, w.day, r, s["regen"]), cap, s["max"])
    for loc in w.locations.values():
        if not loc.planted:
            continue
        caps = {r: tiles.capacity(s) for r, s in cfg["locations"][loc.id]["resources"].items() if s.get("slots")}
        for slot, p in tiles.ripen(loc, w.day, caps):
            ctx.emit("crop_ripe", f"The {p['resource']} you planted at the {loc.name} is ripe: {caps[p['resource']]} "
                     f"{p['resource']} ready to harvest (anyone there can take it).", to=[p["by"]],
                     location=loc.id, resource=p["resource"], slot=slot, by=p["by"])
    for a in w.agents.values():
        a.asleep, a.task = False, None
        a.busy_until = w.tick + wake_offset(w, a.name)
        if a.status == "hospital" and w.day >= a.status_until_day:
            a.status, a.location = "active", a.home
            a.health, a.satiety = 60, 60
            ctx.emit("discharged", f"{a.name} is back from the hospital.", visibility="public")

    # Weekly tax
    if (w.day - 1) % cfg["tax_every_days"] == 0:
        tax = governance.tax_amount(w)
        for a in w.agents.values():
            if a.status == "dead":
                continue
            if a.coins >= tax:
                governance.pay_tax(w, a, tax)
                ctx.emit("tax", f"You paid {tax} coins of tax.", to=[a.name])
            else:
                governance.pay_tax(w, a, a.coins)
                a.evicted_until_day = w.day + cfg["eviction_days"]
                ctx.emit("evicted", f"{a.name} could not pay the tax and is locked out of their house "
                         f"for {cfg['eviction_days']} days.", visibility="public")
    # Debts
    for d in w.debts.values():
        if d.status == "open" and w.day > d.due_day:
            d.status = "defaulted"
            ctx.emit("default", f"{d.borrower} failed to repay {d.lender} on time ({d.coins_owed} coins, "
                     f"{d.id}).", visibility="public", debt=d.id)
    # Orders
    for o in w.orders.values():
        if o.status == "open" and w.day > o.expires_day:
            o.status = "expired"
    if (w.day - 2) % cfg["order_every_days"] == 0 and cfg["order_templates"]:
        for _ in range(cfg.get("orders_per_post", 1)):  # population.resolve raises it for big villages
            tpl = ctx.rng.choice(cfg["order_templates"])
            o = Order(w.new_id("order"), dict(tpl["needs"]), tpl["reward"], w.day + cfg["order_ttl_days"])
            w.orders[o.id] = o
            ctx.emit("order", f"New order on the board ({o.id}): {fmt_items(o.needs)} for {o.reward} coins, "
                     f"until day {o.expires_day}.", visibility="public")
    plots.after_night(ctx)
    family.after_night(ctx)
    works.after_night(ctx)
    conflict.random_fire(ctx)
    ctx.emit("morning", f"Day {w.day} begins.", visibility="public")
