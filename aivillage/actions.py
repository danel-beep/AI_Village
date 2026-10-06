"""All agent actions. Each one validates fully before changing anything,
so a failed action never leaves the world half-changed."""

from __future__ import annotations

from collections import deque
from typing import Annotated

from pydantic import BaseModel, Field

from . import clock, crises, ops, plots, seasons, tiles
from .ops import Ctx, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, Debt, Letter, Offer

Qty = Annotated[int, Field(gt=0, le=1000)]
ItemMap = dict[str, Qty]


# ---------- helpers ----------

def _here(ctx: Ctx, a: Agent):
    return ctx.world.locations[a.location]


def _agent(ctx: Ctx, name: str) -> Agent:
    for other in ctx.world.agents.values():
        if other.name.lower() == name.strip().lower():
            return other
    raise ActionError(f"there is no villager named '{name}'")


def _agent_here(ctx: Ctx, a: Agent, name: str) -> Agent:
    other = _agent(ctx, name)
    if other.name == a.name:
        raise ActionError("you cannot do that to yourself")
    if other.status != "active" or other.location != a.location:
        raise ActionError(f"{other.name} is not here")
    return other


def _items_known(ctx: Ctx, items: dict) -> None:
    for k in items:
        if k not in ctx.cfg["items"]:
            raise ActionError(f"unknown item '{k}'")


def _need(a_items: dict, need: dict, who: str = "you") -> None:
    missing = {k: v - ops.count(a_items, k) for k, v in need.items() if ops.count(a_items, k) < v}
    if missing:
        raise ActionError(f"{who} lack {fmt_items(missing)}")


