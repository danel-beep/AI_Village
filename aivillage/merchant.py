"""A merchant passing through (config `merchant`, off by default; on in «С нуля»): goods nobody in the village can
make, for coins that leave the village.

Rules, in the order a villager meets them:
- Once the trader has come (progress `feature:trader`; always with progress off) the merchant arrives at dawn at
  `place`, first after `first_gap_days`, then `gap_days` after he left (both seeded random ranges, own rng stream),
  and stays `stay_days`. His arrival and his leaving are public.
- He sells `goods` (item -> price, stock) at fixed prices; the stock (per 5 villagers, at least 1) is all he has
  this visit. Goods missing from the item table (crafting off) are skipped. The trader does not deal in them
  (`tradable: false`), villagers can pass them on as they like.
- buy_from_merchant at his place, with one's own coins, or `from_treasury` by whoever holds a treasury
  (works.holder: the mayor, a polity's holder): paid from it, the goods go to the holder, in public.
- What the goods do lives in their item specs: `warmth` (seasons.night_hunger), steel tools (crafting.tools),
  medicine (illness.cure_items).

State: `world.merchant` {"here": {"place", "until_day", "goods": {item: {"price", "left"}}} | None,
"next_day": int | None, "visits": int}; dropped from the world dict while empty.
Log: public `merchant_arrived`, `merchant_left`, `merchant_sale` (treasury purchases); location `merchant_sale`.
"""

from __future__ import annotations

import random

from pydantic import BaseModel, Field

from . import ops, population, progress, works
from .ops import Ctx, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, World

UNLOCK = "feature:trader"


def _c(cfg: dict) -> dict:
    return cfg.get("merchant") or {}


def enabled(cfg: dict) -> bool:
    return bool(_c(cfg).get("enabled"))


def place(cfg: dict) -> str:
    return _c(cfg).get("place", "market")


def goods(cfg: dict) -> dict[str, dict]:
    """The merchant's catalog: item -> {"price", "stock"}, only items the village knows."""
    return {i: g for i, g in (_c(cfg).get("goods") or {}).items() if i in cfg["items"]}


def here(world: World) -> dict | None:
    return (world.merchant or {}).get("here")


def _gap(rng: random.Random, span) -> int:
    lo, hi = span
    return rng.randint(int(lo), int(hi))


def _stock(cfg: dict, n: int) -> int:
    return max(1, round(n * population.size(cfg) / 5))


def new_day(ctx: Ctx, rng: random.Random) -> None:
    """Dawn: the merchant leaves when his stay is over, or arrives on the day drawn for him."""
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg) or not goods(cfg) or place(cfg) not in w.locations or not progress.unlocked(w, UNLOCK):
        return
    m = w.merchant
    if not m:
        m.update({"here": None, "next_day": w.day + _gap(rng, _c(cfg).get("first_gap_days", [1, 3])), "visits": 0})
    h = m.get("here")
    if h and w.day >= h["until_day"]:
        m["here"] = None
        m["next_day"] = w.day + _gap(rng, _c(cfg).get("gap_days", [4, 7]))
        ctx.emit("merchant_left", "The merchant has packed up and left the village. Nobody knows when he comes "
                 "again.", visibility="public", location=h["place"])
        return
    if h or w.day < (m.get("next_day") or 0):
        return
    days = int(_c(cfg).get("stay_days", 2))
    stock = {i: {"price": int(g["price"]), "left": _stock(cfg, int(g.get("stock", 1)))} for i, g in goods(cfg).items()}
    m["here"] = {"place": place(cfg), "until_day": w.day + days, "goods": stock}
    m["visits"] = m.get("visits", 0) + 1
    where = w.locations[place(cfg)].name
    offer = ", ".join(f"{i} {g['price']} coins ({g['left']} left)" for i, g in stock.items())
    ctx.emit("merchant_arrived", f"A merchant from afar has come to {where} for {days} day(s). He sells goods nobody "
             f"here makes, at fixed prices: {offer}. buy_from_merchant there.", visibility="public",
             location=place(cfg), goods={i: g["price"] for i, g in stock.items()}, until_day=w.day + days)


