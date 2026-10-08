"""Threats from outside the village: bandit raids, a beast, a traveler.

The god sends them (`raid`, `beast`, `traveler` god events), warned days ahead or not at all; with
`threats.kinds.<kind>.per_day` they also come by themselves at dawn (0 = never, the fair setting).

- **raid**: bandits arrive at a house. Every hour nobody fights them they carry off `loot_share` of
  each chest there and move on to the next house (`houses`, nearest first); after `hours` they leave and
  set fire to the house they are at, unless someone fought them that hour. Driven off (hp 0), they drop
  what they carried on the ground and their purse goes to the defenders.
- **beast**: every hour unopposed it eats food from the chests of the house it is at, mauls someone
  there, then prowls to another house; leaves after `hours`. Killed, the village pays a bounty.
- **traveler**: waits at the square asking for `need` food (`help_stranger`). Fed, an honest one
  rewards his helpers; `chase_stranger` drives him off. Some are bandit scouts: unless chased off,
  an unwarned raid follows a day or two after they leave. Nothing tells the two apart but behaviour.

`defend` is one dice round against the raid/beast at your place (combat numbers, best weapon carried),
and it strikes back. Night: a threat still here acts unopposed through `fire_night_hours` hours.

State: `world.threats`, a list of dicts with `state` coming | here | gone | defeated. The engine calls
`arrivals` every tick, `end_of_hour`, `night` and `new_day`; agents see warned and present threats in
`observe()["threats"]`; the log view carries `threats` for the viewer.

With village stages on (progress.py, the «С нуля» mode) raids come by themselves only from the stage of
`feature:raids` (a town by default, a hamlet in «С нуля»): before that a random raid is not scheduled and a random
traveler is never a scout (the dice are still rolled, so the other draws stay where they were). The god can send a
raid at any stage.

`threats.hostile.max_gap_days` (0 = off, the old dawn rolls exactly): bandits or a beast come at a random moment,
but never more than that many calm days in a row. After a hostile threat comes, `min_gap_days` stay calm; from
then on each dawn, besides the kinds' own `per_day` dice, the chance of one is 1 / (days left to the max gap + 1),
so the day it comes is spread evenly over the window instead of falling on a fixed date. Which kind is drawn by
their `per_day` weights (all 0: none, the fair setting). Hostile kinds have their own `max_active` slot there, so a
traveler at the square never blocks bandits.
"""

from __future__ import annotations

import random

from pydantic import BaseModel, Field

from . import clock, conflict, governance, ops, progress, works
from .actions import _agent
from .ops import Ctx, fmt_items
from .registry import ACTIONS, GOD, ActionError
from .state import Agent, Letter, World

HOSTILE = ("raid", "beast")
KINDS = ("raid", "beast", "traveler")
KEEP_FINISHED = 6  # finished threats kept in the world for the log, oldest dropped
WHAT = {"raid": "bandits", "beast": "a beast", "traveler": "a traveler"}
RAIDS = "feature:raids"  # progress.DEFAULT_UNLOCKS: the town stage; «С нуля»: the hamlet


def _t(cfg: dict) -> dict:
    return cfg.get("threats") or {}


def enabled(cfg: dict) -> bool:
    return bool(_t(cfg).get("enabled"))


def _kind(cfg: dict, kind: str) -> dict:
    return _t(cfg)["kinds"][kind]


def here(world: World, loc: str, kinds: tuple = HOSTILE) -> dict | None:
    return next((t for t in world.threats if t["state"] == "here" and t["location"] == loc and t["kind"] in kinds),
                None)


def _scale(world: World) -> float:
    n = sum(1 for a in world.agents.values() if a.status != "dead")
    return max(1.0, n / 5)


def _defense(world: World) -> float:
    """Strength multiplier from village defenses: each wall level (works.py) and any finished
    project listed in `defense_projects`."""
    f = float(_t(world.config).get("wall_factor_per_level", 1.0)) ** _wall_level(world)
    for pid, k in (_t(world.config).get("defense_projects") or {}).items():
        p = world.projects.get(pid)
        if p is not None and p.done:
            f *= k
    return f


