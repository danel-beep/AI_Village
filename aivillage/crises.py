"""Soft world crises: crop failure, drought, rats, a trader's shortage, a caravan buying one good.

The first live run showed villagers live alone while food is easy; trades, gifts and thefts appear
only under need. Crises bring need now and then, and unevenly (only some yards and chests are hit),
so some villagers have something to sell and others a reason to ask, borrow or steal.

All numbers are in config block `crises` (economy modes tune them). A crisis is a dict in
`world.crises`: {"id", "kind", "text", "start_day", "end_day", "frozen": {loc: [resource]},
"prices": {item: {"buy"|"sell": factor}}}. It is active while start_day <= day < end_day.
The engine calls `new_day` at dawn (before regrowth), asks `blocks_regrowth` in the regrowth loop and
`price_factor` for trader prices; agents see active crises in `observe()["crises"]`.
"""

from __future__ import annotations

import random
from typing import Literal

from pydantic import BaseModel, Field

from . import ops, plots, tiles
from .ops import Ctx
from .registry import GOD, ActionError
from .state import World

KEEP_FINISHED = 5  # finished crises kept in the world (for gap_days and the log), oldest dropped


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("crises", {}).get("enabled"))


def active(world: World) -> list[dict]:
    return [c for c in world.crises if c["start_day"] <= world.day < c["end_day"]]


def blocks_regrowth(world: World, loc_id: str, resource: str) -> bool:
    return any(resource in c.get("frozen", {}).get(loc_id, []) for c in active(world))


def price_factor(world: World, item: str, side: str) -> float:
    """Multiplier on the trader's price; side "buy" = a villager buys from the trader, "sell" = sells to him."""
    f = 1.0
    for c in active(world):
        f *= c.get("prices", {}).get(item, {}).get(side, 1.0)
    return f


def observe(world: World, name: str) -> dict:
    cs = active(world)
    if not cs:
        return {}
    return {"crises": [{"what": c["text"], "days_left": c["end_day"] - world.day} for c in cs]}


def fact(cfg: dict) -> str | None:
    if not enabled(cfg):
        return None
    return ("- Hard times come now and then (crop failure, drought, rats in the stores, a trader short of food, "
            "a caravan buying one good dear). They are announced in the news, listed in \"crises\", and pass in a "
            "few days; they rarely hit everyone equally.")


def view(world: World) -> list[dict]:
    return [{"kind": c["kind"], "text": c["text"], "days_left": c["end_day"] - world.day} for c in active(world)]


# ---------- dawn ----------

def new_day(ctx: Ctx, rng: random.Random) -> None:
    """Dawn: announce crises that ended, maybe start a new one. Called before regrowth."""
    w, cfg = ctx.world, ctx.cfg
    for c in w.crises:  # also crises the god started while random ones are off
        if c["end_day"] == w.day:
            ctx.emit("crisis_over", f"The {c['title']} is over.", visibility="public", crisis=c["id"],
                     crisis_kind=c["kind"])
    if not enabled(cfg):
        return
    s = cfg["crises"]
    if w.day < s["first_day"] or len(active(w)) >= s["max_active"]:
        return
    last_end = max((c["end_day"] for c in w.crises), default=s["first_day"] - s["gap_days"])
    quiet = w.day - last_end  # calm days so far; after max_quiet_days a crisis comes for sure
    if quiet < s["gap_days"]:
        return
    if quiet < s.get("max_quiet_days", 10**6) and rng.random() >= s["chance_per_day"]:
        return
    kinds = [k for k, spec in s["kinds"].items() if spec.get("weight", 0) > 0 and _possible(w, k, spec)]
    if not kinds:
        return
    kind = rng.choices(kinds, weights=[s["kinds"][k]["weight"] for k in kinds])[0]
    start(ctx, rng, kind)


def start(ctx: Ctx, rng: random.Random, kind: str, days: int | None = None) -> dict:
    """Start a crisis of `kind` today (also used by tests and the god panel)."""
    w, spec = ctx.world, ctx.cfg["crises"]["kinds"][kind]
    lo, hi = spec["days"]
    days = days or rng.randint(lo, hi)
    c = {"id": w.new_id("crisis"), "kind": kind, "start_day": w.day, "end_day": w.day + days,
         "frozen": {}, "prices": {}}
    STARTERS[kind](ctx, rng, spec, c, days)
    w.crises.append(c)
    finished = [x for x in w.crises if x["end_day"] <= w.day]
    for old in finished[:-KEEP_FINISHED]:
        w.crises.remove(old)
    ctx.emit("crisis", c["text"], visibility="public", crisis=c["id"], crisis_kind=kind, days=days)
    return c


def _food_locations(w: World, resources: list[str]) -> dict[str, list[str]]:
    """Locations holding any of `resources` (by config, so generated patches count too)."""
    out: dict[str, list[str]] = {}
    for loc_id, loc in w.locations.items():
        spec = w.config["locations"].get(loc_id, {}).get("resources", {})
        rs = [r for r in resources if r in spec]
        if rs:
            out[loc_id] = rs
    return out


def _possible(w: World, kind: str, spec: dict) -> bool:
    if kind in ("crop_failure", "drought"):  # pointless when nothing of it is left (winter)
        sown = kind == "crop_failure" and spec.get("garden_share") and any(  # no common field: gardens only
            b.get("crop") in spec["resources"] for p in w.plots.values() for b in p.buildings)
        return bool(sown) or any(w.locations[l].resources.get(r, 0) > 0
                                 for l, rs in _food_locations(w, spec["resources"]).items() for r in rs)
    if kind in ("shortage", "caravan"):
        return any(i in w.config["items"] for i in spec["items"])
    return True