class BuyArgs(BaseModel):
    item: str
    qty: int = Field(1, gt=0, le=20)
    from_treasury: bool = Field(False, description="treasury holder only: pay from the treasury you hold; the goods "
                                                   "come to you and everyone hears of it")


@ACTIONS.action("buy_from_merchant", "Buy goods from the passing merchant where he stands (fixed prices, while his "
                "stock lasts). The coins leave the village with him.", BuyArgs,
                available=lambda c, a: enabled(c.cfg) and (h := here(c.world)) is not None
                and a.location == h["place"] and any(g["left"] > 0 for g in h["goods"].values()))
def buy_from_merchant(ctx: Ctx, a: Agent, args: BuyArgs) -> None:
    w = ctx.world
    h = here(w) if enabled(ctx.cfg) else None
    if h is None:
        raise ActionError("there is no merchant in the village now")
    if a.location != h["place"]:
        raise ActionError(f"the merchant is at {h['place']}")
    item = args.item.strip().lower()
    g = h["goods"].get(item)
    if g is None:
        raise ActionError(f"the merchant does not sell {args.item}; he sells: {', '.join(h['goods'])}")
    if g["left"] < args.qty:
        raise ActionError(f"the merchant has only {g['left']} {item} left")
    cost = g["price"] * args.qty
    payer = works.holder(w, a.name) if args.from_treasury else None
    if args.from_treasury and payer is None:
        raise ActionError("you hold no treasury")
    purse = payer.purse if payer else a
    if purse.coins < cost:
        raise ActionError(f"that costs {cost} coins, {'the treasury holds' if payer else 'you have'} {purse.coins}")
    ops.burn_coins(w, purse, cost)
    ops.mint(w, a.inventory, item, args.qty)
    g["left"] -= args.qty
    lot = fmt_items({item: args.qty})
    if payer:
        if payer.note:
            payer.note(f"{lot} from the merchant (bought by {a.name})", cost)
        ctx.emit("merchant_sale", f"{a.name} bought {lot} from the merchant for {cost} coins from {payer.label}; the "
                 f"goods are with {a.name}.", actor=a.name, visibility="public", location=a.location, item=item,
                 qty=args.qty, coins=cost, treasury=True)
        return
    ctx.emit("merchant_sale", f"{a.name} bought {lot} from the merchant for {cost} coins.", actor=a.name,
             visibility="location", location=a.location, item=item, qty=args.qty, coins=cost, treasury=False)


def hidden_actions(cfg: dict) -> frozenset[str]:
    """Kept out of the handbook while there is no merchant in this village."""
    return frozenset() if enabled(cfg) and goods(cfg) else frozenset({"buy_from_merchant"})


def observe(world: World, name: str) -> dict:
    h = here(world) if enabled(world.config) else None
    if h is None:
        return {}
    return {"merchant": {"at": h["place"], "leaves_at_dawn_of_day": h["until_day"],
                         "sells": {i: {"price": g["price"], "left": g["left"]} for i, g in h["goods"].items()}}}


def facts(cfg: dict) -> str | None:
    if not enabled(cfg) or not goods(cfg):
        return None
    from .governance import opens_note  # governance -> actions -> works: import here
    return (f"- A merchant from afar{opens_note(cfg, UNLOCK)} comes to the {place(cfg)} now and then, at no fixed time, "
            f"for {_c(cfg).get('stay_days', 2)} day(s), and sells what nobody in the village makes: "
            + ", ".join(f"{i} {g['price']} coins" for i, g in goods(cfg).items())
            + " (a few of each per visit; the trader does not deal in them). The coins leave with him. Whoever holds "
            "a treasury can buy from_treasury; the goods come to them and everyone hears of it.")


def view(world: World) -> dict | None:
    h = here(world)
    return {"at": h["place"], "goods": {i: g["left"] for i, g in h["goods"].items()}} if h else None