def _wall_level(world: World) -> int:
    return int(works.defense(world))  # wall level x defense_per_level (works.py), 0 without a wall


def _homes(world: World) -> dict[str, str]:
    """home location -> its villager (active, the first one by name if a couple shares it)."""
    out: dict[str, str] = {}
    for a in sorted(world.agents.values(), key=lambda a: a.name):
        if a.status == "active" and a.home in world.locations:
            out.setdefault(a.home, a.name)
    return out


def _near(world: World, home: str, homes: list[str]) -> list[str]:
    """Other homes, those sharing a road with `home` first (same hamlet), then the rest; stable order."""
    mine = set(world.locations[home].neighbors)
    close = [h for h in homes if h != home and mine & set(world.locations[h].neighbors)]
    return close + [h for h in homes if h != home and h not in close]


def _name(world: World, loc: str) -> str:
    return world.locations[loc].name if loc in world.locations else loc


# ---------- scheduling ----------

def schedule(ctx: Ctx, kind: str, arrive_tick: int, warn: bool, target: str | None = None,
             scout: bool = False, cause: str = "god") -> dict:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        raise ActionError("threats are off in this village")
    homes = _homes(w)
    if target is not None:
        who = _agent(ctx, target)
        if who.status != "active":
            raise ActionError(f"{who.name} is not in the village")
        target_home = who.home
    elif kind == "traveler":
        target_home = None
    else:
        if not homes:
            raise ActionError("nobody lives in the village")
        target_home = ctx.rng.choice(sorted(homes))
    day, hour, minute = clock.time_of(cfg, arrive_tick)
    t = {"id": w.new_id("threat"), "kind": kind, "name": _kind(cfg, kind).get("name", kind), "state": "coming",
         "warned": warn, "cause": cause, "arrive_tick": arrive_tick, "arrive_day": day, "arrive_hour": hour,
         "target": target_home, "location": None, "route": [], "hp": 0, "max_hp": 0, "hours_left": 0,
         "fought": False, "fighters": {}, "loot": {}, "loot_coins": 0, "scout": scout, "fed": {}}
    w.threats.append(t)
    when = f"today around {hour}:{minute:02d}" if day == w.day else f"on day {day} around {hour}:00"
    if warn:
        where = f"{homes.get(target_home, '?')}'s house ({target_home})" if target_home else "the village"
        text = {"raid": f"Warning: a band of robbers is camped in the hills and means to raid {where} {when}.",
                "beast": f"Warning: hunters found huge tracks in the woods; a beast is coming down to {where} {when}.",
                "traveler": f"Word on the road: a traveler is coming to the village {when}."}[kind]
        ctx.emit("threat_warning", text, visibility="public", threat=t["id"], threat_kind=kind,
                 target=target_home, arrive_day=day, arrive_hour=hour)
    else:
        ctx.emit("threat_secret", f"[god] {kind} coming unwarned on day {day} {hour}:00 to {target_home}",
                 visibility="private", threat=t["id"], threat_kind=kind, target=target_home)
    return t


def _active_count(world: World, kinds: tuple = KINDS) -> int:
    return sum(1 for t in world.threats if t["state"] in ("coming", "here") and t["kind"] in kinds)


def _hostile(cfg: dict) -> dict:
    return _t(cfg).get("hostile") or {}


def max_gap(cfg: dict) -> int:
    """`threats.hostile.max_gap_days`: the longest calm stretch without bandits or a beast (0 = no guarantee)."""
    return int(_hostile(cfg).get("max_gap_days") or 0)


def calm_days(world: World) -> int:
    """Days since the last hostile threat came (or is due); counted from `first_day` before the first one."""
    last = max((t["arrive_day"] for t in world.threats if t["kind"] in HOSTILE),
               default=int(_t(world.config).get("first_day", 2)) - 1)
    return world.day - last


def new_day(ctx: Ctx, rng: random.Random) -> None:
    """Dawn: maybe a threat starts by itself (its own rng stream, so other random draws do not move)."""
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg) or w.day < _t(cfg).get("first_day", 2):
        return
    if max_gap(cfg):
        _new_day_gap(ctx, rng)
        return
    raids = progress.unlocked(w, RAIDS)
    for kind in KINDS:
        p = float(_kind(cfg, kind).get("per_day") or 0)
        roll = rng.random()
        if p <= 0 or roll >= p or _active_count(w) >= _t(cfg).get("max_active", 1) or (kind == "raid" and not raids):
            continue
        _start(ctx, rng, kind, raids)


