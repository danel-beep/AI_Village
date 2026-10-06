"""Market board ("buy / sell") and who was seen where (config block `market`).

The economy review found two blockers to trade: nobody could see who had what to sell, and 26-38% of
turns went into walking around blindly looking for a partner (an offer accepted 5 times while its sender
was elsewhere). Two plain facts about the world fix both, without nudging anyone:

- Sell listings. `post_sale(items, price, hours)` puts items up from anywhere; the board holds them (they
  leave the seller's inventory) for `sale_hours`. `buy_sale(sale_id)` pays the price straight to the seller
  and the items are carried to the buyer, from anywhere when `remote`. `cancel_listing` takes back your own
  sale or your own order (post_order). Buy orders are the existing `post_order`; with `remote` they are
  delivered from anywhere too (actions.fulfill_order). Everyone sees the cheapest listings with sellers.
- Last seen. Each agent remembers where and when it last saw every villager: being at the same place
  (awake), or any event it witnessed that names an actor and a place. Observation lists the latest
  `seen_show` of them as "place, N h ago".
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import clock, ops
from .actions import ItemMap, _items_known, _need
from .ops import Ctx, Event, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, Sale, World


def _c(cfg: dict) -> dict:
    return cfg["market"]


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("market", {}).get("enabled"))


def remote(cfg: dict) -> bool:
    return enabled(cfg) and bool(_c(cfg).get("remote"))


def _reachable(ctx: Ctx, a: Agent) -> bool:
    return remote(ctx.cfg) or a.location == _c(ctx.cfg)["place"]


def _unit_price(s: Sale) -> float:
    return s.price / max(1, sum(s.items.values()))


# ---------- actions ----------

class PostSaleArgs(BaseModel):
    items: ItemMap = Field(description="items you put up for sale, as one lot")
    price: int = Field(gt=0, le=1000, description="coins for the whole lot")
    hours: int = Field(24, ge=1, description="how many hours the listing stays on the board")


@ACTIONS.action("post_sale", "Put items up for sale on the market board, from anywhere: the board holds them, the "
                "first villager to pay the price gets them and the coins go to you. Unsold items come back when "
                "it expires.", PostSaleArgs, available=lambda c, a: enabled(c.cfg) and bool(a.inventory))
def post_sale(ctx: Ctx, a: Agent, args: PostSaleArgs) -> None:
    c, w = _c(ctx.cfg), ctx.world
    if not enabled(ctx.cfg):
        raise ActionError("there is no market board in this village")
    if not args.items or "coins" in args.items:
        raise ActionError("a sale lists items (not coins)")
    _items_known(ctx, args.items)
    _need(a.inventory, args.items)
    if args.hours > c["max_sale_hours"]:
        raise ActionError(f"a listing stays at most {c['max_sale_hours']} hours")
    mine = [s for s in w.sales.values() if s.seller == a.name]
    if len(mine) >= c["max_own_sales"]:
        raise ActionError(f"you already have {len(mine)} listings on the board")
    for k, v in args.items.items():  # held by the board: comes back as new items on cancel / expiry
        ops.burn(w, a.inventory, k, v)
    s = Sale(w.new_id("sale"), a.name, dict(args.items), args.price, w.tick + clock.hours(ctx.cfg, args.hours))
    w.sales[s.id] = s
    ctx.emit("sale", f"{a.name} put up for sale ({s.id}): {fmt_items(s.items)} for {s.price} coins, "
             f"until {clock.label(ctx.cfg, s.expires_tick)}.", actor=a.name, visibility="public", sale=s.id)


class SaleIdArgs(BaseModel):
    sale_id: str


@ACTIONS.action("buy_sale", "Buy a listing from the market board: you pay its price to the seller and the items "
                "are carried to you.", SaleIdArgs,
                available=lambda c, a: enabled(c.cfg) and _reachable(c, a) and
                any(s.seller != a.name for s in c.world.sales.values()))
def buy_sale(ctx: Ctx, a: Agent, args: SaleIdArgs) -> None:
    w = ctx.world
    if not enabled(ctx.cfg):
        raise ActionError("there is no market board in this village")
    if not _reachable(ctx, a):
        raise ActionError(f"the market board is at the {w.locations[_c(ctx.cfg)['place']].name}")
    s = w.sales.get(args.sale_id)
    if s is None:
        raise ActionError(f"no listing '{args.sale_id}' on the board")
    if s.seller == a.name:
        raise ActionError("that is your own listing (cancel_listing takes it back)")
    if a.coins < s.price:
        raise ActionError(f"it costs {s.price} coins, you have {a.coins}")
    seller = w.agents.get(s.seller)
    if seller is None or seller.status == "dead":
        raise ActionError(f"{s.seller} can no longer sell")
    ops.move_coins(a, seller, s.price)
    for k, v in s.items.items():
        ops.mint(w, a.inventory, k, v)
    del w.sales[s.id]
    ctx.emit("trade", f"{seller.name} and {a.name} traded: {fmt_items(s.items)} for {s.price} coins.",
             actor=a.name, visibility="public", to=[seller.name], sale=s.id, partner=seller.name)


class ListingIdArgs(BaseModel):
    listing_id: str = Field(description="your sale or your order on the board")


def _own_listing(c: Ctx, a: Agent) -> bool:
    return any(s.seller == a.name for s in c.world.sales.values()) or any(
        o.by == a.name and o.status == "open" for o in c.world.orders.values())


@ACTIONS.action("cancel_listing", "Take your own sale or order off the board: the items or coins come back.",
                ListingIdArgs, available=_own_listing)
def cancel_listing(ctx: Ctx, a: Agent, args: ListingIdArgs) -> None:
    w = ctx.world
    s = w.sales.get(args.listing_id)
    o = w.orders.get(args.listing_id)
    if s is not None and s.seller == a.name:
        for k, v in s.items.items():
            ops.mint(w, a.inventory, k, v)
        del w.sales[s.id]
        what = fmt_items(s.items)
    elif o is not None and o.by == a.name and o.status == "open":
        ops.mint_coins(w, a, o.reward)
        o.status = "cancelled"
        what = f"{o.reward} coins"
    else:
        raise ActionError(f"you have no listing '{args.listing_id}' on the board")
    ctx.emit("listing_cancelled", f"{a.name} took {args.listing_id} off the board.", actor=a.name,
             visibility="public", listing=args.listing_id)
    ctx.emit("listing_cancelled", f"You took {args.listing_id} off the board; {what} back.", to=[a.name],
             listing=args.listing_id)


# ---------- upkeep ----------

def expire(ctx: Ctx) -> None:
    """Hourly: listings past their time go back to the seller (a dead seller's lot is gone)."""
    w = ctx.world
    for s in list(w.sales.values()):
        if s.expires_tick > w.tick:
            continue
        del w.sales[s.id]
        seller = w.agents.get(s.seller)
        if seller is not None and seller.status != "dead":
            for k, v in s.items.items():
                ops.mint(w, seller.inventory, k, v)
            ctx.emit("sale_expired", f"Nobody bought your listing {s.id}; {fmt_items(s.items)} back.",
                     to=[seller.name], sale=s.id)


def note_presence(world: World) -> None:
    """Every tick: awake villagers remember everyone at the same place."""
    by_place: dict[str, list[Agent]] = {}
    for a in world.agents.values():
        if a.status == "active":
            by_place.setdefault(a.location, []).append(a)
    for people in by_place.values():
        if len(people) < 2:
            continue
        for a in people:
            if a.asleep:
                continue
            for o in people:
                if o is not a:
                    a.seen[o.name] = {"place": o.location, "tick": world.tick}


def _on_event(ctx: Ctx, ev: Event, names: list[str]) -> None:
    if not ev.actor or not ev.location or ev.actor not in ctx.world.agents:
        return
    for n in names:
        a = ctx.world.agents.get(n)
        if a is not None and n != ev.actor:
            a.seen[ev.actor] = {"place": ev.location, "tick": ev.tick}


ops.EVENT_HOOKS.append(_on_event)


# ---------- observation ----------

def facts(cfg: dict) -> str:
    c = _c(cfg)
    where = "from anywhere" if c["remote"] else f"at the {cfg['locations'][c['place']]['name']}"
    orders = "; villagers' orders can be delivered from anywhere too" if c["remote"] else ""
    from .governance import opens_note  # governance -> actions -> market: import here
    return (f"- Market board{opens_note(cfg, 'action:post_sale')}: anyone can list items for sale (they are held by the board, {c['sale_hours']} h "
            f"by default) and buy a listing {where}; the coins go to the seller{orders}. \"for_sale\" shows the "
            f"cheapest listings. \"last_seen\" is where you last saw each villager.")


def observe(world: World, name: str) -> dict:
    cfg = world.config
    if not enabled(cfg):
        return {}
    c, a, out = _c(cfg), world.agents[name], {}
    others = sorted((s for s in world.sales.values() if s.seller != name), key=lambda s: (_unit_price(s), s.id))
    if others:
        out["for_sale"] = [{"id": s.id, "seller": s.seller, "items": s.items, "price": s.price}
                           for s in others[:c["show"]]]
    mine = [{"id": s.id, "items": s.items, "price": s.price, "until": clock.label(cfg, s.expires_tick)}
            for s in world.sales.values() if s.seller == name]
    if mine:
        out["your_sales"] = mine
    here = {o.name for o in world.agents.values() if o.location == a.location}
    per_hour = clock.per_hour(cfg)
    seen = sorted(((n, v) for n, v in a.seen.items() if n not in here and n in world.agents
                   and world.agents[n].status != "dead"), key=lambda x: -x[1]["tick"])
    if seen:
        out["last_seen"] = {n: f"{v['place']}, {max(0, world.tick - 1 - v['tick']) // per_hour} h ago"
                            for n, v in seen[:c["seen_show"]]}
    return out
