"""Private plots: every house has a yard of a few cells where its family builds its own economy.

A plot belongs to a house (`world.plots[home_id]`) and is used by its owner and the owner's
spouse. Cells limit what fits: garden beds (sow grain, harvest more of it, nobody else may take
it), a chicken coop, a cow pen, beehives, a fence. Animals eat grain from the owner's chest every
night and fill their stock (eggs, milk, honey) up to a cap; `collect` takes the stock and ripe
beds. Coins paid for buildings, expansions and house upgrades go to the village treasury when
there is a government (burned otherwise), so the richest can buy more land and a bigger house.

There is no common field: grain grows only in garden beds. Lots for sale (aivillage/land.py) are plots
too (kind "lot", no house): their owner builds and collects there the same way. The shared places
(river, forest, mine, market) stay common. What lies in someone else's
yard can be stolen with `steal_from_plot`: the family notices if it is at home and awake, a fence
halves the chance, and other people there may see it. Thefts use the same events as `steal`
(steal_attempt / witness / steal / robbed), so reputation, feelings and theft reports just work.

Start sizes come from the agent spec (`plot_cells`, `house_level`, `buildings`), so a run config
or a "fairness" knob can make the start as equal or as unequal as wanted. Numbers: config `plots`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import ops, seasons
from .ops import Ctx, Event, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, Plot, World


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("plots", {}).get("enabled"))


def _p(cfg: dict) -> dict:
    return cfg["plots"]


# ---------- setup and queries ----------

def setup(world: World, spec: dict, home: str) -> None:
    """Called by new_world for each agent. Starting buildings are free (and start empty)."""
    cfg = world.config
    if not enabled(cfg):
        return
    p = _p(cfg)
    plot = Plot(owner=spec["name"], home=home, cells=int(spec.get("plot_cells", p["start_cells"])),
                house=max(1, min(p["house_max"], int(spec.get("house_level", 1)))))
    world.plots[home] = plot
    given = "buildings" in spec
    starts = p.get("start_buildings", {})
    kinds = spec["buildings"] if given else starts.get(spec.get("profession"), starts.get("default", []))
    for kind in kinds:
        if kind not in p["buildings"]:
            raise ValueError(f"agent {spec['name']}: unknown building '{kind}'")
        if not given and used_cells(cfg, plot) + p["buildings"][kind]["cells"] > plot.cells:
            continue  # default start: only what fits a small yard
        b = _add_building(world, plot, kind, built_day=world.day)
        if not given and "crop" in p["buildings"][kind]:  # default beds start sown, ripe on day 2
            spec_b = p["buildings"][kind]
            b["crop"], b["ripe_day"] = spec_b["crop"], world.day + 1
            b["amount"] = _bed_yield(cfg, spec_b, spec.get("profession"))
    if used_cells(cfg, plot) > plot.cells:
        raise ValueError(f"agent {spec['name']}: starting buildings need more than {plot.cells} cells")


def _bed_yield(cfg: dict, spec: dict, profession: str | None, tool: bool = False) -> int:
    """A garden bed's harvest: more when the crop is the sower's trade (farmer: grain) and with a tool (a hoe)."""
    bonus = spec.get("profession_bonus", 0) if spec["crop"] in cfg["professions"].get(profession, []) else 0
    return spec["yield"] + bonus + (spec.get("tool_bonus", 0) if tool else 0)


def _add_building(world: World, plot: Plot, kind: str, built_day: int) -> dict:
    b = {"id": world.new_id("b"), "kind": kind, "built_day": built_day, "items": {}}
    if "crop" in world.config["plots"]["buildings"][kind]:
        b["crop"] = None
        b["ripe_day"] = 0
    plot.buildings.append(b)
    return b


def used_cells(cfg: dict, plot: Plot) -> int:
    specs = _p(cfg)["buildings"]
    return sum(specs[b["kind"]]["cells"] for b in plot.buildings)


def may_use(world: World, name: str, plot: Plot) -> bool:
    if not plot.owner:
        return False  # a lot for sale
    if name == plot.owner:
        return True
    return any(name in m.spouses and plot.owner in m.spouses for m in world.kin.marriages.values())


def plot_here(world: World, a: Agent) -> Plot | None:
    return world.plots.get(a.location)


def own_plot_here(world: World, a: Agent) -> Plot | None:
    plot = plot_here(world, a)
    return plot if plot and may_use(world, a.name, plot) else None


def household(world: World, plot: Plot) -> list[str]:
    return [n for n in world.agents if may_use(world, n, plot)]


def stock(plot: Plot) -> dict[str, int]:
    out: dict[str, int] = {}
    for b in plot.buildings:
        for k, v in b["items"].items():
            out[k] = out.get(k, 0) + v
    return out


def has_fence(plot: Plot) -> bool:
    return any(b["kind"] == "fence" for b in plot.buildings)


def expand_price(cfg: dict, plot: Plot) -> int:
    p = _p(cfg)
    return p["expand_price"] + p["expand_price_step"] * plot.expansions


def upgrade_cost(cfg: dict, plot: Plot) -> dict | None:
    return _p(cfg)["house_upgrade"].get(str(plot.house + 1))


def health_bonus(world: World, a: Agent) -> int:
    """Extra night health for sleeping in a bigger house."""
    plot = world.plots.get(a.location)
    if not enabled(world.config) or plot is None or a.location != a.home:
        return 0
    return (plot.house - 1) * _p(world.config)["house_bonus_health"]


def _pay(world: World, a: Agent, coins: int, items: dict[str, int]) -> None:
    for k, v in items.items():
        ops.burn(world, a.inventory, k, v)
    if coins and world.config.get("governance", {}).get("enabled"):
        ops.move_coins(a, world.governance, coins)  # to the treasury (governance.pay_tax; no import cycle)
    elif coins:
        ops.burn_coins(world, a, coins)


def _check_cost(a: Agent, coins: int, items: dict[str, int]) -> None:
    lack = {k: v - ops.count(a.inventory, k) for k, v in items.items() if ops.count(a.inventory, k) < v}
    if a.coins < coins or lack:
        parts = ([f"{coins - a.coins} more coins"] if a.coins < coins else []) + ([fmt_items(lack)] if lack else [])
        raise ActionError(f"you need {coins} coins and {fmt_items(items)} in your inventory; missing: "
                          f"{', '.join(parts)}")


def _at_own_plot(ctx: Ctx, a: Agent) -> Plot:
    if not enabled(ctx.cfg):
        raise ActionError("there are no private plots in this village")
    plot = own_plot_here(ctx.world, a)
    if plot is None:
        raise ActionError(f"you must be at your own home ({a.home}) or on a lot you own to work on your land")
    if plot.kind == "home" and ctx.world.day < a.evicted_until_day:
        raise ActionError("you are locked out of your house until you pay the tax")
    return plot


def _at_own_home(ctx: Ctx, a: Agent) -> Plot:
    plot = _at_own_plot(ctx, a)
    if plot.kind != "home":
        raise ActionError("this is a lot: it has no house and cannot be enlarged; do this at your home")
    return plot


def _avail_own(ctx: Ctx, a: Agent) -> bool:
    return enabled(ctx.cfg) and own_plot_here(ctx.world, a) is not None


def _avail_home(ctx: Ctx, a: Agent) -> bool:
    plot = own_plot_here(ctx.world, a) if enabled(ctx.cfg) else None
    return bool(plot and plot.kind == "home")


# ---------- actions ----------

class BuildArgs(BaseModel):
    kind: str = Field(description="garden_bed, chicken_coop, cow_pen, beehive or fence")


@ACTIONS.action("build", "Build on your own land: your yard at home or a lot you own (garden_bed, chicken_coop, "
                "cow_pen, beehive, fence). "
                "Costs coins and materials from your inventory and takes free cells.", BuildArgs,
                available=_avail_own)
def build(ctx: Ctx, a: Agent, args: BuildArgs) -> None:
    plot = _at_own_plot(ctx, a)
    specs = _p(ctx.cfg)["buildings"]
    spec = specs.get(args.kind)
    if spec is None:
        raise ActionError(f"unknown building '{args.kind}'; can build: {', '.join(specs)}")
    have = sum(1 for b in plot.buildings if b["kind"] == args.kind)
    if "max" in spec and have >= spec["max"]:
        raise ActionError(f"your plot already has {have} {args.kind} (max {spec['max']})")
    free = plot.cells - used_cells(ctx.cfg, plot)
    if spec["cells"] > free:
        raise ActionError(f"{args.kind} needs {spec['cells']} free cells, your plot has {free} free of "
                          f"{plot.cells}; expand_plot buys more")
    _check_cost(a, spec["coins"], spec["items"])
    _pay(ctx.world, a, spec["coins"], spec["items"])
    b = _add_building(ctx.world, plot, args.kind, built_day=ctx.world.day)
    ctx.emit("build", f"{a.name} built a {args.kind} at {ctx.world.locations[plot.home].name}.",
             actor=a.name, location=plot.home, visibility="location", home=plot.home, building=b["id"],
             what=args.kind)


@ACTIONS.action("collect", "Collect what your land made here (eggs, milk, honey, ripe garden grain) into your inventory.",
                available=lambda c, a: _avail_own(c, a) and bool(stock(c.world.plots[a.location])))
def collect(ctx: Ctx, a: Agent, args) -> None:
    plot = _at_own_plot(ctx, a)
    got: dict[str, int] = {}
    for b in plot.buildings:
        if not b["items"]:
            continue
        for k, v in b["items"].items():
            got[k] = got.get(k, 0) + v
        ops.move_items(b["items"], a.inventory, dict(b["items"]))
    if not got:
        raise ActionError("nothing is ready on your plot yet")
    ctx.emit("collect", f"{a.name} collected {fmt_items(got)} from the plot.", actor=a.name, location=plot.home,
             visibility="location", home=plot.home, items=got)


def can_sow(ctx: Ctx, a: Agent) -> bool:
    plot = own_plot_here(ctx.world, a) if enabled(ctx.cfg) else None
    beds = _free_beds(ctx.cfg, plot) if plot else []
    crop = _p(ctx.cfg)["buildings"][beds[0]["kind"]]["crop"] if beds else None
    return bool(beds) and seasons.regen(ctx.cfg, ctx.world.day, crop, 1) > 0  # not in frozen ground


def _free_beds(cfg: dict, plot: Plot) -> list[dict]:
    specs = _p(cfg)["buildings"]
    return [b for b in plot.buildings if "crop" in specs[b["kind"]] and b["crop"] is None and not b["items"]]


def sow(ctx: Ctx, a: Agent, crop: str | None) -> None:
    """`plant` on your own plot: sow a free garden bed. Only your family may harvest it."""
    plot = _at_own_plot(ctx, a)
    specs = _p(ctx.cfg)["buildings"]
    beds = _free_beds(ctx.cfg, plot)
    if not beds:
        if not any("crop" in specs[b["kind"]] for b in plot.buildings):
            raise ActionError("your plot has no garden_bed; build one first")
        raise ActionError("every garden bed on your plot is sown or ripe (collect first)")
    b = beds[0]
    spec = specs[b["kind"]]
    if crop not in (None, spec["crop"]):
        raise ActionError(f"garden beds grow {spec['crop']} only")
    crop = spec["crop"]
    if seasons.regen(ctx.cfg, ctx.world.day, crop, 1) == 0:
        raise ActionError(f"the ground is frozen: {crop} cannot be planted this season")
    if ops.count(a.inventory, crop) < spec["seed"]:
        raise ActionError(f"you need {spec['seed']} {crop} in your inventory as seed")
    ops.burn(ctx.world, a.inventory, crop, spec["seed"])
    b["crop"], b["ripe_day"] = crop, ctx.world.day + spec["days"]
    b["amount"] = _bed_yield(ctx.cfg, spec, a.profession, tool=ops.count(a.inventory, "tool") > 0)
    where = "at home" if plot.kind == "home" else f"at {ctx.world.locations[plot.home].name}"
    ctx.emit("plant", f"{a.name} planted {crop} in a garden bed {where} (ripe on day {b['ripe_day']}).",
             actor=a.name, location=plot.home, visibility="location", resource=crop, building=b["id"],
             ripe_day=b["ripe_day"], private=True)


@ACTIONS.action("expand_plot", "Buy more land for your plot (at home). The price grows with every purchase.",
                available=_avail_home)
def expand_plot(ctx: Ctx, a: Agent, args) -> None:
    plot = _at_own_home(ctx, a)
    p = _p(ctx.cfg)
    if plot.cells + p["expand_cells"] > p["max_cells"]:
        raise ActionError(f"your plot is already as big as land allows ({plot.cells} cells)")
    price = expand_price(ctx.cfg, plot)
    _check_cost(a, price, {})
    _pay(ctx.world, a, price, {})
    plot.cells += p["expand_cells"]
    plot.expansions += 1
    ctx.emit("expand_plot", f"{a.name} bought land: the plot at {ctx.world.locations[plot.home].name} now has "
             f"{plot.cells} cells.", actor=a.name, location=plot.home, visibility="public", home=plot.home,
             cells=plot.cells, price=price)


@ACTIONS.action("upgrade_house", "Make your house bigger (at home): more health each night at home and more plot cells.",
                available=_avail_home)
def upgrade_house(ctx: Ctx, a: Agent, args) -> None:
    plot = _at_own_home(ctx, a)
    p = _p(ctx.cfg)
    cost = upgrade_cost(ctx.cfg, plot)
    if cost is None:
        raise ActionError(f"your house is already the biggest (level {plot.house})")
    _check_cost(a, cost["coins"], cost["items"])
    _pay(ctx.world, a, cost["coins"], cost["items"])
    plot.house += 1
    plot.cells += p["house_bonus_cells"]
    ctx.emit("upgrade_house", f"{a.name} enlarged the house to level {plot.house}.", actor=a.name,
             location=plot.home, visibility="public", home=plot.home, level=plot.house)


class StealPlotArgs(BaseModel):
    item: str = Field(description="egg, milk, honey or grain lying ready on this plot")
    qty: int = Field(1, ge=1)


def _avail_steal(ctx: Ctx, a: Agent) -> bool:
    plot = plot_here(ctx.world, a) if enabled(ctx.cfg) else None
    return bool(plot and not may_use(ctx.world, a.name, plot) and stock(plot))


@ACTIONS.action("steal_from_plot", "Steal what is ready (eggs, milk, honey, ripe grain) from the plot of the house you "
                "are at. The family notices if at home and awake; a fence makes it harder; others may see you.",
                StealPlotArgs, available=_avail_steal)
def steal_from_plot(ctx: Ctx, a: Agent, args: StealPlotArgs) -> None:
    w, cfg, p = ctx.world, ctx.cfg, _p(ctx.cfg)
    plot = plot_here(w, a) if enabled(cfg) else None
    if plot is None:
        raise ActionError("you are not at anyone's plot (go to their home_<Name> or lot)")
    if may_use(w, a.name, plot):
        raise ActionError("this is your own plot; use collect")
    if not plot.owner:
        raise ActionError("this lot belongs to nobody and has nothing on it")
    have = stock(plot).get(args.item, 0)
    if have == 0:
        ready = fmt_items(stock(plot))
        raise ActionError(f"there is no {args.item} ready on this plot; ready: {ready}")
    owner = plot.owner
    guards = [o for o in household(w, plot) if w.agents[o].location == plot.home and ops.can_act(w.agents[o])]
    chance = 1.0
    if guards:
        chance *= cfg["steal_awake_target_success"]
        for g in guards:
            ctx.emit("steal_attempt", f"{a.name} tried to steal {args.item} from your plot!", actor=a.name,
                     to=[g])
    if has_fence(plot):
        chance *= p["fence_success"]
    success = chance >= 1 or ctx.rng.random() < chance
    victim = guards[0] if guards else owner
    witnesses = [o.name for o in w.agents.values()
                 if o.status == "active" and not o.asleep and o.location == a.location
                 and o.name != a.name and o.name not in guards and ctx.rng.random() < cfg["steal_notice_chance"]]
    for x in witnesses:
        ctx.emit("witness", f"You saw {a.name} steal {args.item} from {owner}'s plot!", actor=a.name, to=[x],
                 thief=a.name, victim=owner)
    if not success:
        why = " (the fence held)" if not guards else ""
        ctx.emit("steal", f"Your theft from {owner}'s plot failed{why}.", actor=a.name, to=[a.name], victim=victim,
                 success=False, witnesses=witnesses, home=plot.home)
        return
    qty = min(args.qty, p["steal_max"], have)
    left = qty
    for b in plot.buildings:
        n = min(left, b["items"].get(args.item, 0))
        if n:
            ops.move_items(b["items"], a.inventory, {args.item: n})
            left -= n
    ctx.emit("steal", f"You stole {qty} {args.item} from {owner}'s plot.", actor=a.name, to=[a.name],
             victim=victim, success=True, qty=qty, item=args.item, witnesses=witnesses, home=plot.home)
    ctx.emit("robbed", f"Someone stole {qty} {args.item} from your plot.", to=household(w, plot), victim=owner,
             home=plot.home)


# ---------- engine hooks ----------

def after_night(ctx: Ctx) -> None:
    """New day: garden beds ripen, fed animals produce. Called by engine.night after regrowth."""
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        return
    specs = _p(cfg)["buildings"]
    season = seasons.season_of(cfg, w.day) if cfg.get("seasons", {}).get("enabled") else None
    for plot in w.plots.values():
        if not plot.owner:
            continue
        chest = w.chests.get(f"chest_{plot.owner}")
        hungry: list[str] = []
        for b in plot.buildings:
            spec = specs[b["kind"]]
            if "crop" in spec:
                if b["crop"] and w.day >= b["ripe_day"]:
                    n = b.pop("amount", spec["yield"])
                    ops.mint(w, b["items"], b["crop"], n)
                    where = "" if plot.kind == "home" else f" at {w.locations[plot.home].name}"
                    ctx.emit("crop_ripe", f"The {b['crop']} in your garden bed{where} is ripe: {n} "
                             f"{b['crop']} ready to collect.", to=household(w, plot), location=plot.home,
                             resource=b["crop"], building=b["id"], by=plot.owner, private=True)
                    b["crop"], b["ripe_day"] = None, 0
                continue
            if "makes" not in spec or (w.day - b["built_day"]) % spec.get("every_days", 1):
                continue
            if season in spec.get("idle_seasons", []):
                continue
            feed = spec.get("feed", 0)
            if feed:
                if chest is None or ops.count(chest.items, spec["feed_item"]) < feed:
                    hungry.append(b["kind"])
                    continue
                ops.burn(w, chest.items, spec["feed_item"], feed)
            room = spec["cap"] - ops.count(b["items"], spec["makes"])
            if room > 0:
                ops.mint(w, b["items"], spec["makes"], min(room, spec["per_day"]))
        if hungry:
            feed_item = specs[next(b["kind"] for b in plot.buildings if b["kind"] in hungry)]["feed_item"]
            ctx.emit("hungry_animals", f"Your {', '.join(sorted(set(hungry)))} had no {feed_item} in your chest last "
                     f"night and made nothing. Store {feed_item} in your chest to feed them.",
                     to=household(w, plot), home=plot.home, animals=sorted(set(hungry)))


def _on_event(ctx: Ctx, ev: Event, names: list[str]) -> None:
    """A burned house loses everything ready on its plot and one house level."""
    if ev.kind != "house_burned" or not enabled(ctx.cfg):
        return
    plot = ctx.world.plots.get(ev.data.get("home"))
    if plot is None:
        return
    for b in plot.buildings:
        for k, v in list(b["items"].items()):
            ops.burn(ctx.world, b["items"], k, v)
        if b.get("crop"):
            b["crop"], b["ripe_day"] = None, 0
    plot.house = max(1, plot.house - 1)


ops.EVENT_HOOKS.append(_on_event)


# ---------- observation, prompt, log ----------

def _building_obs(cfg: dict, b: dict) -> dict:
    out = {"id": b["id"], "kind": b["kind"]}
    if b["items"]:
        out["ready"] = dict(b["items"])
    if b.get("crop"):
        out["growing"] = {"crop": b["crop"], "ripe_day": b["ripe_day"]}
    return out


def observe(world: World, name: str) -> dict:
    """`plot`: your own plot (wherever you are). `here_plot`: the yard you stand in, if it is someone else's.
    `village_plots`: how big everyone's land and house are (who is rich)."""
    cfg = world.config
    if not enabled(cfg):
        return {}
    a = world.agents[name]
    out: dict = {}
    mine = next((p for p in world.plots.values() if p.home == a.home and may_use(world, name, p)), None) \
        or next((p for p in world.plots.values() if p.owner == name and p.kind == "home"), None)
    if mine:
        up = upgrade_cost(cfg, mine)
        out["plot"] = {
            "home": mine.home, "cells": mine.cells, "free_cells": mine.cells - used_cells(cfg, mine),
            "house_level": mine.house, "buildings": [_building_obs(cfg, b) for b in mine.buildings],
            "expand_price": expand_price(cfg, mine) if mine.cells < _p(cfg)["max_cells"] else None,
            "upgrade_house": ({"coins": up["coins"], "items": up["items"]} if up else None),
        }
    here = world.plots.get(a.location)
    if here and here.owner and not may_use(world, name, here):
        out["here_plot"] = {"owner": here.owner, "house_level": here.house, "fence": has_fence(here),
                            "ready": stock(here),
                            "family_home": [n for n in household(world, here)
                                            if world.agents[n].location == here.home]}
    out["village_plots"] = {p.owner: {"cells": p.cells, "house": p.house,
                                      "buildings": len([b for b in p.buildings if b["kind"] != "fence"])}
                            for p in world.plots.values() if p.kind == "home"}
    return out