def _new_day_gap(ctx: Ctx, rng: random.Random) -> None:
    """Dawn with a max calm gap: travelers by their own dice and slot; bandits or a beast by their dice or, the
    longer it has been calm, more and more surely (evenly spread over the window, sure on the last day)."""
    w, cfg = ctx.world, ctx.cfg
    h = _hostile(cfg)
    raids = progress.unlocked(w, RAIDS)
    if (float(_kind(cfg, "traveler").get("per_day") or 0) > rng.random()
            and _active_count(w, ("traveler",)) < _t(cfg).get("max_active", 1)):
        _start(ctx, rng, "traveler", raids)
    allowed = [k for k in HOSTILE if float(_kind(cfg, k).get("per_day") or 0) > 0 and (k != "raid" or raids)]
    rolls = {k: rng.random() for k in HOSTILE}
    force = rng.random()
    if not allowed or _active_count(w, HOSTILE) >= int(h.get("max_active", 1)):
        return
    quiet, top = calm_days(w), max_gap(cfg)
    if quiet < int(h.get("min_gap_days", 0)):
        return
    kind = next((k for k in allowed if rolls[k] < float(_kind(cfg, k)["per_day"])), None)
    if kind is None and force < 1 / max(1, top - quiet + 1):
        kind = rng.choices(allowed, weights=[float(_kind(cfg, k)["per_day"]) for k in allowed])[0]
    if kind:
        _start(ctx, rng, kind, raids)


def _start(ctx: Ctx, rng: random.Random, kind: str, raids: bool) -> None:
    w, cfg = ctx.world, ctx.cfg
    start = clock.tick_of(cfg, w.day, cfg["day_start_hour"])
    warn = kind != "traveler" and rng.random() < float(_t(cfg).get("warn_chance", 0))
    if warn:
        tick = clock.tick_of(cfg, w.day + int(_t(cfg).get("warn_days", 2)), int(_t(cfg).get("arrive_hour", 11)))
    else:
        hour = rng.randint(cfg["day_start_hour"] + 2, max(cfg["day_start_hour"] + 2, cfg["day_end_hour"] - 5))
        tick = max(start + 1, clock.tick_of(cfg, w.day, hour))
    homes = sorted(_homes(w))
    if kind != "traveler" and not homes:  # everyone away (hospital): nobody to raid today
        return
    target = None
    if kind != "traveler" and homes:
        target = w.agents[_homes(w)[rng.choice(homes)]].name
    scout = kind == "traveler" and rng.random() < float(_kind(cfg, kind).get("scout_chance", 0)) and raids
    schedule(ctx, kind, tick, warn, target, scout=scout, cause="random")


# ---------- arrival, hours, night ----------

def arrivals(ctx: Ctx) -> None:
    for t in ctx.world.threats:
        if t["state"] == "coming" and t["arrive_tick"] <= ctx.world.tick:
            _arrive(ctx, t)


