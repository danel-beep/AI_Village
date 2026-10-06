"""Land for sale: empty lots anyone can buy, build on and sell on. Private property beyond the home yard.

A location whose config has a `"lot": {"cells", "price"}` spec is an empty piece of land. At the
start nobody owns it (`world.plots[lot].owner == ""`). `buy_land` there pays the price (to the
treasury, burned without a government) and makes it yours: from then on it is a plot like your yard
(plots.py): `build`, `plant`, `collect` work there for you and your spouse, and what lies on it can be
stolen with `steal_from_plot` (nobody guards a lot unless its owner stands there; a fence helps).
A lot has no house: no upgrade_house, no expand_plot, it never burns.

Owners trade land between themselves: `sell_land(lot, to, price)` offers it to one person for coins;
they `buy_land(lot)` from anywhere before the offer runs out, the coins go to the seller and the
buildings go with the land.

The hand-made map has a few lots in `config.locations`; a generated map (mapgen.py) lays out its
own, about one per two villagers (`land.lots`), so land is scarce. Numbers: config `land`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import clock, ops, plots
from .actions import _agent
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, Plot, World


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("land", {}).get("enabled")) and plots.enabled(cfg)


def lot_count(cfg: dict, villagers: int) -> int:
    n = cfg.get("land", {}).get("lots")
    return int(n) if n is not None else max(2, (villagers + 1) // 2)


def setup(world: World) -> None:
    """Called by new_world: one unowned plot per lot location."""
    if not enabled(world.config):
        return
    for lid, spec in world.config["locations"].items():
        lot = spec.get("lot")
        if lot:
            world.plots[lid] = Plot(owner="", home=lid, cells=int(lot["cells"]), house=0, kind="lot",
                                    price=int(lot["price"]))


def lots(world: World) -> list[Plot]:
    return [p for p in world.plots.values() if p.kind == "lot"]


def _lot(ctx: Ctx, lot_id: str | None, a: Agent) -> Plot:
    lid = lot_id or a.location
    plot = ctx.world.plots.get(lid)
    if plot is None or plot.kind != "lot":
        known = ", ".join(p.home for p in lots(ctx.world))
        raise ActionError(f"'{lid}' is not a lot; lots: {known}")
    return plot


class BuyArgs(BaseModel):
    lot: str | None = Field(None, description="lot id; default: the lot you stand on")


def _avail_buy(ctx: Ctx, a: Agent) -> bool:
    if not enabled(ctx.cfg):
        return False
    here = ctx.world.plots.get(a.location)
    return bool(here and here.kind == "lot" and not here.owner) or \
        any(p.sale and p.sale["to"] == a.name for p in lots(ctx.world))


@ACTIONS.action("buy_land", "Buy a lot: an empty one for sale while you stand on it (price to the village), or one "
                "its owner offered you with sell_land (from anywhere, coins to the owner). Then build on it like your yard.",
                BuyArgs, available=_avail_buy)
def buy_land(ctx: Ctx, a: Agent, args: BuyArgs) -> None:
    if not enabled(ctx.cfg):
        raise ActionError("there is no land for sale in this village")
    w = ctx.world
    plot = _lot(ctx, args.lot, a)
    name = w.locations[plot.home].name
    if plot.owner == a.name:
        raise ActionError("this lot is already yours")
    if plot.owner:
        sale = plot.sale
        if not sale or sale["to"] != a.name or sale["expires_tick"] <= w.tick:
            raise ActionError(f"{name} belongs to {plot.owner} and is not offered to you")
        price, seller = sale["price"], w.agents[plot.owner]
        if a.coins < price:
            raise ActionError(f"you need {price} coins, you have {a.coins}")
        ops.move_coins(a, seller, price)
        plot.owner, plot.sale = a.name, None
        ctx.emit("land_sold", f"{seller.name} sold {name} to {a.name} for {price} coins.", actor=a.name,
                 visibility="public", lot=plot.home, seller=seller.name, buyer=a.name, price=price, to=[seller.name])
        return
    if a.location != plot.home:
        raise ActionError(f"go to {plot.home} first: land is bought on the spot")
    if a.coins < plot.price:
        raise ActionError(f"{name} costs {plot.price} coins, you have {a.coins}")
    plots._pay(w, a, plot.price, {})
    plot.owner = a.name
    ctx.emit("land_bought", f"{a.name} bought {name} ({plot.cells} cells) for {plot.price} coins.", actor=a.name,
             location=plot.home, visibility="public", lot=plot.home, price=plot.price, cells=plot.cells)


class SellArgs(BaseModel):
    lot: str = Field(description="id of a lot you own")
    to: str = Field(description="who may buy it")
    price: int = Field(ge=0, description="coins they pay you")


@ACTIONS.action("sell_land", "Offer a lot you own to one person for coins; they buy_land it from anywhere for a few "
                "hours. The buildings on it go with the land.", SellArgs,
                available=lambda c, a: enabled(c.cfg) and any(p.owner == a.name for p in lots(c.world)))
def sell_land(ctx: Ctx, a: Agent, args: SellArgs) -> None:
    w = ctx.world
    plot = _lot(ctx, args.lot, a)
    if plot.owner != a.name:
        raise ActionError(f"{args.lot} is not yours")
    buyer = _agent(ctx, args.to)
    if buyer.name == a.name:
        raise ActionError("you cannot sell land to yourself")
    plot.sale = {"to": buyer.name, "price": args.price,
                 "expires_tick": w.tick + clock.hours(ctx.cfg, ctx.cfg["land"]["sale_ttl_hours"])}
    ctx.emit("land_offer", f"{a.name} offers you {w.locations[plot.home].name} ({plot.home}, {plot.cells} cells, "
             f"{len(plot.buildings)} buildings) for {args.price} coins: buy_land {plot.home} to accept.",
             actor=a.name, to=[buyer.name], lot=plot.home, price=args.price)


# ---------- observation, prompt ----------

def observe(world: World, name: str) -> dict:
    """`your_lots`: land you own besides your yard. `land_for_sale`: empty lots and their prices.
    `land_offers`: lots their owners offered you."""
    if not enabled(world.config):
        return {}
    cfg = world.config
    out: dict = {}
    mine = [p for p in lots(world) if plots.may_use(world, name, p)]
    if mine:
        out["your_lots"] = [{"id": p.home, "cells": p.cells, "free_cells": p.cells - plots.used_cells(cfg, p),
                             "buildings": [plots._building_obs(cfg, b) for b in p.buildings]} for p in mine]
    out["land_for_sale"] = [{"id": p.home, "name": world.locations[p.home].name, "cells": p.cells, "price": p.price}
                            for p in lots(world) if not p.owner]
    out["land_owners"] = {p.home: p.owner for p in lots(world) if p.owner}
    offers = [{"lot": p.home, "from": p.owner, "price": p.sale["price"], "cells": p.cells}
              for p in lots(world) if p.sale and p.sale["to"] == name and p.sale["expires_tick"] > world.tick]
    if offers:
        out["land_offers"] = offers
    return out


def facts(cfg: dict) -> str:
    sale = [(lid, s["lot"]) for lid, s in cfg["locations"].items() if s.get("lot")]
    listed = ", ".join(f"{lid} ({lot['cells']} cells, {lot['price']} coins)" for lid, lot in sale)
    from .governance import opens_note  # governance -> actions -> land: import here
    return (f"- Land: there is no common field. Empty lots can be bought{opens_note(cfg, 'action:buy_land')} with "
            f"buy_land while standing on them: "
            f"{listed}. A lot you own works like your yard (build, plant, collect; others can steal from it). "
            "sell_land offers your lot to someone for coins.")


def expire_offers(world: World) -> None:
    for p in lots(world):
        if p.sale and p.sale["expires_tick"] <= world.tick:
            p.sale = None
