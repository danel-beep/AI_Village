"""Fights, arson and random fires: violence as an ordinary choice with consequences.

`attack(target, take?, qty?)`: a fight of a few D&D-like rounds resolved at once by the engine's dice
(seeded, so replay is exact). Each round the attacker swings, then the defender swings back (a
sleeping defender wakes and misses the first round): roll d`die` + weapon attack, `hit_at` or more
hits (a natural max always hits, a 1 always misses) for d`damage_die` + weapon damage, taken off
health. A fighter at or below `give_up_health` stops the fight. Whoever dealt more damage wins; a
tie means the defender held. A winning attacker takes up to `loot_max` of the item asked for (or
`loot_coins_max` coins) from the loser's inventory. Health 0 sends a fighter to the hospital as
usual (engine.check_health). The best weapon carried is used automatically (`combat.weapons`: a
tool is a shovel or pick, a club, a smith's spear).

`set_fire()` at someone else's house: costs `arson_wood` wood and starts the same fire the god's
"fire" starts (the village hears only "the house is on fire"). The family at home and awake always
sees who did it; other people there with `steal_notice_chance`.

Everyone who sees a fight or arson thinks worse of the culprit (feelings and reputation, numbers in
`combat.feelings` / `combat.reputation`) and may report it like a theft (governance.report_theft).

`random_fires.per_day`: the chance that some house catches fire by itself at dawn (a setting).

Gear (`combat.gear`, «С нуля» plan task 9; only with crafting on, so «Обычный» is unchanged): more weapon
tiers (club -> spear / bow -> sword, made by crafting recipes), `hunt` bonuses against animals (`hunt_weapon`,
used by animals.py), armor (`soak`: the best one worn takes `block` off each hit, at least 1 still lands, in
fights, from big game and from threats) and wear (`wear`: one use per fight / hunt / defend for the weapon, one
per hit taken for the armor; `uses` before it breaks, kept in `Agent.tool_wear_by` like crafting's tools).
People see the weapon and armor of those next to them (`seen_gear` in `here.people`), and their own wear
(`observe`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import family, ops, plots, reputation, theft, works
from .actions import _agent_here
from .ops import Ctx, Event
from .registry import ACTIONS, ActionError
from .state import Agent, Fire


def _c(cfg: dict) -> dict:
    return cfg["combat"]


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("combat", {}).get("enabled"))


def _gear(cfg: dict) -> dict:
    return _c(cfg).get("gear") or {}


def gear_on(cfg: dict) -> bool:
    """Weapon tiers, armor and wear: `combat.gear.enabled` and crafting on (the recipes make the gear)."""
    return bool(cfg.get("combat", {}).get("gear", {}).get("enabled")) and bool(cfg.get("crafting", {}).get("enabled"))


def weapons(cfg: dict) -> dict[str, dict]:
    """Every weapon in this world: `combat.weapons`, plus the gear tiers when gear is on."""
    out = dict(_c(cfg)["weapons"])
    if gear_on(cfg):
        out.update(_gear(cfg).get("weapons", {}))
    return out


def weapon(cfg: dict, a: Agent) -> tuple[str | None, int, int]:
    """The best weapon `a` carries: (item or None for fists, attack bonus, damage bonus)."""
    best: tuple[str | None, int, int] = (None, 0, 0)
    for item, w in weapons(cfg).items():
        if ops.count(a.inventory, item) and w["attack"] + w["damage"] > best[1] + best[2]:
            best = (item, w["attack"], w["damage"])
    return best


def _hunt_bonus(cfg: dict, item: str, w: dict) -> int:
    return int(w.get("hunt", _gear(cfg).get("hunt", {}).get(item, 0)))


def hunt_weapon(cfg: dict, a: Agent) -> tuple[str | None, int, int]:
    """The weapon `a` hunts with (animals.py): like `weapon`, with gear on its `hunt` bonus added to attack."""
    if not gear_on(cfg):
        return weapon(cfg, a)
    best: tuple[str | None, int, int] = (None, 0, 0)
    for item, w in weapons(cfg).items():
        atk = w["attack"] + _hunt_bonus(cfg, item, w)
        if ops.count(a.inventory, item) and atk + w["damage"] > best[1] + best[2]:
            best = (item, atk, w["damage"])
    return best


def armor(cfg: dict, a: Agent) -> tuple[str | None, int]:
    """The best armor `a` wears: (item or None, damage blocked per hit). None with gear off."""
    best: tuple[str | None, int] = (None, 0)
    if gear_on(cfg):
        for item, s in _gear(cfg).get("armor", {}).items():
            if ops.count(a.inventory, item) and int(s["block"]) > best[1]:
                best = (item, int(s["block"]))
    return best


def soak(ctx: Ctx, a: Agent, damage: int) -> int:
    """Damage of one hit on `a` after armor (at least 1 of a real hit lands); the armor wears by one use."""
    item, block = armor(ctx.cfg, a)
    if item is None or damage <= 0:
        return damage
    wear(ctx, a, item)
    return max(1, damage - block)


def wear(ctx: Ctx, a: Agent, item: str | None) -> None:
    """One use of a weapon or armor; it breaks after `gear.uses`. No-op with gear off or for unlisted items."""
    if item is None or not gear_on(ctx.cfg):
        return
    uses = _gear(ctx.cfg).get("uses", {}).get(item)
    if not uses or not ops.count(a.inventory, item):
        return
    used = a.tool_wear_by.get(item, 0) + 1
    if used >= int(uses):
        a.tool_wear_by.pop(item, None)
        ops.burn(ctx.world, a.inventory, item, 1)
        ctx.emit("gear_broke", f"Your {item} wore out and broke.", to=[a.name], item=item)
    else:
        a.tool_wear_by[item] = used


def seen_gear(cfg: dict, a: Agent) -> dict:
    """What others see on `a` (`here.people[].gear`): {} with gear off or nothing carried."""
    if not gear_on(cfg):
        return {}
    w, ar = weapon(cfg, a)[0], armor(cfg, a)[0]
    g = {k: v for k, v in (("weapon", w), ("armor", ar)) if v}
    return {"gear": g} if g else {}


def observe(world, name: str) -> dict:
    """Your own weapon and armor with the uses left (gear on)."""
    cfg = world.config
    if not gear_on(cfg):
        return {}
    a = world.agents[name]
    uses = _gear(cfg).get("uses", {})
    out = {}
    for slot, item in (("weapon", weapon(cfg, a)[0]), ("armor", armor(cfg, a)[0])):
        if item:
            left = f" ({uses[item] - a.tool_wear_by.get(item, 0)} of {uses[item]} uses left)" if uses.get(item) else ""
            out[slot] = item + left
    return {"your_gear": out} if out else {}


def _witnesses(ctx: Ctx, a: Agent, exclude: set[str]) -> list[str]:
    return [o.name for o in ctx.world.agents.values()
            if o.status == "active" and not o.asleep and o.location == a.location and o.name not in exclude]


class AttackArgs(BaseModel):
    target: str = Field(description="a person here")
    take: str | None = Field(None, description="item (or 'coins') to take from them if you win")
    qty: int = Field(1, ge=1)


def _can_attack(ctx: Ctx, a: Agent) -> bool:
    return enabled(ctx.cfg) and any(o.name != a.name and o.status == "active" and o.location == a.location
                                    for o in ctx.world.agents.values())


@ACTIONS.action("attack", "Fight a person here: a few rounds of dice, a weapon you carry (tool, club, spear) helps. "
                "Both lose health; if you win you may take an item or coins from them. People here see it.",
                AttackArgs, available=_can_attack)
def attack(ctx: Ctx, a: Agent, args: AttackArgs) -> None:
    cfg = ctx.cfg
    if not enabled(cfg):
        raise ActionError("there is no fighting in this village")
    c = _c(cfg)
    d = _agent_here(ctx, a, args.target)
    if d.name == a.name:
        raise ActionError("you cannot attack yourself")
    if a.health < c["min_health"]:
        raise ActionError(f"you are too weak to fight (health {a.health}, need {c['min_health']})")
    if args.take and args.take != "coins" and args.take not in cfg["items"]:
        raise ActionError(f"unknown item '{args.take}'")
    rng = ctx.rng
    gear = {a.name: weapon(cfg, a), d.name: weapon(cfg, d)}
    worn = {a.name: armor(cfg, a)[0], d.name: armor(cfg, d)[0]}
    surprised = d.asleep
    d.asleep = False
    dealt = {a.name: 0, d.name: 0}
    rounds: list[dict] = []
    quit_by = None
    for r in range(1, c["rounds"] + 1):
        pairs = [(a, d)] + ([] if surprised and r == 1 else [(d, a)])
        for x, y in pairs:
            _, atk, dmg = gear[x.name]
            roll = rng.randint(1, c["die"])
            hit = roll == c["die"] or (roll != 1 and roll + atk >= c["hit_at"])
            hurt = min(y.health, soak(ctx, y, rng.randint(1, c["damage_die"]) + dmg)) if hit else 0
            y.health -= hurt
            dealt[x.name] += hurt
            rounds.append({"round": r, "by": x.name, "roll": roll, "bonus": atk, "hit": hit, "damage": hurt})
            if y.health <= c["give_up_health"]:
                quit_by = y.name
                break
        if quit_by:
            break
    if quit_by:
        winner = d.name if quit_by == a.name else a.name
    else:
        winner = a.name if dealt[a.name] > dealt[d.name] else d.name
    loot: dict[str, int] = {}
    if winner == a.name and args.take:
        if args.take == "coins":
            n = min(args.qty, c["loot_coins_max"], d.coins)
            if n:
                ops.move_coins(d, a, n)
                loot["coins"] = n
        else:
            n = min(args.qty, c["loot_max"], ops.count(d.inventory, args.take))
            if n:
                ops.move_items(d.inventory, a.inventory, {args.take: n})
                loot[args.take] = n
    for n, x in ((a.name, a), (d.name, d)):
        wear(ctx, x, gear[n][0])
    witnesses = _witnesses(ctx, a, {a.name, d.name})
    arms = lambda n: (f" with a {gear[n][0]}" if gear[n][0] else " bare-handed") + (f" in {worn[n]}" if worn[n] else "")
    hits = {n: sum(1 for x in rounds if x["by"] == n and x["hit"]) for n in dealt}
    how = (f"{a.name} attacked {d.name}{arms(a.name)}; {d.name} fought back{arms(d.name)}. "
           f"{len({x['round'] for x in rounds})} rounds: {a.name} hit {hits[a.name]} times (-{dealt[a.name]} health "
           f"to {d.name}), {d.name} hit {hits[d.name]} times (-{dealt[d.name]} to {a.name}). ")
    end = (f"{quit_by} gave up. " if quit_by else "") + f"{winner} won the fight."
    took = f" {a.name} took {ops.fmt_items(loot) if 'coins' not in loot else str(loot['coins']) + ' coins'} " \
           f"from {d.name}." if loot else ""
    ctx.emit("fight", how + end + took, actor=a.name, location=a.location, visibility="location", to=[d.name],
             attacker=a.name, defender=d.name, winner=winner, rounds=rounds, damage=dealt, loot=loot,
             weapons={n: g[0] for n, g in gear.items()}, witnesses=witnesses, surprised=surprised,
             **({"armor": worn} if gear_on(cfg) else {}))


@ACTIONS.action("set_fire", "Set fire to the house you are at (someone else's). Costs wood as kindling. The family, "
                "if at home and awake, sees you; others here may too.",
                available=lambda c, a: enabled(c.cfg) and _arson_target(c, a) is not None)
def set_fire(ctx: Ctx, a: Agent, args) -> None:
    cfg, w = ctx.cfg, ctx.world
    if not enabled(cfg):
        raise ActionError("there is no arson in this village")
    victims = _arson_target(ctx, a)
    if victims is None:
        raise ActionError("go to someone else's house (home_<Name>) to set it on fire")
    if a.location in w.fires:
        raise ActionError("this house is already burning")
    wood = _c(cfg)["arson_wood"]
    if ops.count(a.inventory, "wood") < wood:
        raise ActionError(f"you need {wood} wood as kindling")
    ops.burn(w, a.inventory, "wood", wood)
    house = a.location
    family_home = [o for o in victims if w.agents[o].location == house and ops.can_act(w.agents[o])]
    others = [n for n in _witnesses(ctx, a, {a.name, *family_home})
              if ctx.rng.random() < theft.notice(w, cfg["steal_notice_chance"] + works.notice_bonus(w))]
    owner = victims[0]
    ctx.emit("set_fire", f"You set fire to {owner}'s house.", actor=a.name, to=[a.name], victim=owner, house=house,
             witnesses=family_home + others)
    start_fire(ctx, house, owner, arsonist=a.name)
    for n in family_home + others:
        ctx.emit("arson_seen", f"You saw {a.name} set fire to {owner}'s house!", actor=a.name, to=[n],
                 arsonist=a.name, victim=owner, house=house)


def _arson_target(ctx: Ctx, a: Agent) -> list[str] | None:
    """The family whose house `a` stands in, if it is someone else's house."""
    w = ctx.world
    plot = w.plots.get(a.location)
    family_ = [o.name for o in w.agents.values() if o.home == a.location]
    if plot is not None and plot.kind == "home":
        family_ = plots.household(w, plot) or family_
    if not family_ or a.name in family_ or a.home == a.location:
        return None
    return family_