def _arrive(ctx: Ctx, t: dict) -> None:
    w, cfg = ctx.world, ctx.cfg
    k = _kind(cfg, t["kind"])
    homes = _homes(w)
    t["state"] = "here"
    t["fresh"] = True
    t["hours_left"] = int(k["hours"])
    if t["kind"] == "traveler":
        t["location"] = "square" if "square" in w.locations else sorted(w.locations)[0]
        need = int(k["need"])
        ctx.emit("threat_arrived", f"A traveler arrived at the {_name(w, t['location'])}, tired and hungry. He asks "
                 f"for {need} food" + (" and asks a lot about who lives where and who keeps coins at home"
                                        if t["scout"] else " and tells stories of the road") +
                 f". He will stay about {t['hours_left']} hours (help_stranger feeds him, chase_stranger drives him off).",
                 visibility="public", threat=t["id"], threat_kind="traveler", location=t["location"])
        return
    if not homes:
        t["state"] = "gone"
        return
    home = t["target"] if t["target"] in homes else ctx.rng.choice(sorted(homes))
    t["location"] = home
    if t["kind"] == "raid":
        t["route"] = [home] + _near(w, home, sorted(homes))[: max(0, int(k["houses"]) - 1)]
    defense = _defense(w)
    t["hp"] = t["max_hp"] = max(1, round(k["hp"] * _scale(w) * defense))
    wall = " The village wall slowed them: they are fewer and weaker." if defense < 1 else ""
    who = homes[home]
    if t["kind"] == "raid":
        scout = " Among them is the traveler who visited the village." if t.get("from_scout") else ""
        text = (f"Bandits! Armed robbers burst into {who}'s house ({home}). Each hour nobody fights them "
                f"they plunder the chests there and move to the next house; in {t['hours_left']} hours they leave and "
                f"burn the house they are at. Anyone there can defend.{scout}{wall}")
    else:
        text = (f"A beast came out of the forest to {who}'s house ({home})! Each hour nobody fights it, "
                f"it eats the food in the chests there, mauls whoever is around and prowls to another house; it "
                f"goes back to the woods in {t['hours_left']} hours. Anyone there can defend.{wall}")
    ctx.emit("threat_arrived", text, visibility="public", threat=t["id"], threat_kind=t["kind"], location=home,
             victim=who, hp=t["hp"])


def end_of_hour(ctx: Ctx) -> None:
    for t in list(ctx.world.threats):
        if t["state"] == "here" and t.pop("fresh", False):  # the hour they come in is for the village to react
            continue
        if t["state"] == "here":
            _hour(ctx, t, opposed=t["fought"])
            t["fought"] = False
    _trim(ctx.world)


def night(ctx: Ctx) -> None:
    """Dusk: a traveler goes on his way; bandits and beasts act unopposed through the night."""
    for t in list(ctx.world.threats):
        if t["state"] != "here":
            continue
        if t["kind"] == "traveler":
            _leave(ctx, t)
            continue
        t["fought"] = False
        for _ in range(ctx.cfg["fire_night_hours"]):
            if t["state"] != "here":
                break
            _hour(ctx, t, opposed=False)


def _hour(ctx: Ctx, t: dict, opposed: bool) -> None:
    if not opposed:
        if t["kind"] == "raid":
            _plunder(ctx, t)
        elif t["kind"] == "beast":
            _prowl(ctx, t)
    t["hours_left"] -= 1
    if t["hours_left"] <= 0:
        _leave(ctx, t, burn=not opposed)


def _stayed(ctx: Ctx, t: dict) -> bool:
    """Count an unopposed hour at this house; True (and reset) once they have spent `stay_hours` there."""
    t["stay"] = t.get("stay", 0) + 1
    if t["stay"] < int(_kind(ctx.cfg, t["kind"]).get("stay_hours", 1)):
        return False
    t["stay"] = 0
    return True


def _plunder(ctx: Ctx, t: dict) -> None:
    w = ctx.world
    share = float(_kind(ctx.cfg, "raid")["loot_share"]) * _defense(w)
    home = t["location"]
    took: dict[str, int] = {}
    coins = 0
    for c in w.chests.values():
        if c.location != home:
            continue
        for item, n in sorted(c.items.items()):
            k = int(n * share + 0.5)
            if k:
                ops.burn(w, c.items, item, k)
                took[item] = took.get(item, 0) + k
        k = int(c.coins * share + 0.5)
        if k:
            ops.burn_coins(w, c, k)
            coins += k
    plot = w.plots.get(home)
    yard = float(_kind(ctx.cfg, "raid").get("yard_share") or 0) * _defense(w)
    for b in (plot.buildings if plot is not None and yard > 0 else []):  # what lies ready in the yard
        for item, n in sorted(b["items"].items()):
            k = int(n * yard + 0.5)
            if k:
                ops.burn(w, b["items"], item, k)
                took[item] = took.get(item, 0) + k
    for item, k in took.items():
        t["loot"][item] = t["loot"].get(item, 0) + k
    t["loot_coins"] += coins
    owner = _homes(w).get(home)
    what = ", ".join(x for x in (fmt_items(took) if took else "", f"{coins} coins" if coins else "") if x) or "nothing"
    ctx.emit("plundered", f"The bandits plundered {_name(w, home)}: they took {what}.", visibility="public",
             to=[owner] if owner else None, threat=t["id"], home=home, items=took, coins=coins)
    route = t["route"]
    nxt = route[route.index(home) + 1] if home in route and route.index(home) + 1 < len(route) else None
    if nxt and t["hours_left"] > 1 and _stayed(ctx, t):
        t["location"] = nxt
        ctx.emit("threat_moves", f"The bandits move on to {_name(w, nxt)}.", visibility="public", threat=t["id"],
                 location=nxt, threat_kind="raid")


