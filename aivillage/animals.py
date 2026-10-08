"""Game animals and hunting (config block `animals`, off unless `animals.enabled`).

Herds live per location (`world.animals["herds"]`: {loc: {species: count}}). Where they live comes from
`animals.habitats` ({loc: {species: count}}) if the map sets it, else from the map itself: places with
`wood` get the forest species, places with `fish` the water ones; big game (`far: true`) only in the
farther half of those places counted in road hops from the square, and a `farthest` species only in the
farthest one. Counts scale with village size / `base_size`.

- **Small game** (`min_hunters` 1: hare, duck): `hunt(animal)` is one roll at once, d`die` + weapon
  attack >= the species' `hit_at` catches one; the meat and hide go to the hunter.
- **Big game** (`min_hunters` 2-3: deer, boar, elk): `hunt(animal)` joins the hunt party for that animal
  at that place (opened by the first hunter, open `party_hours` clock hours). At the end of an hour, if
  enough party members are still there and awake, the hunt runs: up to `rounds` rounds, each member in a
  shuffled order strikes (d`die` + weapon attack >= `hit_at` hits for d`damage_die` + weapon damage);
  a species with `attack` strikes back at one of them each round. Whoever lands the killing blow takes
  all the meat and hide. Not enough hunters when the party closes, or the animal survives the rounds:
  it gets away. Weapons are `combat.weapons` (conflict.weapon, the best one carried).
- **Herds**: every hunt (caught or not) adds to the place's `pressure`. At night, from a place hunted
  `flee_after` times that day, `flee_share` of each species moves to its calmest other habitat; then
  each herd grows by `breed` x n x (1 - n / cap) (a herd of fewer than 2 does not grow); pressure
  halves. A hunted-out habitat stays empty unless animals move in, or a pair strays in from the wild
  (`stray_chance` per night).

The engine calls `setup` (new_world), `end_of_hour` (hunts; the night upkeep on the day's last hour) and
`observe`; run.py logs `view`. All randomness outside actions uses the own stream `animals`.
"""

from __future__ import annotations

import random
from collections import deque

from pydantic import BaseModel, Field

from . import conflict, labor, ops, progress
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, World

ACTION_NAMES = ("hunt",)
BIG_GAME = "feature:big_game"  # progress.py: with stages on, big game opens at the hamlet (plan: stage 1)
progress.DEFAULT_UNLOCKS.setdefault(BIG_GAME, {"stage": "hamlet"})


def _c(cfg: dict) -> dict:
    return cfg.get("animals") or {}


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def hidden_actions(cfg: dict) -> frozenset[str]:
    """Actions to leave out of the handbook when animals are off."""
    return frozenset() if enabled(cfg) else frozenset(ACTION_NAMES)


def _species(cfg: dict) -> dict:
    return _c(cfg)["species"]


def _rng(world: World) -> random.Random:
    return random.Random(f"{world.config['seed']}:{world.tick}:animals")


# ---------- setup ----------

def _hops(world: World, start: str) -> dict[str, int]:
    if start not in world.locations:
        return {}
    dist, todo = {start: 0}, deque([start])
    while todo:
        cur = todo.popleft()
        for nb in sorted(world.locations[cur].neighbors):
            if nb in world.locations and nb not in dist:
                dist[nb] = dist[cur] + 1
                todo.append(nb)
    return dist