def _days(n: int) -> str:
    return "a day" if n == 1 else f"{n} days"


def _blight(ctx: Ctx, rng: random.Random, spec: dict, c: dict, days: int) -> None:
    w = ctx.world
    hit = _food_locations(w, spec["resources"])
    for loc_id, rs in hit.items():
        loc = w.locations[loc_id]
        for r in rs:
            tiles.scale(loc, r, spec["keep"])
            for k in [k for k, p in loc.planted.items() if p["resource"] == r]:
                del loc.planted[k]
    c["frozen"] = hit
    what = " and ".join(sorted({r for rs in hit.values() for r in rs}))
    if c["kind"] == "drought":
        c["title"] = "drought"
        c["text"] = (f"Drought! The river runs low and the bushes dry up: most {what} is gone and none grows back "
                     f"for {_days(days)}.")
        return
    c["title"] = "crop failure"
    gardens = _wither_gardens(ctx, rng, spec.get("garden_share", 0), set(spec["resources"]))
    if not hit:  # no common field: only the gardens suffer
        c["text"] = "Crop failure! Blight hits the gardens: what was sown in some home garden beds died."
        return
    c["text"] = (f"Crop failure! Blight hits the fields: most {what} is gone, sown beds died, and nothing "
                 f"grows back for {_days(days)}." + (" Some home gardens were hit too." if gardens else ""))


def _wither_gardens(ctx: Ctx, rng: random.Random, share: float, crops: set[str]) -> list[str]:
    """Sown garden beds in a random `share` of yards die (seed lost). Returns the hit homes."""
    w = ctx.world
    if not share or not plots.enabled(ctx.cfg):
        return []
    sown = [h for h, p in sorted(w.plots.items())
            if any(b.get("crop") in crops for b in p.buildings)]
    hit = rng.sample(sown, round(len(sown) * share)) if sown else []
    for h in hit:
        p = w.plots[h]
        for b in p.buildings:
            if b.get("crop") in crops:
                b["crop"], b["ripe_day"] = None, 0
        ctx.emit("crop_failed", "Blight killed what was sown in your garden beds.", to=plots.household(w, p),
                 location=h, home=h)
    return hit


def _rats(ctx: Ctx, rng: random.Random, spec: dict, c: dict, days: int) -> None:
    w = ctx.world
    chests = [ch for ch in sorted(w.chests.values(), key=lambda x: x.owner)
              if w.agents.get(ch.owner) and w.agents[ch.owner].status != "dead"]
    hit = rng.sample(chests, max(1, round(len(chests) * spec["share"]))) if chests else []
    victims, fed = [], []
    for ch in hit:
        eaten = {}
        for item in spec["items"]:
            n = int(ops.count(ch.items, item) * spec["eat"])
            if n > 0:
                ops.burn(w, ch.items, item, n)
                eaten[item] = n
        victims.append(ch.owner)
        if eaten:
            fed.append(ch.owner)
        ctx.emit("rats", (f"Rats got into {ch.owner}'s chest and ate {ops.fmt_items(eaten)}." if eaten else
                          f"Rats got into {ch.owner}'s house but found no food in the chest."),
                 to=[ch.owner], location=ch.location, victim=ch.owner, eaten=eaten)
    c["title"] = "rat plague"
    c["victims"] = victims
    # Say only what happened: chests without food lose nothing (the final live run's report said otherwise).
    empty = [v for v in victims if v not in fed]
    if fed:
        c["text"] = f"Rats! Overnight they ate food from the chests of {', '.join(fed)}." + (
            f" They also got into the houses of {', '.join(empty)} but found no food." if empty else "")
    elif victims:
        c["text"] = f"Rats got into the houses of {', '.join(victims)} overnight but found no food in the chests."
    else:
        c["text"] = "Rats roam the village, looking for food."


def _shortage(ctx: Ctx, rng: random.Random, spec: dict, c: dict, days: int) -> None:
    item = rng.choice([i for i in spec["items"] if i in ctx.cfg["items"]])
    c["prices"] = {item: {"buy": spec["buy"]}}
    c["title"] = f"{item} shortage"
    c["text"] = (f"The trader is almost out of {item}: for {_days(days)} he sells it at {spec['buy']:g} times "
                 f"the usual price.")


def _caravan(ctx: Ctx, rng: random.Random, spec: dict, c: dict, days: int) -> None:
    item = rng.choice([i for i in spec["items"] if i in ctx.cfg["items"]])
    c["prices"] = {item: {"sell": spec["sell"]}}
    c["title"] = "caravan's visit"
    c["text"] = (f"A caravan has come to the market: for {_days(days)} its merchant buys {item} at "
                 f"{spec['sell']:g} times what the trader usually pays.")


STARTERS = {"crop_failure": _blight, "drought": _blight, "rats": _rats, "shortage": _shortage,
            "caravan": _caravan}


# ---------- god panel ----------

class CrisisArgs(BaseModel):
    kind: Literal["crop_failure", "drought", "rats", "shortage", "caravan"]
    days: int = Field(2, ge=1, le=10)


@GOD.action("crisis", "Start a world crisis now: crop_failure, drought, rats, shortage or caravan.", CrisisArgs)
def god_crisis(ctx: Ctx, _god, args: CrisisArgs) -> None:
    if args.kind not in ctx.cfg.get("crises", {}).get("kinds", {}):
        raise ActionError(f"crisis kind {args.kind} is not configured")
    start(ctx, ctx.rng, args.kind, args.days)