def start_fire(ctx: Ctx, house: str, victim: str, **data) -> None:
    cfg = ctx.cfg
    if house not in ctx.world.fires:
        ctx.world.fires[house] = Fire(house, cfg["fire_ticks"], cfg["fire_water_needed"])
    ctx.emit("fire", f"Smoke! {victim}'s house is on fire! It needs {cfg['fire_water_needed']} buckets "
             f"of water (fetch water at the river) and grows if nobody fights it; it burns down in "
             f"{cfg['fire_ticks']} hours.", visibility="public", victim=victim, house=house, **data)


def random_fire(ctx: Ctx) -> None:
    """Dawn: with `random_fires.per_day` chance a random house catches fire by itself."""
    w = ctx.world
    chance = float(ctx.cfg.get("random_fires", {}).get("per_day") or 0)
    if chance <= 0 or ctx.rng.random() >= chance:
        return
    homes = sorted({a.home: a.name for a in w.agents.values()
                    if a.status == "active" and a.home not in w.fires}.items())
    if homes:
        house, victim = ctx.rng.choice(homes)
        start_fire(ctx, house, victim, cause="accident")


# ---------- consequences ----------

def _on_event(ctx: Ctx, ev: Event, names: list[str]) -> None:
    """People think worse of whoever they saw fight or set a fire."""
    if ev.kind not in ("fight", "arson_seen") or not enabled(ctx.cfg):
        return
    w, c = ctx.world, _c(ctx.cfg)
    culprit = ev.actor
    if ev.kind == "fight":
        victim, seen = ev.data["defender"], [n for n in names if n not in (culprit, ev.data["defender"])]
    else:
        victim, seen = None, list(ev.to)
        victims = [o.name for o in w.agents.values() if o.home == ev.data["house"]]
        seen_victims = [n for n in seen if n in victims]
        seen = [n for n in seen if n not in victims]
        for v in seen_victims:
            _blame(w, v, culprit, c, "victim", ev)
    if victim:
        _blame(w, victim, culprit, c, "victim", ev)
    for n in seen:
        _blame(w, n, culprit, c, "witness", ev)