def auto_habitats(world: World) -> dict[str, dict[str, int]]:
    """Habitats from the map: species by `lives_by` resource, big game farther from the square."""
    cfg = world.config
    c = _c(cfg)
    dist = _hops(world, c.get("center", "square"))
    out: dict[str, dict[str, int]] = {}
    for sp, s in _species(cfg).items():
        places = sorted((lid for lid, spec in cfg["locations"].items()
                         if s["lives_by"] in spec.get("resources", {}) and lid in world.locations),
                        key=lambda lid: (dist.get(lid, 99), lid))
        if not places:
            continue
        wild = [lid for lid in places if cfg["locations"][lid].get("biome") in s.get("biomes", ())]
        if wild:  # a big map has its far biomes (mapgen `biome`): this species lives only there
            places = wild
        if s.get("farthest"):
            places = places[-1:]
        elif s.get("far") and not wild:
            places = places[len(places) // 2:]
        for lid in places:
            out.setdefault(lid, {})[sp] = int(s["start"])
    return out


def setup(world: World) -> None:
    if not enabled(world.config):
        return
    c = _c(world.config)
    for item, spec in sorted(c.get("items", {}).items()):  # meat, hide: added unless the config has them
        world.config["items"].setdefault(item, dict(spec))
    n = sum(1 for _ in world.agents)
    scale = max(1.0, n / float(c.get("base_size", 5)))
    habitats = c.get("habitats") or auto_habitats(world)
    herds, cap = {}, {}
    for lid in sorted(habitats):
        if lid not in world.locations:
            continue
        for sp, count in sorted(habitats[lid].items()):
            if sp not in _species(world.config):
                continue
            k = max(1, round(int(count) * scale))
            herds.setdefault(lid, {})[sp] = k
            cap.setdefault(lid, {})[sp] = max(k, round(int(_species(world.config)[sp]["cap"]) * scale))
    world.animals = {"herds": herds, "cap": cap, "pressure": {}, "parties": [], "today": {}}


def _herd(world: World, loc: str) -> dict[str, int]:
    return (world.animals.get("herds") or {}).get(loc, {})


def _open(world: World, sp: str) -> bool:
    return int(_species(world.config)[sp]["min_hunters"]) <= 1 or progress.unlocked(world, BIG_GAME)


def _seen(world: World, loc: str) -> dict[str, int]:
    """The herds here a villager can see and hunt (big game is hidden until progress opens it)."""
    return {k: v for k, v in _herd(world, loc).items() if _open(world, k)}


# ---------- hunting ----------

def _party(world: World, loc: str, sp: str) -> dict | None:
    return next((p for p in world.animals.get("parties", []) if p["location"] == loc and p["species"] == sp), None)


def _strike(rng: random.Random, c: dict, s: dict, atk: int, dmg: int) -> tuple[int, bool, int]:
    roll = rng.randint(1, c["die"])
    hit = roll == c["die"] or (roll != 1 and roll + atk >= int(s["hit_at"]))
    return roll, hit, (rng.randint(1, c["damage_die"]) + dmg if hit else 0)


def _loot(world: World, a: Agent, s: dict) -> dict[str, int]:
    got = {}
    for item, n in sorted(s.get("loot", {}).items()):
        if n > 0:
            ops.mint(world, a.inventory, item, n)
            got[item] = n
    return got


def _press(world: World, loc: str) -> None:
    p = world.animals.setdefault("pressure", {})
    p[loc] = p.get(loc, 0) + 1
    t = world.animals.setdefault("today", {})
    t[loc] = t.get(loc, 0) + 1


def _take(world: World, loc: str, sp: str) -> None:
    h = world.animals["herds"][loc]
    h[sp] -= 1
    if h[sp] <= 0:
        del h[sp]
        if not h:
            del world.animals["herds"][loc]


class HuntArgs(BaseModel):
    animal: str = Field(description="an animal here (see animals_here)")


def _can_hunt(ctx: Ctx, a: Agent) -> bool:
    return enabled(ctx.cfg) and bool(_seen(ctx.world, a.location))


@ACTIONS.action("hunt", "Hunt an animal here. Small game: one try, a catch is yours. Big game: you join the "
                "hunt party for it here; it runs at the end of the hour when enough hunters are present, and "
                "the meat and hide go to whoever lands the killing blow.", HuntArgs, available=_can_hunt)
def hunt(ctx: Ctx, a: Agent, args: HuntArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        raise ActionError("there is no hunting in this village")
    sp = args.animal.strip().lower()
    herd = _seen(w, a.location)
    if sp not in _species(cfg):
        raise ActionError(f"unknown animal '{args.animal}' (animals: {', '.join(_species(cfg))})")
    if not herd.get(sp):
        seen = ", ".join(f"{k} x{v}" for k, v in sorted(herd.items())) or "none"
        raise ActionError(f"there is no {sp} here (animals here: {seen})")
    s, c = _species(cfg)[sp], cfg["combat"]
    item, atk, dmg = conflict.hunt_weapon(cfg, a)
    atk += labor.hunt_bonus(cfg, a)  # no professions: hunting mastery
    arms = f" with a {item}" if item else " bare-handed"
    if int(s["min_hunters"]) <= 1:
        labor.practice(ctx, a, "hunting")
        _press(w, a.location)
        roll, hit, _ = _strike(ctx.rng, c, s, atk, dmg)
        conflict.wear(ctx, a, item)
        if not hit:
            ctx.emit("hunt_miss", f"{a.name} hunted a {sp}{arms} and it got away.", actor=a.name,
                     location=a.location, visibility="location", species=sp, roll=roll, weapon=item)
            return
        _take(w, a.location, sp)
        got = _loot(w, a, s)
        ctx.emit("hunt_catch", f"{a.name} caught a {sp}{arms}: {ops.fmt_items(got)}.", actor=a.name,
                 location=a.location, visibility="location", species=sp, roll=roll, weapon=item, loot=got,
                 killer=a.name, hunters=[a.name])
        return
    if a.health < c["min_health"]:
        raise ActionError(f"you are too weak to hunt big game (health {a.health}, need {c['min_health']})")
    p = _party(w, a.location, sp)
    if p is None:
        p = {"id": w.new_id("hunt"), "location": a.location, "species": sp, "hunters": [],
             "opened_tick": w.tick, "hours_left": int(_c(cfg).get("party_hours", 1))}
        w.animals.setdefault("parties", []).append(p)
    if a.name in p["hunters"]:
        raise ActionError(f"you are already in the hunt party for the {sp} here")
    p["hunters"].append(a.name)
    need = int(s["min_hunters"])
    ctx.emit("hunt_party", f"{a.name} joined the hunt for a {sp} here{arms} ({len(p['hunters'])} hunter(s), "
             f"{need} needed; it runs at the end of the hour).", actor=a.name, location=a.location,
             visibility="location", species=sp, hunters=list(p["hunters"]), needed=need, party=p["id"], weapon=item)


def _present(world: World, p: dict) -> list[str]:
    return [n for n in p["hunters"] if (x := world.agents.get(n)) is not None and ops.can_act(x)
            and x.location == p["location"]]


def _run_party(ctx: Ctx, rng: random.Random, p: dict, hunters: list[str]) -> None:
    w, cfg = ctx.world, ctx.cfg
    sp, loc = p["species"], p["location"]
    s, c = _species(cfg)[sp], cfg["combat"]
    _press(w, loc)
    hp, killer = int(s["hp"]), None
    dealt: dict[str, int] = {n: 0 for n in hunters}
    hurt: dict[str, int] = {}
    gear = {n: conflict.hunt_weapon(cfg, w.agents[n]) for n in hunters}
    gear = {n: (g[0], g[1] + labor.hunt_bonus(cfg, w.agents[n]), g[2]) for n, g in gear.items()}
    for n in hunters:
        labor.practice(ctx, w.agents[n], "hunting")
    for _ in range(int(_c(cfg).get("rounds", 4))):
        order = list(hunters)
        rng.shuffle(order)
        for n in order:
            _, hit, d = _strike(rng, c, s, gear[n][1], gear[n][2])
            if hit:
                d = min(hp, d)
                hp -= d
                dealt[n] += d
                if hp <= 0:
                    killer = n
                    break
        if killer:
            break
        if s.get("attack") is not None:
            victim = w.agents[rng.choice(sorted(hunters))]
            back = rng.randint(1, c["die"])
            if back == c["die"] or (back != 1 and back + int(s["attack"]) >= c["hit_at"]):
                h = min(victim.health, conflict.soak(ctx, victim, rng.randint(1, int(s["damage_die"]))))
                victim.health -= h
                hurt[victim.name] = hurt.get(victim.name, 0) + h
    for n in hunters:
        conflict.wear(ctx, w.agents[n], gear[n][0])
    wounds = "".join(f", {n} was hurt (-{h} health)" for n, h in sorted(hurt.items()))
    names = ", ".join(hunters)
    if killer is None:
        ctx.emit("hunt_failed", f"The hunt for a {sp} ({names}) failed: it got away{wounds}.", location=loc,
                 visibility="location", species=sp, hunters=hunters, dealt=dealt, hurt=hurt, party=p["id"])
        return
    _take(w, loc, sp)
    got = _loot(w, w.agents[killer], s)
    ctx.emit("hunt_kill", f"The hunt for a {sp} ({names}) brought it down. {killer} landed the killing blow and "
             f"took {ops.fmt_items(got)}{wounds}.", actor=killer, location=loc, visibility="location", species=sp,
             hunters=hunters, killer=killer, loot=got, dealt=dealt, hurt=hurt, party=p["id"],
             weapons={n: g[0] for n, g in gear.items()})


def end_of_hour(ctx: Ctx) -> None:
    w = ctx.world
    if not enabled(ctx.cfg) or not w.animals:
        return
    rng = _rng(w)
    keep = []
    for p in w.animals.get("parties", []):
        sp = p["species"]
        need = int(_species(ctx.cfg)[sp]["min_hunters"])
        here = _present(w, p)
        p["hours_left"] -= 1
        if len(here) >= need and _herd(w, p["location"]).get(sp):
            _run_party(ctx, rng, p, here)
        elif p["hours_left"] <= 0 or not _herd(w, p["location"]).get(sp):
            _press(w, p["location"])
            ctx.emit("hunt_failed", f"The {sp} got away: the hunt needs {need} hunters here at once and had "
                     f"{len(here)}.", location=p["location"], visibility="location", species=sp, hunters=here,
                     needed=need, party=p["id"])
        else:
            keep.append(p)
    w.animals["parties"] = keep
    if w.hour + 1 >= ctx.cfg["day_end_hour"]:
        _night(ctx, rng)


def _night(ctx: Ctx, rng: random.Random) -> None:
    """Hunted herds move to their calmest other habitat, then every herd breeds from what is left."""
    w = ctx.world
    c = _c(ctx.cfg)
    herds, cap, pressure = w.animals["herds"], w.animals["cap"], w.animals.setdefault("pressure", {})
    today = w.animals.get("today", {})
    moved = []
    for loc in sorted(today):
        if today[loc] < int(c.get("flee_after", 3)) or loc not in herds:
            continue
        for sp in sorted(herds[loc]):
            homes = [h for h in sorted(cap) if h != loc and sp in cap[h]]
            if not homes:
                continue
            to = min(homes, key=lambda h: (pressure.get(h, 0), herds.get(h, {}).get(sp, 0) / cap[h][sp], h))
            n = -(-herds[loc][sp] * float(c.get("flee_share", 0.5)) // 1)  # ceil
            n = int(min(n, herds[loc][sp]))
            if n <= 0:
                continue
            herds[loc][sp] -= n
            herds.setdefault(to, {})[sp] = herds.get(to, {}).get(sp, 0) + n
            moved.append({"species": sp, "from": loc, "to": to, "count": n})
        herds[loc] = {k: v for k, v in herds[loc].items() if v > 0}
        if not herds[loc]:
            del herds[loc]
    for m in moved:
        ctx.emit("animals_moved", f"{m['count']} {m['species']} left {m['from']} for {m['to']}.", location=m["from"],
                 visibility="log", **m)
    for loc in sorted(herds):
        for sp in sorted(herds[loc]):
            n = herds[loc][sp]
            top = cap.get(loc, {}).get(sp, n)
            if n < 2 or n >= top:
                continue
            grow = float(_species(ctx.cfg)[sp]["breed"]) * n * (1 - n / top)
            born = int(grow) + (1 if rng.random() < grow - int(grow) else 0)
            herds[loc][sp] = min(top, n + born)
    for loc in sorted(cap):  # a hunted-out habitat: now and then a pair wanders in from the wild
        for sp in sorted(cap[loc]):
            if not herds.get(loc, {}).get(sp) and rng.random() < float(c.get("stray_chance", 0)):
                n = min(cap[loc][sp], int(c.get("stray_count", 2)))
                herds.setdefault(loc, {})[sp] = n
                ctx.emit("animals_moved", f"{n} {sp} came to {loc} from the wild.", location=loc, visibility="log",
                         species=sp, to=loc, count=n)
    w.animals["pressure"] = {k: v // 2 for k, v in sorted(pressure.items()) if v // 2 > 0}
    w.animals["today"] = {}


# ---------- observation, prompt, log ----------

def observe(world: World, name: str) -> dict:
    if not enabled(world.config) or not world.animals:
        return {}
    a = world.agents[name]
    herd = _seen(world, a.location)
    out: dict = {}
    if herd:
        sp = _species(world.config)
        out["animals_here"] = {k: {"count": v, "hunters_needed": int(sp[k]["min_hunters"])}
                               for k, v in sorted(herd.items())}
    parties = [{"animal": p["species"], "hunters": list(p["hunters"]),
                "hunters_needed": int(_species(world.config)[p["species"]]["min_hunters"])}
               for p in world.animals.get("parties", []) if p["location"] == a.location]
    if parties:
        out["hunt_parties_here"] = parties
    return out


def facts(cfg: dict) -> str | None:
    if not enabled(cfg):
        return None
    sp = _species(cfg)
    small = ", ".join(k for k, v in sp.items() if int(v["min_hunters"]) <= 1)
    big = ", ".join(f"{k} ({v['min_hunters']} hunters)" for k, v in sp.items() if int(v["min_hunters"]) > 1)
    loot = "; ".join(f"{k}: {ops.fmt_items(v.get('loot', {}))}" for k, v in sp.items())
    return (f"- Wild animals live in forests and by the water; \"animals_here\" shows them. Small game ({small}) "
            f"is hunted alone. Big game ({big}) only falls to that many hunters at the same place in the same "
            f"hour; the one who lands the killing blow takes all of it. A weapon carried helps. What each gives: "
            f"{loot}. Animals breed from those left, and leave places where they are hunted a lot.")


def view(world: World) -> dict:
    if not enabled(world.config) or not world.animals:
        return {}
    return {"animals": {"herds": world.animals.get("herds", {}),
                        "parties": [{"location": p["location"], "species": p["species"], "hunters": p["hunters"]}
                                    for p in world.animals.get("parties", [])]}}