def facts(cfg: dict) -> str:
    p = _p(cfg)
    parts = []
    for kind, s in p["buildings"].items():
        cost = " + ".join(x for x in ([f"{s['coins']} coins"] if s["coins"] else []) + [fmt_items(s["items"])])
        if "crop" in s:
            bonus = (f" ({s['yield'] + s['profession_bonus']} if you are a "
                     f"{'/'.join(k for k, v in cfg['professions'].items() if s['crop'] in v)})"
                     if s.get("profession_bonus") else "")
            hoe = f", +{s['tool_bonus']} if you carry a tool" if s.get("tool_bonus") else ""
            what = f"plant {s['seed']} {s['crop']} -> {s['yield']}{bonus}{hoe} after {s['days']} nights, only yours"
        elif "makes" in s:
            every = f"/{s['every_days']} days" if s.get("every_days", 1) > 1 else "/day"
            feed = f", eats {s['feed']} {s['feed_item']}/night from your chest" if s.get("feed") else ""
            what = f"{s['per_day']} {s['makes']}{every}{feed}, holds {s['cap']}"
        else:
            what = f"thieves succeed {int(p['fence_success'] * 100)}% as often"
        parts.append(f"{kind} ({s['cells']} cells, {cost}): {what}")
    return (f"- Your plot: the yard at your home, {p['start_cells']} cells at start. Grain grows only in garden "
            "beds. build there (or on a lot you own): "
            + "; ".join(parts) + ". collect takes what is ready. expand_plot buys +" + str(p["expand_cells"])
            + " cells (price grows); upgrade_house gives +" + str(p["house_bonus_cells"]) + " cells and more health"
            " at night." + (" Coins paid go to the treasury." if cfg.get("governance", {}).get("enabled") else "")
            + " Others' yards can be robbed with steal_from_plot.")


def view(world: World) -> dict:
    """Plots for the viewer: size, house level, buildings with what is ready or growing."""
    return {h: {"owner": p.owner, "cells": p.cells, "house": p.house,
                **({"kind": "lot", "price": p.price, "for_sale": not p.owner} if p.kind == "lot" else {}),
                "buildings": [{"id": b["id"], "kind": b["kind"], "items": dict(b["items"]),
                               **({"crop": b["crop"], "ripe_day": b["ripe_day"]} if b.get("crop") else {})}
                              for b in p.buildings]}
            for h, p in world.plots.items()}


def holdings(world: World) -> dict[str, int]:
    """Items lying on plots (for invariants)."""
    out: dict[str, int] = {}
    for p in world.plots.values():
        for k, v in stock(p).items():
            out[k] = out.get(k, 0) + v
    return out