def _text(ctx: Ctx, text: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise ActionError("text is empty")
    return text[: ctx.cfg["max_text_len"]]


def _own_chest(ctx: Ctx, a: Agent):
    return ctx.world.chests[f"chest_{a.name}"]


def _chest_here(ctx: Ctx, a: Agent):
    for c in ctx.world.chests.values():
        if c.location == a.location:
            return c
    raise ActionError("there is no chest here")


def _has_chest_access(ctx: Ctx, a: Agent, chest) -> bool:
    if chest.owner == a.name:
        return ctx.world.day >= a.evicted_until_day
    return a.name in chest.shared_with


def shortest_path(ctx: Ctx, start: str, goal: str) -> list[str] | None:
    locs = ctx.world.locations
    prev: dict[str, str | None] = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            path = []
            while cur != start:
                path.append(cur)
                cur = prev[cur]
            return list(reversed(path))
        for n in locs[cur].neighbors:
            if n not in prev:
                prev[n] = cur
                q.append(n)
    return None


def step_move(ctx: Ctx, a: Agent, dest: str) -> None:
    src = a.location
    a.location = dest
    loc = ctx.world.locations[dest]
    ctx.emit("move", f"{a.name} left for {loc.name}.", actor=a.name, location=src, visibility="location")
    ctx.emit("move", f"{a.name} arrived at {loc.name}.", actor=a.name, location=dest, visibility="location",
             to=[a.name])


USED_UP = {"wood": "felled a tree", "grain": "harvested a whole bed", "berries": "picked a bush clean",
           "fish": "fished out a shoal", "stone": "broke up a rock", "ore": "mined out an ore vein",
           "gold": "dug out a gold seam"}


def work_hour(ctx: Ctx, a: Agent, resource: str) -> int:
    """One hour of gathering. Returns the amount gathered (may be 0 if exhausted)."""
    cfg = ctx.cfg
    loc = _here(ctx, a)
    if ctx.world.day < a.sick_until_day:
        ctx.emit("work", "You are sick and cannot work.", to=[a.name])
        return 0
    amount = cfg["work_base_yield"]
    if resource in cfg["professions"].get(a.profession, []):
        amount *= cfg["work_profession_multiplier"]
    using_tool = resource != "water" and ops.count(a.inventory, "tool") > 0
    if using_tool:
        amount *= cfg["work_tool_multiplier"]
    if resource == "water":
        amount = 2
    cap = cfg["locations"].get(loc.id, {}).get("resources", {}).get(resource, {}).get("per_hour")
    if cap:
        amount = min(amount, cap)  # gold: slow digging whatever the tools
    taken = tiles.take(loc, resource, amount)
    amount = sum(n for _, n in taken)
    if amount > 0:
        ops.mint(ctx.world, a.inventory, resource, amount)
    for slot, _ in taken:
        if slot >= 0 and loc.slots[resource][slot] == 0:  # log-only, for the map: a tree fell, a bed is bare
            ctx.emit("slot_empty", f"{a.name} {USED_UP.get(resource, 'used up a ' + resource + ' spot')} at the "
                     f"{loc.name}.", actor=a.name,
                     location=loc.id, resource=resource, slot=slot)
    if using_tool:
        a.tool_wear += 1
        if a.tool_wear >= cfg["tool_durability_hours"]:
            a.tool_wear = 0
            ops.burn(ctx.world, a.inventory, "tool", 1)
            ctx.emit("tool_broke", "Your tool wore out and broke.", to=[a.name])
    ctx.emit("work", f"You gathered {amount} {resource}." if amount else f"There is no {resource} left here.",
             actor=a.name, location=loc.id, to=[a.name], resource=resource, amount=amount,
             slots=[s for s, _ in taken if s >= 0])
    return amount


# ---------- movement & work ----------

class MoveArgs(BaseModel):
    to: str = Field(description="location id")


@ACTIONS.action("move", "Walk to a location. Far places take several hours; you keep walking automatically.",
                MoveArgs)
def move(ctx: Ctx, a: Agent, args: MoveArgs) -> None:
    if args.to not in ctx.world.locations:
        raise ActionError(f"unknown location '{args.to}'")
    if args.to == a.location:
        raise ActionError("you are already there")
    path = shortest_path(ctx, a.location, args.to)
    if not path:
        raise ActionError(f"no road to {args.to}")
    step_move(ctx, a, path[0])
    a.task = {"kind": "move", "path": path[1:]} if len(path) > 1 else None


class WorkArgs(BaseModel):
    hours: int = Field(1, ge=1, le=8, description="how many hours to keep working")
    resource: str | None = Field(None, description="what to gather here; default: the first resource here")


def _can_work(ctx: Ctx, a: Agent) -> bool:
    return bool(_here(ctx, a).resources)


@ACTIONS.action("work", "Gather a resource at this location. Your profession gives x3, a tool x2.",
                WorkArgs, available=_can_work)
def work(ctx: Ctx, a: Agent, args: WorkArgs) -> None:
    loc = _here(ctx, a)
    if not loc.resources:
        raise ActionError("nothing to gather here")
    res = args.resource
    if res is None:
        mine = [r for r in ctx.cfg["professions"].get(a.profession, []) if r in loc.resources]
        res = mine[0] if mine else next(iter(loc.resources))
    if res not in loc.resources:
        raise ActionError(f"there is no {res} here; available: {', '.join(loc.resources)}")
    hours = min(args.hours, ctx.cfg["max_work_hours"])
    work_hour(ctx, a, res)
    a.task = {"kind": "work", "resource": res, "hours_left": hours - 1} if hours > 1 else None


class CraftArgs(BaseModel):
    recipe: str
    times: int = Field(1, ge=1, le=10)


@ACTIONS.action("craft", "Make an item from a recipe (bread, fish_soup, club at home; tool, lock, spear at the smithy "
                "by a smith).",
                CraftArgs)
def craft(ctx: Ctx, a: Agent, args: CraftArgs) -> None:
    r = ctx.cfg["recipes"].get(args.recipe)
    if r is None:
        raise ActionError(f"unknown recipe '{args.recipe}'; known: {', '.join(ctx.cfg['recipes'])}")
    if r["where"] == "home" and a.location != a.home:
        raise ActionError(f"{args.recipe} can only be made at your home")
    if r["where"] != "home" and a.location != r["where"]:
        raise ActionError(f"{args.recipe} can only be made at the {r['where']}")
    if r["profession"] and a.profession != r["profession"]:
        raise ActionError(f"only a {r['profession']} can make {args.recipe}")
    need = {k: v * args.times for k, v in r["inputs"].items()}
    _need(a.inventory, need)
    for k, v in need.items():
        ops.burn(ctx.world, a.inventory, k, v)
    out = r["output"] * args.times
    ops.mint(ctx.world, a.inventory, args.recipe, out)
    ctx.emit("craft", f"{a.name} made {out} {args.recipe}.", actor=a.name, location=a.location,
             visibility="location")


class EatArgs(BaseModel):
    item: str
    qty: int = Field(1, ge=1, le=10)


@ACTIONS.action("eat", "Eat food from your inventory.", EatArgs,
                available=lambda c, a: any("food" in c.cfg["items"].get(i, {}) for i in a.inventory))
def eat(ctx: Ctx, a: Agent, args: EatArgs) -> None:
    info = ctx.cfg["items"].get(args.item)
    if not info or "food" not in info:
        raise ActionError(f"{args.item} is not food")
    _need(a.inventory, {args.item: args.qty})
    ops.burn(ctx.world, a.inventory, args.item, args.qty)
    a.satiety = min(ctx.cfg["satiety_max"], a.satiety + info["food"] * args.qty)
    ctx.emit("eat", f"You ate {args.qty} {args.item}. Satiety {a.satiety}.", actor=a.name, to=[a.name])


@ACTIONS.action("sleep", "Go to sleep until morning. Sleeping at home restores health.")
def sleep(ctx: Ctx, a: Agent, args) -> None:
    a.asleep = True
    a.task = None
    ctx.emit("sleep", f"{a.name} fell asleep.", actor=a.name, location=a.location, visibility="location",
             to=[a.name])


@ACTIONS.action("wait", "Do nothing for an hour.")
def wait(ctx: Ctx, a: Agent, args) -> None:
    pass


# ---------- talking ----------

class SayArgs(BaseModel):
    text: str


@ACTIONS.action("say", "Say something out loud; everyone at your location hears it.", SayArgs)
def say(ctx: Ctx, a: Agent, args: SayArgs) -> None:
    t = _text(ctx, args.text)
    ctx.emit("say", f'{a.name} says: "{t}"', actor=a.name, location=a.location, visibility="location",
             text_raw=t)


class WhisperArgs(BaseModel):
    to: str
    text: str


@ACTIONS.action("whisper", "Say something privately to one person at your location.", WhisperArgs)
def whisper(ctx: Ctx, a: Agent, args: WhisperArgs) -> None:
    other = _agent_here(ctx, a, args.to)
    t = _text(ctx, args.text)
    ctx.emit("whisper", f'{a.name} whispers to you: "{t}"', actor=a.name, to=[other.name], text_raw=t)
    ctx.emit("whisper", f'You whisper to {other.name}: "{t}"', actor=a.name, to=[a.name])
    ctx.emit("whisper_seen", f"{a.name} whispers something to {other.name}.", actor=a.name,
             location=a.location, visibility="location")


class LetterArgs(BaseModel):
    to: str
    text: str


@ACTIONS.action("letter", "Send a letter to anyone; it arrives next hour wherever they are.", LetterArgs)
def letter(ctx: Ctx, a: Agent, args: LetterArgs) -> None:
    other = _agent(ctx, args.to)
    t = _text(ctx, args.text)
    ctx.world.mail.append(Letter(a.name, other.name, t, ctx.world.tick + clock.per_hour(ctx.cfg)))
    ctx.emit("letter_sent", f"You sent a letter to {other.name}.", actor=a.name, to=[a.name])


# ---------- giving, trading, debts ----------

class GiveArgs(BaseModel):
    to: str
    items: ItemMap = Field(default_factory=dict)
    coins: int = Field(0, ge=0)


@ACTIONS.action("give", "Give items and/or coins to a person here. Nothing is asked in return.", GiveArgs)
def give(ctx: Ctx, a: Agent, args: GiveArgs) -> None:
    other = _agent_here(ctx, a, args.to)
    _items_known(ctx, args.items)
    if not args.items and not args.coins:
        raise ActionError("give what? items and coins are both empty")
    _need(a.inventory, args.items)
    if a.coins < args.coins:
        raise ActionError(f"you only have {a.coins} coins")
    ops.move_items(a.inventory, other.inventory, args.items)
    ops.move_coins(a, other, args.coins)
    what = fmt_items({**args.items, **({"coins": args.coins} if args.coins else {})})
    ctx.emit("give", f"{a.name} gave {what} to {other.name}.", actor=a.name, location=a.location,
             visibility="location", to=[other.name])


class LendArgs(BaseModel):
    to: str
    coins: int = Field(gt=0)
    repay_coins: int = Field(gt=0, description="how much they must pay back")
    due_day: int = Field(description="day by which it must be repaid")


@ACTIONS.action("lend", "Lend coins to a person here. The debt is written on the public board at the square.",
                LendArgs)
def lend(ctx: Ctx, a: Agent, args: LendArgs) -> None:
    other = _agent_here(ctx, a, args.to)
    if a.coins < args.coins:
        raise ActionError(f"you only have {a.coins} coins")
    if args.due_day <= ctx.world.day:
        raise ActionError("due_day must be in the future")
    ops.move_coins(a, other, args.coins)
    d = Debt(ctx.world.new_id("debt"), a.name, other.name, args.repay_coins, args.due_day, day=ctx.world.day)
    ctx.world.debts[d.id] = d
    ctx.emit("lend", f"{a.name} lent {args.coins} coins to {other.name}; {other.name} must repay "
             f"{args.repay_coins} by day {args.due_day} ({d.id}).", actor=a.name, location=a.location,
             visibility="location", to=[other.name], debt=d.id)


class RepayArgs(BaseModel):
    debt_id: str
    coins: int = Field(gt=0)


@ACTIONS.action("repay", "Pay back (part of) a debt. Can be done from anywhere.", RepayArgs,
                available=lambda c, a: any(d.borrower == a.name and d.status in ("open", "defaulted")
                                           for d in c.world.debts.values()))
def repay(ctx: Ctx, a: Agent, args: RepayArgs) -> None:
    d = ctx.world.debts.get(args.debt_id)
    if d is None or d.borrower != a.name:
        raise ActionError(f"you have no debt '{args.debt_id}'")
    if d.status not in ("open", "defaulted"):
        raise ActionError(f"that debt is already closed ({d.status})")
    pay = min(args.coins, d.coins_owed)
    if a.coins < pay:
        raise ActionError(f"you only have {a.coins} coins")
    lender = ctx.world.agents[d.lender]
    ops.move_coins(a, lender, pay)
    d.coins_owed -= pay
    if d.coins_owed == 0:
        d.status, d.claim = "repaid", None
    ctx.emit("repay", f"{a.name} repaid {pay} coins to {d.lender} ({d.id}, {d.coins_owed} left).",
             actor=a.name, visibility="public", debt=d.id)
    if d.status == "repaid":
        from . import debts
        debts.on_repaid(ctx, d)


class OfferArgs(BaseModel):
    to: str
    give: ItemMap = Field(default_factory=dict, description="items you give; use 'coins' for money")
    want: ItemMap = Field(default_factory=dict, description="items you want; use 'coins' for money")


def _check_bundle(ctx: Ctx, bundle: dict) -> None:
    _items_known(ctx, {k: v for k, v in bundle.items() if k != "coins"})


def _holds(a: Agent, bundle: dict) -> bool:
    return ops.has_all(a.inventory, {k: v for k, v in bundle.items() if k != "coins"}) \
        and a.coins >= bundle.get("coins", 0)


def _transfer_bundle(src: Agent, dst: Agent, bundle: dict) -> None:
    ops.move_items(src.inventory, dst.inventory, {k: v for k, v in bundle.items() if k != "coins"})
    ops.move_coins(src, dst, bundle.get("coins", 0))


@ACTIONS.action("offer", "Propose a trade to anyone. If they accept while you are both in one place, "
                "the swap happens automatically and fairly.", OfferArgs)
def offer(ctx: Ctx, a: Agent, args: OfferArgs) -> None:
    other = _agent(ctx, args.to)
    if other.name == a.name:
        raise ActionError("you cannot trade with yourself")
    if not args.give and not args.want:
        raise ActionError("an offer needs give or want")
    _check_bundle(ctx, args.give)
    _check_bundle(ctx, args.want)
    if not _holds(a, args.give):
        raise ActionError("you do not have what you offer")
    o = Offer(ctx.world.new_id("offer"), a.name, other.name, dict(args.give), dict(args.want),
              ctx.world.tick + clock.hours(ctx.cfg, ctx.cfg["offer_ttl_ticks"]))
    ctx.world.offers[o.id] = o
    ctx.emit("offer", f"{a.name} offers you {fmt_items(o.give)} for {fmt_items(o.want)} ({o.id}).",
             actor=a.name, to=[other.name], offer=o.id)
    ctx.emit("offer", f"You offered {other.name} {fmt_items(o.give)} for {fmt_items(o.want)} ({o.id}).",
             actor=a.name, to=[a.name], offer=o.id)


class OfferIdArgs(BaseModel):
    offer_id: str


def _my_offer(ctx: Ctx, a: Agent, offer_id: str) -> Offer:
    o = ctx.world.offers.get(offer_id)
    if o is None or o.to != a.name:
        raise ActionError(f"no open offer '{offer_id}' for you")
    return o


@ACTIONS.action("accept", "Accept a trade offer made to you. You must be in the same place.", OfferIdArgs,
                available=lambda c, a: any(o.to == a.name for o in c.world.offers.values()))
def accept(ctx: Ctx, a: Agent, args: OfferIdArgs) -> None:
    o = _my_offer(ctx, a, args.offer_id)
    sender = ctx.world.agents[o.sender]
    if sender.status != "active" or sender.location != a.location:
        raise ActionError(f"{sender.name} must be here to trade")
    if not _holds(sender, o.give):
        del ctx.world.offers[o.id]
        raise ActionError(f"{sender.name} no longer has {fmt_items(o.give)}; offer cancelled")
    if not _holds(a, o.want):
        raise ActionError(f"you do not have {fmt_items(o.want)}")
    _transfer_bundle(sender, a, o.give)
    _transfer_bundle(a, sender, o.want)
    del ctx.world.offers[o.id]
    ctx.emit("trade", f"{sender.name} and {a.name} traded: {fmt_items(o.give)} for {fmt_items(o.want)}.",
             actor=a.name, location=a.location, visibility="location", to=[sender.name], offer=o.id, partner=sender.name)


@ACTIONS.action("decline", "Decline a trade offer made to you.", OfferIdArgs,
                available=lambda c, a: any(o.to == a.name for o in c.world.offers.values()))
def decline(ctx: Ctx, a: Agent, args: OfferIdArgs) -> None:
    o = _my_offer(ctx, a, args.offer_id)
    del ctx.world.offers[o.id]
    ctx.emit("decline", f"{a.name} declined your offer {o.id}.", actor=a.name, to=[o.sender, a.name])


# ---------- NPC market ----------

class MarketArgs(BaseModel):
    item: str
    qty: int = Field(1, ge=1, le=100)


def _price(ctx: Ctx, item: str, side: str) -> int:
    info = ctx.cfg["items"].get(item)
    if info is None or not info.get("tradable", True):
        raise ActionError(f"the trader does not deal in {item}")
    ratio = ctx.cfg["npc_sell_ratio"] if side == "buy" else ctx.cfg["npc_buy_ratio"]
    return max(1, int(info["value"] * ratio * crises.price_factor(ctx.world, item, side)))


@ACTIONS.action("buy", "Buy from the trader at the market (expensive).", MarketArgs,
                available=lambda c, a: a.location == "market")
def buy(ctx: Ctx, a: Agent, args: MarketArgs) -> None:
    if a.location != "market":
        raise ActionError("the trader is at the market")
    cost = _price(ctx, args.item, "buy") * args.qty
    if a.coins < cost:
        raise ActionError(f"that costs {cost} coins, you have {a.coins}")
    ops.burn_coins(ctx.world, a, cost)
    ops.mint(ctx.world, a.inventory, args.item, args.qty)
    ctx.emit("buy", f"{a.name} bought {args.qty} {args.item} from the trader for {cost} coins.", actor=a.name,
             location=a.location, visibility="location")


@ACTIONS.action("sell", "Sell to the trader at the market (cheap). The only way new coins enter the village.",
                MarketArgs, available=lambda c, a: a.location == "market" and bool(a.inventory))
def sell(ctx: Ctx, a: Agent, args: MarketArgs) -> None:
    if a.location != "market":
        raise ActionError("the trader is at the market")
    price = _price(ctx, args.item, "sell")
    _need(a.inventory, {args.item: args.qty})
    ops.burn(ctx.world, a.inventory, args.item, args.qty)
    ops.mint_coins(ctx.world, a, price * args.qty)
    ctx.emit("sell", f"{a.name} sold {args.qty} {args.item} to the trader for {price * args.qty} coins.",
             actor=a.name, location=a.location, visibility="location")


# ---------- chests & alliances ----------

class ChestArgs(BaseModel):
    items: ItemMap = Field(default_factory=dict)
    coins: int = Field(0, ge=0)


def _chest_avail(c: Ctx, a: Agent) -> bool:
    return any(ch.location == a.location and _has_chest_access(c, a, ch) for ch in c.world.chests.values())


@ACTIONS.action("store", "Put items/coins into the chest here (yours or one shared with you).", ChestArgs,
                available=_chest_avail)
def store(ctx: Ctx, a: Agent, args: ChestArgs) -> None:
    chest = _chest_here(ctx, a)
    if not _has_chest_access(ctx, a, chest):
        raise ActionError("you have no access to this chest")
    _items_known(ctx, args.items)
    _need(a.inventory, args.items)
    if a.coins < args.coins:
        raise ActionError(f"you only have {a.coins} coins")
    ops.move_items(a.inventory, chest.items, args.items)
    ops.move_coins(a, chest, args.coins)
    ctx.emit("store", f"You put {fmt_items(args.items)} and {args.coins} coins into {chest.owner}'s chest.",
             actor=a.name, to=[a.name])


@ACTIONS.action("take", "Take items/coins from the chest here (yours or one shared with you).", ChestArgs,
                available=_chest_avail)
def take(ctx: Ctx, a: Agent, args: ChestArgs) -> None:
    chest = _chest_here(ctx, a)
    if not _has_chest_access(ctx, a, chest):
        raise ActionError("you have no access to this chest")
    _need(chest.items, args.items, who="the chest has too little: it lacks")
    if chest.coins < args.coins:
        raise ActionError(f"the chest has only {chest.coins} coins")
    ops.move_items(chest.items, a.inventory, args.items)
    ops.move_coins(chest, a, args.coins)
    ctx.emit("take", f"You took {fmt_items(args.items)} and {args.coins} coins from {chest.owner}'s chest.",
             actor=a.name, to=[a.name])
    if chest.owner != a.name:
        ctx.emit("take_shared", f"{a.name} took {fmt_items(args.items)} and {args.coins} coins from your chest.",
                 actor=a.name, to=[chest.owner])


class PersonArgs(BaseModel):
    person: str


@ACTIONS.action("share_chest", "Give someone access to your chest. They can take everything.",
                PersonArgs)
def share_chest(ctx: Ctx, a: Agent, args: PersonArgs) -> None:
    other = _agent(ctx, args.person)
    chest = _own_chest(ctx, a)
    if other.name == a.name or other.name in chest.shared_with:
        raise ActionError(f"{other.name} already has access")
    chest.shared_with.append(other.name)
    ctx.emit("share", f"{a.name} gave you access to their chest.", actor=a.name, to=[other.name, a.name])


@ACTIONS.action("unshare_chest", "Remove someone's access to your chest.", PersonArgs,
                available=lambda c, a: bool(_own_chest(c, a).shared_with))
def unshare_chest(ctx: Ctx, a: Agent, args: PersonArgs) -> None:
    other = _agent(ctx, args.person)
    chest = _own_chest(ctx, a)
    if other.name not in chest.shared_with:
        raise ActionError(f"{other.name} has no access")
    chest.shared_with.remove(other.name)
    ctx.emit("unshare", f"{a.name} removed your access to their chest.", actor=a.name, to=[other.name, a.name])


@ACTIONS.action("install_lock", "Put a lock on your chest (uses 1 lock). Thieves can no longer open it.",
                available=lambda c, a: a.location == a.home and ops.count(a.inventory, "lock") > 0)
def install_lock(ctx: Ctx, a: Agent, args) -> None:
    chest = _own_chest(ctx, a)
    if a.location != a.home:
        raise ActionError("you must be at home")
    if chest.locked:
        raise ActionError("your chest is already locked")
    _need(a.inventory, {"lock": 1})
    ops.burn(ctx.world, a.inventory, "lock", 1)
    chest.locked = True
    ctx.emit("lock", "You installed a lock on your chest.", actor=a.name, to=[a.name])


class StealArgs(BaseModel):
    target: str = Field(description="a person here, or 'chest' for the chest here")
    item: str = Field(description="item name or 'coins'")
    qty: int = Field(1, ge=1)


@ACTIONS.action("steal", "Try to steal from a person here or from the chest here. Others may see you.",
                StealArgs)
def steal(ctx: Ctx, a: Agent, args: StealArgs) -> None:
    cfg = ctx.cfg
    qty = min(args.qty, cfg["max_steal_qty"])
    if args.item != "coins":
        _items_known(ctx, {args.item: 1})
    if args.target.lower() == "chest":
        chest = _chest_here(ctx, a)
        if chest.owner == a.name:
            raise ActionError("that is your own chest")
        if chest.locked:
            raise ActionError("the chest is locked")
        victim_name, holder, src, success = chest.owner, chest, chest.items, True
    else:
        victim = _agent_here(ctx, a, args.target)
        victim_name, holder, src = victim.name, victim, victim.inventory
        success = victim.asleep or ctx.rng.random() < cfg["steal_awake_target_success"]
        if not victim.asleep:
            # An awake victim always notices the attempt.
            ctx.emit("steal_attempt", f"{a.name} tried to steal {args.item} from you!", actor=a.name,
                     to=[victim.name])
    stock = holder.coins if args.item == "coins" else ops.count(src, args.item)
    qty = min(qty, stock)
    witnesses = [o.name for o in ctx.world.agents.values()
                 if o.status == "active" and not o.asleep and o.location == a.location
                 and o.name not in (a.name, victim_name) and ctx.rng.random() < cfg["steal_notice_chance"]]
    for w in witnesses:
        ctx.emit("witness", f"You saw {a.name} steal {args.item} from {victim_name}!", actor=a.name, to=[w],
                 thief=a.name, victim=victim_name)
    if not success or qty == 0:
        ctx.emit("steal", f"Your theft from {victim_name} failed.", actor=a.name, to=[a.name],
                 victim=victim_name, success=False, witnesses=witnesses)
        return
    if args.item == "coins":
        ops.move_coins(holder, a, qty)
    else:
        ops.move_items(src, a.inventory, {args.item: qty})
    ctx.emit("steal", f"You stole {qty} {args.item} from {victim_name}.", actor=a.name, to=[a.name],
             victim=victim_name, success=True, qty=qty, item=args.item, witnesses=witnesses)
    # The victim learns about the loss, but not who did it (unless they were awake and present).
    ctx.emit("robbed", f"Someone stole {qty} {args.item} from you.", to=[victim_name], victim=victim_name)


class PickUpArgs(BaseModel):
    item: str
    qty: int = Field(1, ge=1)


@ACTIONS.action("pick_up", "Pick up something lying on the ground here.", PickUpArgs,
                available=lambda c, a: bool(c.world.locations[a.location].ground))
def pick_up(ctx: Ctx, a: Agent, args: PickUpArgs) -> None:
    ground = _here(ctx, a).ground
    _need(ground, {args.item: args.qty}, who="the ground has too little: it lacks")
    ops.move_items(ground, a.inventory, {args.item: args.qty})
    ctx.emit("pick_up", f"{a.name} picked up {args.qty} {args.item}.", actor=a.name, location=a.location,
             visibility="location")


# ---------- public works ----------

class ContributeArgs(BaseModel):
    project_id: str
    items: ItemMap


@ACTIONS.action("contribute", "Give items to a village project at the square. When done, everyone is rewarded.",
                ContributeArgs, available=lambda c, a: a.location == "square" and
                any(not p.done for p in c.world.projects.values()))
def contribute(ctx: Ctx, a: Agent, args: ContributeArgs) -> None:
    if a.location != "square":
        raise ActionError("projects are at the square")
    p = ctx.world.projects.get(args.project_id)
    if p is None or p.done:
        raise ActionError(f"no open project '{args.project_id}'")
    useful = {k: min(v, p.needs.get(k, 0) - p.contributed.get(k, 0)) for k, v in args.items.items()}
    useful = {k: v for k, v in useful.items() if v > 0}
    if not useful:
        raise ActionError(f"{p.name} does not need that; it needs {fmt_items(_remaining(p))}")
    _need(a.inventory, useful)
    for k, v in useful.items():
        ops.burn(ctx.world, a.inventory, k, v)
        p.contributed[k] = p.contributed.get(k, 0) + v
    p.contributors[a.name] = p.contributors.get(a.name, 0) + sum(useful.values())
    ctx.emit("contribute", f"{a.name} contributed {fmt_items(useful)} to {p.name}.", actor=a.name,
             visibility="public", project=p.id)
    if not _remaining(p):
        p.done = True
        reward = ctx.cfg["projects"][p.id]["reward_coins_each"]
        for other in ctx.world.agents.values():
            if other.status != "dead":
                ops.mint_coins(ctx.world, other, reward)
        ctx.emit("project_done", f"{p.name} is finished! Every villager receives {reward} coins.",
                 visibility="public", project=p.id)


def _remaining(p) -> dict:
    return {k: v - p.contributed.get(k, 0) for k, v in p.needs.items() if p.contributed.get(k, 0) < v}


class OrderArgs(BaseModel):
    order_id: str


@ACTIONS.action("fulfill_order", "Deliver everything an order on the board needs, at the square, and get "
                "the whole reward yourself.", OrderArgs,
                available=lambda c, a: a.location == "square" and any(o.status == "open"
                                                                      for o in c.world.orders.values()))
def fulfill_order(ctx: Ctx, a: Agent, args: OrderArgs) -> None:
    if a.location != "square":
        raise ActionError("orders are delivered at the square")
    o = ctx.world.orders.get(args.order_id)
    if o is None or o.status != "open":
        raise ActionError(f"no open order '{args.order_id}'")
    _need(a.inventory, o.needs)
    for k, v in o.needs.items():
        ops.burn(ctx.world, a.inventory, k, v)
    ops.mint_coins(ctx.world, a, o.reward)
    o.status, o.fulfilled_by = "fulfilled", a.name
    ctx.emit("order_done", f"{a.name} fulfilled order {o.id} and received {o.reward} coins.", actor=a.name,
             visibility="public", order=o.id)


@ACTIONS.action("extinguish", "Pour all the water you carry on a fire here (as much as it still needs).",
                available=lambda c, a: a.location in c.world.fires)
def extinguish(ctx: Ctx, a: Agent, args) -> None:
    fire = ctx.world.fires.get(a.location)
    if fire is None:
        raise ActionError("nothing is burning here")
    _need(a.inventory, {"water": 1})
    used = min(ops.count(a.inventory, "water"), fire.water_needed)
    ops.burn(ctx.world, a.inventory, "water", used)
    fire.water_needed -= used
    data = dict(helper=a.name, house=a.location, buckets=used, water_needed=fire.water_needed)
    if fire.water_needed <= 0:
        del ctx.world.fires[a.location]
        ctx.emit("fire_out", f"{a.name} poured {used} water and put out the fire at {_here(ctx, a).name}!",
                 actor=a.name, location=a.location, visibility="public", **data)
    else:
        ctx.emit("pour_water", f"{a.name} poured {used} water on the fire ({fire.water_needed} more needed, "
                 f"{fire.ticks_left} hours left).", actor=a.name, location=a.location, visibility="location", **data)


class PlantArgs(BaseModel):
    crop: str | None = Field(None, description="what to sow here; default: the first crop that can be sown here")


def _sowable(ctx: Ctx, loc) -> dict:
    spec = ctx.cfg["locations"].get(loc.id, {}).get("resources", {})
    return {r: s for r, s in spec.items() if "plant" in s}


@ACTIONS.action("plant", "Sow a seed in a free bed here (takes 1 hour). It ripens after some nights; then work here "
                "to harvest. Anyone can harvest a ripe bed. At home it sows your own garden_bed (only your family harvests it).",
                PlantArgs, available=lambda c, a: bool(_sowable(c, _here(c, a))) or plots.can_sow(c, a))
def plant(ctx: Ctx, a: Agent, args: PlantArgs) -> None:
    if plots.own_plot_here(ctx.world, a) is not None:
        return plots.sow(ctx, a, args.crop)
    loc = _here(ctx, a)
    sowable = _sowable(ctx, loc)
    if not sowable:
        raise ActionError("nothing can be planted here")
    crop = args.crop or next(iter(sowable))
    if crop not in sowable:
        raise ActionError(f"{crop} cannot be planted here; can plant: {', '.join(sowable)}")
    rule = sowable[crop]["plant"]
    if seasons.regen(ctx.cfg, ctx.world.day, crop, 1) == 0:
        raise ActionError(f"the ground is frozen: {crop} cannot be planted this season")
    free = tiles.free_beds(loc, crop)
    if not free:
        raise ActionError(f"no free bed: every bed here still has {crop} or is already sown")
    _need(a.inventory, {crop: rule["seed"]})
    ops.burn(ctx.world, a.inventory, crop, rule["seed"])
    slot = free[0]
    ripe = ctx.world.day + rule["days"]
    loc.planted[str(slot)] = {"resource": crop, "by": a.name, "ripe_day": ripe}
    ctx.emit("plant", f"{a.name} planted {crop} at the {loc.name} (ripe on day {ripe}).", actor=a.name,
             location=loc.id, visibility="location", resource=crop, slot=slot, ripe_day=ripe)