def _prowl(ctx: Ctx, t: dict) -> None:
    w, cfg = ctx.world, ctx.cfg
    k = _kind(cfg, "beast")
    home = t["location"]
    share = float(k["eat_share"]) * _defense(w)
    ate: dict[str, int] = {}
    for c in w.chests.values():
        if c.location != home:
            continue
        for item, n in sorted(c.items.items()):
            if cfg["items"].get(item, {}).get("food") and int(n * share + 0.5):
                q = int(n * share + 0.5)
                ops.burn(w, c.items, item, q)
                ate[item] = ate.get(item, 0) + q
    there = sorted(a.name for a in w.agents.values() if a.status == "active" and a.location == home)
    victim = ctx.rng.choice(there) if there else None
    hurt = 0
    if victim:
        a = w.agents[victim]
        hurt = min(a.health, ctx.rng.randint(1, int(k["damage_die"])) + int(k["maul"]))
        a.health -= hurt
        a.asleep = False
    bits = []
    if ate:
        bits.append(f"ate {fmt_items(ate)} from the chests")
    if victim:
        bits.append(f"mauled {victim} (-{hurt} health)")
    owner = _homes(w).get(home)
    ctx.emit("beast_attack", f"The beast at {_name(w, home)} " + (" and ".join(bits) or "found nothing") + ".",
             visibility="public", to=sorted({n for n in (owner, victim) if n}), threat=t["id"], home=home, items=ate,
             victim=victim, damage=hurt)
    homes = [h for h in sorted(_homes(w)) if h != home]
    if homes and t["hours_left"] > 1 and _stayed(ctx, t):
        t["location"] = ctx.rng.choice(homes)
        ctx.emit("threat_moves", f"The beast prowls on toward {_name(w, t['location'])}.", visibility="public",
                 threat=t["id"], location=t["location"], threat_kind="beast")


def _leave(ctx: Ctx, t: dict, burn: bool = False) -> None:
    w, cfg = ctx.world, ctx.cfg
    t["state"] = "gone"
    loc = t["location"]
    if t["kind"] == "traveler":
        fed = sum(t["fed"].values())
        ctx.emit("threat_left", f"The traveler left the village" + (" well fed." if fed >= _kind(cfg, "traveler")["need"]
                                                                   else " hungry."),
                 visibility="public", threat=t["id"], threat_kind="traveler")
        if t["scout"] and not t.get("chased_by"):
            day = w.day + 1 + ctx.rng.randint(0, 1)
            homes = _homes(w)
            rich = max(sorted(homes), key=lambda h: sum(c.coins for c in w.chests.values() if c.location == h),
                       default=None)
            if rich:
                r = schedule(ctx, "raid", clock.tick_of(cfg, day, ctx.rng.randint(cfg["day_start_hour"] + 3,
                                                                                 cfg["day_end_hour"] - 5)),
                             warn=False, target=homes[rich], cause="scout")
                r["from_scout"] = True
        return
    loot = fmt_items(t["loot"]) if t["loot"] else ""
    took = ", ".join(x for x in (loot, f"{t['loot_coins']} coins" if t["loot_coins"] else "") if x)
    if t["kind"] == "raid":
        ctx.emit("threat_left", "The bandits left" + (f" with {took}" if took else "") + ".", visibility="public",
                 threat=t["id"], threat_kind="raid", location=loc)
        # what they carried leaves the world with them (it was burned from the chests when taken)
        if burn and _kind(cfg, "raid").get("burn") and loc and loc not in w.fires:
            owner = _homes(w).get(loc)
            if owner:
                conflict.start_fire(ctx, loc, owner, cause="bandits")
    else:
        ctx.emit("threat_left", "The beast went back into the forest.", visibility="public", threat=t["id"],
                 threat_kind="beast", location=loc)