def _blame(w, who: str, culprit: str, c: dict, role: str, ev: Event) -> None:
    family.change(w, who, culprit, c["feelings"][role])
    reputation.note(w, who, culprit, c["reputation"][role], f"day {ev.day}: {ev.text}")


ops.EVENT_HOOKS.append(_on_event)


def facts(cfg: dict) -> str:
    c = _c(cfg)
    arms = ", ".join(f"{k} +{v['attack']} to hit/+{v['damage']} damage" for k, v in weapons(cfg).items())
    return (f"- Fights: attack a person here; {c['rounds']} rounds of d{c['die']} rolls ({c['hit_at']}+ hits for "
            f"d{c['damage_die']} health), the best weapon you carry is used ({arms}). Who dealt more damage wins; a "
            f"winning attacker may take up to {c['loot_max']} of one item or {c['loot_coins_max']} coins. "
            f"set_fire at someone else's house costs {c['arson_wood']} wood. People who see either remember it.")


def gear_facts(cfg: dict) -> list[str]:
    """Prompt facts with gear on: hunting bonuses, armor and how long each item lasts."""
    if not gear_on(cfg):
        return []
    g = _gear(cfg)
    hunt = ", ".join(f"{k} +{b}" for k, w in weapons(cfg).items() if (b := _hunt_bonus(cfg, k, w)))
    arm = ", ".join(f"{k} -{s['block']}" for k, s in g.get("armor", {}).items())
    uses = ", ".join(f"{k} {n}" for k, n in g.get("uses", {}).items())
    lines = []
    if hunt:
        lines.append(f"- Hunting: the weapon carried adds to the roll against animals ({hunt} more to hit them).")
    if arm:
        lines.append(f"- Armor: the best armor carried takes damage off every hit you take, in fights, from big "
                     f"game and from raiders or a beast ({arm} per hit; a hit still does at least 1).")
    if uses:
        lines.append(f"- Weapons and armor wear out: a weapon after that many fights, hunts or defends, armor after "
                     f"that many hits taken ({uses}). People see the weapon and armor of those next to them.")
    return lines