def _defeat(ctx: Ctx, t: dict) -> None:
    w, cfg = ctx.world, ctx.cfg
    t["state"] = "defeated"
    loc = w.locations[t["location"]]
    fighters = t["fighters"]
    total = sum(fighters.values()) or 1
    purse = t["loot_coins"] + round(_kind(cfg, t["kind"]).get("bounty", 0) * _scale(w))
    shares = {n: purse * d // total for n, d in sorted(fighters.items())}
    left = purse - sum(shares.values())
    for n in sorted(fighters, key=lambda n: (-fighters[n], n)):  # rounding leftovers to the best fighters
        if left <= 0:
            break
        shares[n] += 1
        left -= 1
    for n, c in shares.items():
        if c:
            ops.mint_coins(w, w.agents[n], c)
    for item, k in sorted(t["loot"].items()):
        ops.mint(w, loc.ground, item, k)
    names = ", ".join(sorted(fighters, key=lambda n: -fighters[n]))
    what = "bandits" if t["kind"] == "raid" else "beast"
    dropped = f" They dropped {fmt_items(t['loot'])} on the ground at {loc.name}." if t["loot"] else ""
    pay = ", ".join(f"{n} {c}" for n, c in shares.items() if c)
    ctx.emit("threat_defeated", f"{names} drove off the {what}!{dropped}" + (f" Coins for the defenders: {pay}." if pay
                                                                            else ""),
             visibility="public", threat=t["id"], threat_kind=t["kind"], location=loc.id, fighters=dict(fighters),
             coins=shares, loot=dict(t["loot"]))
    t["loot"], t["loot_coins"] = {}, 0


def _trim(world: World) -> None:
    done = [t for t in world.threats if t["state"] in ("gone", "defeated")]
    if max_gap(world.config):  # the last hostile one stays: calm_days counts from it
        last = max((t for t in world.threats if t["kind"] in HOSTILE), key=lambda t: t["arrive_tick"], default=None)
        done = [t for t in done if t is not last]
    for t in done[: max(0, len(done) - KEEP_FINISHED)]:
        world.threats.remove(t)


# ---------- villager actions ----------

def _can_defend(ctx: Ctx, a: Agent) -> bool:
    return here(ctx.world, a.location) is not None


@ACTIONS.action("defend", "Fight the bandits or the beast here: one round of dice, your best weapon (tool, club, "
                "spear) helps; they strike back. Several people together drive them off sooner.",
                available=_can_defend)
def defend(ctx: Ctx, a: Agent, _args) -> None:
    t = here(ctx.world, a.location)
    if t is None:
        raise ActionError("there is nothing to fight here")
    c = ctx.cfg["combat"]
    if a.health < c["min_health"]:
        raise ActionError(f"you are too weak to fight (health {a.health}, need {c['min_health']})")
    k = _kind(ctx.cfg, t["kind"])
    rng = ctx.rng
    item, atk, dmg = conflict.weapon(ctx.cfg, a)
    roll = rng.randint(1, c["die"])
    hit = roll == c["die"] or (roll != 1 and roll + atk >= c["hit_at"])
    dealt = min(t["hp"], rng.randint(1, c["damage_die"]) + dmg) if hit else 0
    t["hp"] -= dealt
    t["fought"] = True
    t["fighters"][a.name] = t["fighters"].get(a.name, 0) + dealt
    hurt = 0
    if t["hp"] > 0:
        back = rng.randint(1, c["die"])
        if back == c["die"] or (back != 1 and back + int(k["attack"]) >= c["hit_at"]):
            hurt = min(a.health, conflict.soak(ctx, a, rng.randint(1, int(k["damage_die"]))))
            a.health -= hurt
    conflict.wear(ctx, a, item)
    what = "the bandits" if t["kind"] == "raid" else "the beast"
    arms = f" with a {item}" if item else " bare-handed"
    text = (f"{a.name} fought {what}{arms}: " + (f"hit for {dealt}" if hit else "missed") +
            (f", and was hurt (-{hurt} health)" if hurt else "") + f". {what.capitalize()}: {t['hp']}/{t['max_hp']}.")
    ctx.emit("defend", text, actor=a.name, location=a.location, visibility="location", threat=t["id"],
             threat_kind=t["kind"], roll=roll, hit=hit, damage=dealt, hurt=hurt, hp=t["hp"], weapon=item)
    if t["hp"] <= 0:
        _defeat(ctx, t)


def _traveler_here(ctx: Ctx, a: Agent) -> dict | None:
    return here(ctx.world, a.location, ("traveler",))


class HelpArgs(BaseModel):
    item: str = Field(description="a food you carry")


@ACTIONS.action("help_stranger", "Give the traveler here one food you carry.", HelpArgs,
                available=lambda c, a: _traveler_here(c, a) is not None)
def help_stranger(ctx: Ctx, a: Agent, args: HelpArgs) -> None:
    t = _traveler_here(ctx, a)
    if t is None:
        raise ActionError("there is no traveler here")
    if not ctx.cfg["items"].get(args.item, {}).get("food"):
        raise ActionError(f"{args.item} is not food")
    if not ops.count(a.inventory, args.item):
        raise ActionError(f"you have no {args.item}")
    k = _kind(ctx.cfg, "traveler")
    need = int(k["need"])
    if sum(t["fed"].values()) >= need:
        raise ActionError("the traveler has had enough, thank you")
    ops.burn(ctx.world, a.inventory, args.item, 1)
    t["fed"][a.name] = t["fed"].get(a.name, 0) + 1
    ctx.emit("help_stranger", f"{a.name} gave the traveler {args.item}.", actor=a.name, location=a.location,
             visibility="location", threat=t["id"], item=args.item)
    if sum(t["fed"].values()) >= need:
        _thank(ctx, t)


def _thank(ctx: Ctx, t: dict) -> None:
    w, cfg = ctx.world, ctx.cfg
    k = _kind(cfg, "traveler")
    helpers = sorted(t["fed"])
    t["hours_left"] = min(t["hours_left"], 1)
    if t["scout"]:
        ctx.emit("stranger_thanks", "The traveler ate, nodded and said little.", location=t["location"],
                 visibility="location", threat=t["id"], helpers=helpers)
        return
    gifts = {}
    for n in helpers:
        roll = ctx.rng.randrange(3)
        who = w.agents[n]
        if roll == 0:
            ops.mint_coins(w, who, int(k["reward_coins"]))
            gifts[n] = f"{k['reward_coins']} coins"
        elif roll == 1 and "tool" in cfg["items"]:
            ops.mint(w, who.inventory, "tool", 1)
            gifts[n] = "a tool"
        else:
            spots = sorted(l.id for l in w.locations.values() if l.resources)
            spot = ctx.rng.choice(spots) if spots else who.location
            ops.mint(w, w.locations[spot].ground, "ore", 3)
            gifts[n] = f"a tip about something hidden at {_name(w, spot)}"
            w.mail.append(Letter("the traveler", n, f"For your kindness: I hid 3 ore at the {_name(w, spot)}. "
                                 "Pick it up before someone else does.", w.tick + clock.per_hour(cfg)))
    ctx.emit("stranger_thanks", "The traveler thanked his hosts: " + "; ".join(f"{n} got {g}" for n, g in gifts.items())
             + ".", location=t["location"], visibility="location", to=helpers, threat=t["id"], helpers=helpers,
             gifts=gifts)


@ACTIONS.action("chase_stranger", "Drive the traveler here out of the village.",
                available=lambda c, a: _traveler_here(c, a) is not None)
def chase_stranger(ctx: Ctx, a: Agent, _args) -> None:
    t = _traveler_here(ctx, a)
    if t is None:
        raise ActionError("there is no traveler here")
    t["chased_by"] = a.name
    t["state"] = "gone"
    ctx.emit("chase_stranger", f"{a.name} drove the traveler out of the village.", actor=a.name,
             location=a.location, visibility="public", threat=t["id"])


# ---------- god events ----------

class ThreatArgs(BaseModel):
    target: str | None = Field(None, description="villager whose house is hit first (empty: anyone)")
    in_days: int = Field(0, ge=0, le=14, description="in how many days it comes (0: within the hour)")
    warn: bool = Field(True, description="warn the village in advance")


def god_arrival_tick(cfg: dict, tick: int, days: int, warn: bool) -> int:
    """When a god raid/beast sent at `tick` arrives (the server shows it to the player right away)."""
    if days == 0:  # a warning today gives the village two hours to get ready
        return tick + (clock.hours(cfg, 2) if warn else 1)
    return clock.tick_of(cfg, clock.time_of(cfg, tick)[0] + days, int(_t(cfg).get("arrive_hour", 11)))


def _god_tick(ctx: Ctx, days: int, warn: bool) -> int:
    return god_arrival_tick(ctx.cfg, ctx.world.tick, days, warn)


@GOD.action("raid", "Bandits raid a house (warned days ahead or not). If nobody fights them they plunder chests "
            "house after house and burn one when they leave.", ThreatArgs)
def god_raid(ctx: Ctx, _god, args: ThreatArgs) -> None:
    schedule(ctx, "raid", _god_tick(ctx, args.in_days, args.warn), args.warn, args.target or None)


@GOD.action("beast", "A beast comes out of the forest (warned or not): eats stores and mauls people until driven "
            "off or it leaves.", ThreatArgs)
def god_beast(ctx: Ctx, _god, args: ThreatArgs) -> None:
    schedule(ctx, "beast", _god_tick(ctx, args.in_days, args.warn), args.warn, args.target or None)


class TravelerArgs(BaseModel):
    scout: bool = Field(False, description="secretly a bandit scout")


@GOD.action("traveler", "A hungry traveler comes to the square. A scout brings an unwarned raid unless chased off.",
            TravelerArgs)
def god_traveler(ctx: Ctx, _god, args: TravelerArgs) -> None:
    schedule(ctx, "traveler", ctx.world.tick + 1, False, None, scout=args.scout)


# ---------- observation, prompt, log ----------

def observe(world: World, name: str) -> dict:
    out = []
    for t in world.threats:
        if t["state"] == "coming" and t["warned"]:
            out.append({"what": WHAT[t["kind"]], "expected": f"day {t['arrive_day']} around {t['arrive_hour']}:00",
                        **({"where": t["target"]} if t["target"] else {})})
        elif t["state"] == "here":
            row = {"what": WHAT[t["kind"]], "where": t["location"]}
            if t["kind"] == "traveler":
                row["asks_food"] = max(0, _kind(world.config, "traveler")["need"] - sum(t["fed"].values()))
            else:
                row["strength"] = f"{t['hp']}/{t['max_hp']}"
                row["hours_left"] = t["hours_left"]
            out.append(row)
    return {"threats": out} if out else {}


def facts(cfg: dict) -> str | None:
    if not enabled(cfg):
        return None
    return (f"- Danger can come from outside: bandits{governance.opens_note(cfg, RAIDS)} plunder chests house by house and burn one when they leave; a "
            "beast eats stores and mauls people; a traveler asks for food. Warnings, if any, come in the news; "
            "\"threats\" lists what is expected or here. Anyone at the place can defend (a dice round, they strike "
            "back); driven-off bandits drop what they took." + _gap_fact(cfg))


def _gap_fact(cfg: dict) -> str:
    top = max_gap(cfg)
    if not top or not any(float(_kind(cfg, k).get("per_day") or 0) > 0 for k in HOSTILE):
        return ""
    return f" Bandits or a beast come at no fixed time, but rarely more than {top} days pass without one."


def view(world: World) -> list[dict]:
    return [{"id": t["id"], "kind": t["kind"], "state": t["state"], "location": t["location"], "hp": t["hp"],
             "max_hp": t["max_hp"], "hours_left": t["hours_left"], "warned": t["warned"], "target": t["target"],
             "arrive_day": t["arrive_day"], "arrive_hour": t["arrive_hour"]}
            for t in world.threats if t["state"] == "here" or (t["state"] == "coming" and t["warned"])]
