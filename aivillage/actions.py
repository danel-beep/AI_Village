"""All agent actions. Each one validates fully before changing anything,
so a failed action never leaves the world half-changed."""

from __future__ import annotations

from collections import deque
from typing import Annotated

from pydantic import BaseModel, Field

from . import clock, crafting, crises, labor, ops, plots, pricing, seasons, theft, tiles, works
from .ops import Ctx, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, Debt, Letter, Offer, Order

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
    if (left := labor.hours_left(cfg, a)) is not None and left <= 0 and resource != "water":
        ctx.emit("work", "You are too tired to work any more today.", to=[a.name])
        return 0
    amount = cfg["work_base_yield"]
    if resource in cfg["professions"].get(a.profession, []):
        amount *= cfg["work_profession_multiplier"]
    amount += labor.bonus(cfg, a, resource)
    if crafting.enabled(cfg):  # many kinds of tools, each fits some resources and wears on its own
        if crafting.missing_tool(cfg, a, resource):
            ctx.emit("work", crafting.missing_tool(cfg, a, resource), to=[a.name])
            return 0
        tool, mult = crafting.tool_for(cfg, a, resource) if resource != "water" else (None, 1.0)
        amount, using_tool = crafting.scale(amount, mult), False
    else:
        tool, using_tool = None, resource != "water" and ops.count(a.inventory, "tool") > 0
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
    labor.after_work_hour(ctx, a, resource)
    crafting.wear(ctx, a, tool)
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
    hours: int = Field(1, ge=1, le=8, description="how many hours to keep working in a row with this one call "
                       "(default 1; at most 4, the rest of the day's work cap still applies)")
    resource: str | None = Field(None, description="what to gather here; default: the first resource here")


def _can_work(ctx: Ctx, a: Agent) -> bool:
    return bool(_here(ctx, a).resources)


@ACTIONS.action("work", "Gather a resource at this location for `hours` hours in a row (up to 4 per call). "
                "Your profession gives x3, a tool x2.",
                WorkArgs, available=_can_work)
def work(ctx: Ctx, a: Agent, args: WorkArgs) -> None:
    loc = _here(ctx, a)
    if not loc.resources:
        raise ActionError("nothing to gather here")
    res = args.resource
    if res is None:
        mine = [r for r in ctx.cfg["professions"].get(a.profession, []) if r in loc.resources]
        free = labor.free_goods(ctx.cfg, a, list(loc.resources))
        res = mine[0] if mine else (free[0] if free else next(iter(loc.resources)))
    if res not in loc.resources:
        raise ActionError(f"there is no {res} here; available: {', '.join(loc.resources)}")
    if crafting.enabled(ctx.cfg) and (why := crafting.missing_tool(ctx.cfg, a, res)):
        raise ActionError(why)
    if why := labor.may_gather(ctx.cfg, a, res):
        free = labor.free_goods(ctx.cfg, a, list(loc.resources))
        raise ActionError(why + (f"; here you can gather: {', '.join(free)}" if free else "; nothing here is yours to gather"))
    hours = min(args.hours, ctx.cfg["max_work_hours"])
    if res != "water" and (left := labor.hours_left(ctx.cfg, a)) is not None:
        if left <= 0:
            raise ActionError(f"you already worked {a.worked_today} hours today, the most anyone can; "
                              "you can work again tomorrow")
        hours = min(hours, left)
    work_hour(ctx, a, res)
    a.task = {"kind": "work", "resource": res, "hours_left": hours - 1} if hours > 1 else None


class CraftArgs(BaseModel):
    recipe: str
    times: int = Field(1, ge=1, le=10)


@ACTIONS.action("craft", "Make an item from a recipe (bread, fish_soup, club at home; tool, lock, spear at the smithy "
                "by a smith).",
                CraftArgs)
def craft(ctx: Ctx, a: Agent, args: CraftArgs) -> None:
    if crafting.enabled(ctx.cfg):
        return crafting.craft(ctx, a, args.recipe, args.times)
    r = ctx.cfg["recipes"].get(args.recipe)
    if r is None:
        raise ActionError(f"unknown recipe '{args.recipe}'; known: {', '.join(ctx.cfg['recipes'])}")
    if r["where"] == "home" and a.location != a.home:
        raise ActionError(f"{args.recipe} can only be made at your home")
    if r["where"] != "home" and a.location != r["where"]:
        raise ActionError(f"{args.recipe} can only be made at the {r['where']}")
    if r["profession"] and a.profession != r["profession"] and not labor.no_professions(ctx.cfg):
        raise ActionError(f"only a {r['profession']} can make {args.recipe}")
    need = {k: v * args.times for k, v in r["inputs"].items()}
    _need(a.inventory, need)
    for k, v in need.items():
        ops.burn(ctx.world, a.inventory, k, v)
    out = r["output"] * args.times
    ops.mint(ctx.world, a.inventory, args.recipe, out)
    ctx.emit("craft", f"{a.name} made {out} {args.recipe}.", actor=a.name, location=a.location,
             visibility="location", recipe=args.recipe)


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


@ACTIONS.action("sleep", "Go to sleep until morning (you skip the rest of the day). Health comes back at night if you spend "
                 "the night at home and are not too hungry, asleep or awake.")
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


@ACTIONS.action("give", "Give items and/or coins to a person here, or anywhere if World facts say gifts are "
                "carried. Nothing is asked in return.", GiveArgs)
def give(ctx: Ctx, a: Agent, args: GiveArgs) -> None:
    other = _agent(ctx, args.to)
    carried = labor.trade_anywhere(ctx.cfg) and other.location != a.location  # carried like a trade
    if not carried:
        other = _agent_here(ctx, a, args.to)
    elif other.name == a.name:
        raise ActionError("you cannot do that to yourself")
    elif other.status != "active":
        raise ActionError(f"{other.name} cannot receive anything now")
    _items_known(ctx, args.items)
    if not args.items and not args.coins:
        raise ActionError("give what? items and coins are both empty")
    _need(a.inventory, args.items)
    if a.coins < args.coins:
        raise ActionError(f"you only have {a.coins} coins")
    ops.move_items(a.inventory, other.inventory, args.items)
    ops.move_coins(a, other, args.coins)
    what = fmt_items({**args.items, **({"coins": args.coins} if args.coins else {})})
    ctx.emit("give", f"{a.name} gave {what} to {other.name}" + (" (carried)." if carried else "."), actor=a.name,
             location=a.location, visibility="location", to=[other.name], **({"carried": True} if carried else {}))
    if args.items:
        from . import debts  # debts imports this module
        debts.repay_in_kind(ctx, a, other, args.items)


class LendArgs(BaseModel):
    to: str
    coins: int = Field(gt=0)
    repay_coins: int = Field(gt=0, description="how much they must pay back")
    due_day: int = Field(description="day by which it must be repaid")


@ACTIONS.action("lend", "Offer a loan to a person here. If they accept, they get the coins and owe you repay_coins "
                "by due_day, written in the private debt book.", LendArgs)
def lend(ctx: Ctx, a: Agent, args: LendArgs) -> None:
    """Only an offer: the debt starts when the borrower accepts it (audit B-6: a lender could write any debt,
    a billion for 1 coin, on someone who never agreed)."""
    other = _agent_here(ctx, a, args.to)
    if a.coins < args.coins:
        raise ActionError(f"you only have {a.coins} coins")
    if args.due_day <= ctx.world.day:
        raise ActionError("due_day must be in the future")
    from . import debts  # debts imports this module
    cap = debts._cfg(ctx.cfg).get("max_promise", 500)
    if args.repay_coins > cap:
        raise ActionError(f"at most {cap} coins to repay per loan")
    o = Offer(ctx.world.new_id("offer"), a.name, other.name, {"coins": args.coins}, {},
              ctx.world.tick + clock.hours(ctx.cfg, ctx.cfg["offer_ttl_ticks"]),
              due_day=args.due_day, you_owe={"coins": args.repay_coins})
    ctx.world.offers[o.id] = o
    ctx.emit("offer", f"{a.name} {_offer_text(o)} ({o.id}).", actor=a.name, to=[other.name], offer=o.id)
    ctx.emit("offer", f"You {_offer_text(o, own=True)} ({o.id}).", actor=a.name, to=[a.name], offer=o.id)


def _loan_made(ctx: Ctx, o: Offer, lender: Agent, borrower: Agent) -> None:
    """`accept` of a loan offer: the coins move and the debt is written."""
    ops.move_coins(lender, borrower, o.give["coins"])
    repay = o.you_owe["coins"]
    d = Debt(ctx.world.new_id("debt"), lender.name, borrower.name, repay, o.due_day, day=ctx.world.day)
    ctx.world.debts[d.id] = d
    ctx.emit("lend", f"{lender.name} lent {o.give['coins']} coins to {borrower.name}; {borrower.name} must repay "
             f"{repay} by day {o.due_day} ({d.id}).", actor=lender.name, location=borrower.location,
             visibility="location", to=[lender.name, borrower.name], debt=d.id, offer=o.id)


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
    if d.lender not in ctx.world.agents:  # a tax or fine bill owed to the treasury (debts.pay_bill)
        from . import debts
        return debts.settle_bill(ctx, a, d, args.coins)
    if d.coins_owed <= 0:
        raise ActionError(f"{d.id} is owed in items ({fmt_items(d.items_owed)}): give them to {d.lender}")
    pay = min(args.coins, d.coins_owed)
    if a.coins < pay:
        raise ActionError(f"you only have {a.coins} coins")
    lender = ctx.world.agents[d.lender]
    ops.move_coins(a, lender, pay)
    d.coins_owed -= pay
    if d.coins_owed == 0 and not d.items_owed:
        d.status, d.claim = "repaid", None
    ctx.emit("repay", f"{a.name} repaid {pay} coins to {d.lender} ({d.id}, {d.coins_owed} left).",
             actor=a.name, to=[d.lender, a.name], debt=d.id)
    if d.status == "repaid":
        from . import debts
        debts.on_repaid(ctx, d)


class OfferArgs(BaseModel):
    to: str
    give: ItemMap = Field(default_factory=dict, description="items you give; use 'coins' for money")
    want: ItemMap = Field(default_factory=dict, description="items you want; use 'coins' for money")
    i_owe: ItemMap = Field(default_factory=dict, description="optional: what you will owe them later, if World "
                           "facts allow it; use 'coins' for money")
    due_day: int | None = Field(None, description="with i_owe: day by which you will give it")


def offer_view(o: Offer) -> dict:
    """An offer as agents see it (the i_owe / you_owe part only when there is one)."""
    v = dict(vars(o))
    if not o.you_owe:
        del v["you_owe"]
        if not o.i_owe:
            del v["due_day"]
    if not o.i_owe:
        del v["i_owe"]
    return v


def _offer_text(o: Offer, own: bool = False) -> str:
    """The offer in words, for its receiver ("offers you ...") or its sender (own: "offered Anna ...")."""
    if o.you_owe:
        lent, repay = o.give["coins"], o.you_owe["coins"]
        if own:
            return f"offered {o.to} a loan of {lent} coins, {repay} to repay by day {o.due_day}"
        return (f"offers you a loan of {lent} coins: you would owe {repay} coins by day {o.due_day} "
                f"(accept or decline)")
    if not o.i_owe:
        return f"{'offered ' + o.to if own else 'offers you'} {fmt_items(o.give)} for {fmt_items(o.want)}"
    if own:
        head = f"offered {o.to} {fmt_items(o.give)}" if o.give else f"asked {o.to} for"
        owe = f"you will owe {o.to} {fmt_items(o.i_owe)} by day {o.due_day}"
    else:
        head = f"offers you {fmt_items(o.give)}" if o.give else "asks you for"
        owe = f"owes you {fmt_items(o.i_owe)} by day {o.due_day}"
    if not o.give:
        return f"{head} {fmt_items(o.want)}; in return {owe}"
    return f"{head} now for {fmt_items(o.want)}, and {owe}"


def _check_bundle(ctx: Ctx, bundle: dict) -> None:
    _items_known(ctx, {k: v for k, v in bundle.items() if k != "coins"})


def _holds(a: Agent, bundle: dict) -> bool:
    return ops.has_all(a.inventory, {k: v for k, v in bundle.items() if k != "coins"}) \
        and a.coins >= bundle.get("coins", 0)


def _transfer_bundle(src: Agent, dst: Agent, bundle: dict) -> None:
    ops.move_items(src.inventory, dst.inventory, {k: v for k, v in bundle.items() if k != "coins"})
    ops.move_coins(src, dst, bundle.get("coins", 0))


@ACTIONS.action("offer", "Propose a trade to anyone. If they accept (see accept), the swap happens automatically "
                "and fairly.", OfferArgs)
def offer(ctx: Ctx, a: Agent, args: OfferArgs) -> None:
    other = _agent(ctx, args.to)
    if other.name == a.name:
        raise ActionError("you cannot trade with yourself")
    if not args.give and not args.want:
        raise ActionError("an offer needs give or want")
    _check_bundle(ctx, args.give)
    _check_bundle(ctx, args.want)
    i_owe = {k: v for k, v in args.i_owe.items() if v}
    if i_owe or args.due_day is not None:
        from . import debts  # debts imports this module
        if not debts.in_kind(ctx.cfg):
            raise ActionError("offers here cannot carry i_owe; use promise to owe coins")
        if not i_owe:
            raise ActionError("due_day goes with i_owe: what you will owe them")
        if args.due_day is None or args.due_day <= ctx.world.day:
            raise ActionError(f"i_owe needs a due_day after today (day {ctx.world.day})")
        if not args.want:
            raise ActionError("i_owe is paid for something: say what you want now in want (or use promise)")
        _check_bundle(ctx, i_owe)
        if i_owe.get("coins", 0) > debts._cfg(ctx.cfg).get("max_promise", 500):
            raise ActionError(f"at most {debts._cfg(ctx.cfg).get('max_promise', 500)} coins per IOU")
    if not _holds(a, args.give):
        raise ActionError("you do not have what you offer")
    o = Offer(ctx.world.new_id("offer"), a.name, other.name, dict(args.give), dict(args.want),
              ctx.world.tick + clock.hours(ctx.cfg, ctx.cfg["offer_ttl_ticks"]),
              i_owe=i_owe, due_day=args.due_day if i_owe else 0)
    ctx.world.offers[o.id] = o
    ctx.emit("offer", f"{a.name} {_offer_text(o)} ({o.id}).", actor=a.name, to=[other.name], offer=o.id)
    ctx.emit("offer", f"You {_offer_text(o, own=True)} ({o.id}).", actor=a.name, to=[a.name], offer=o.id)


class OfferIdArgs(BaseModel):
    offer_id: str


def _my_offer(ctx: Ctx, a: Agent, offer_id: str) -> Offer:
    o = ctx.world.offers.get(offer_id)
    if o is None or o.to != a.name:
        raise ActionError(f"no open offer '{offer_id}' for you")
    return o


@ACTIONS.action("accept", "Accept a trade offer made to you. You must be in the same place, unless World facts say "
                "trades are carried.", OfferIdArgs,
                available=lambda c, a: any(o.to == a.name for o in c.world.offers.values()))
def accept(ctx: Ctx, a: Agent, args: OfferIdArgs) -> None:
    o = _my_offer(ctx, a, args.offer_id)
    sender = ctx.world.agents[o.sender]
    if sender.status != "active" or (sender.location != a.location and not labor.trade_anywhere(ctx.cfg)):
        raise ActionError(f"{sender.name} must be here to trade")
    if not _holds(sender, o.give):
        del ctx.world.offers[o.id]
        raise ActionError(f"{sender.name} no longer has {fmt_items(o.give)}; offer cancelled")
    if not _holds(a, o.want):
        raise ActionError(f"you do not have {fmt_items(o.want)}")
    if (o.i_owe or o.you_owe) and o.due_day <= ctx.world.day:
        del ctx.world.offers[o.id]
        raise ActionError(f"the repayment day in {o.id} (day {o.due_day}) has come; offer cancelled")
    if o.you_owe:
        del ctx.world.offers[o.id]
        return _loan_made(ctx, o, sender, a)
    _transfer_bundle(sender, a, o.give)
    _transfer_bundle(a, sender, o.want)
    from . import places  # places imports the action registry
    places.note_supply(ctx.world, a, o.give)
    places.note_supply(ctx.world, sender, o.want)
    del ctx.world.offers[o.id]
    ctx.emit("trade", f"{sender.name} and {a.name} traded: {fmt_items(o.give)} for {fmt_items(o.want)}.",
             actor=a.name, location=a.location, visibility="location", to=[sender.name], offer=o.id, partner=sender.name)
    if o.i_owe:
        from . import debts  # debts imports this module
        d = debts.write(ctx, a.name, sender.name, o.i_owe.get("coins", 0), o.due_day, kind="iou",
                        note=f"for {fmt_items(o.want)}", items={k: v for k, v in o.i_owe.items() if k != "coins"})
        ctx.emit("iou", f"{sender.name} now owes {a.name} {debts.owed(d)} by day {d.due_day} for "
                 f"{fmt_items(o.want)} ({d.id}, written in the private debt book).", actor=sender.name,
                 to=debts.sides(d), debt=d.id, lender=a.name, borrower=sender.name)


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


def _price(ctx: Ctx, item: str, side: str, qty: int) -> int:
    """Coins for a lot (pricing.total: the stock-driven price slides unit by unit within the lot)."""
    info = ctx.cfg["items"].get(item)
    if info is None or not info.get("tradable", True):
        raise ActionError(f"the trader does not deal in {item}")
    return pricing.total(ctx.world, item, side, qty)


@ACTIONS.action("buy", "Buy from the trader at the market (expensive).", MarketArgs,
                available=lambda c, a: a.location == "market")
def buy(ctx: Ctx, a: Agent, args: MarketArgs) -> None:
    if a.location != "market":
        raise ActionError("the trader is at the market")
    cost = _price(ctx, args.item, "buy", args.qty)
    if a.coins < cost:
        raise ActionError(f"that costs {cost} coins, you have {a.coins}")
    labor.trader_deal(ctx.world, args.item, args.qty, "sell")
    pricing.trader_sold(ctx.world, args.item, args.qty)
    ops.burn_coins(ctx.world, a, cost)
    ops.mint(ctx.world, a.inventory, args.item, args.qty)
    from . import places
    places.note_supply(ctx.world, a, {args.item: args.qty})
    ctx.emit("buy", f"{a.name} bought {args.qty} {args.item} from the trader for {cost} coins.", actor=a.name,
             location=a.location, visibility="location")


@ACTIONS.action("sell", "Sell to the trader at the market (cheap). The only way new coins enter the village.",
                MarketArgs, available=lambda c, a: a.location == "market" and bool(a.inventory))
def sell(ctx: Ctx, a: Agent, args: MarketArgs) -> None:
    if a.location != "market":
        raise ActionError("the trader is at the market")
    _need(a.inventory, {args.item: args.qty})
    coins = _price(ctx, args.item, "sell", args.qty)
    labor.trader_deal(ctx.world, args.item, args.qty, "buy", coins)
    pricing.trader_bought(ctx.world, args.item, args.qty)
    ops.burn(ctx.world, a.inventory, args.item, args.qty)
    ops.mint_coins(ctx.world, a, coins)
    from . import taxes  # taxes imports actions
    taxes.record_income(ctx.world, a, coins)
    ctx.emit("sell", f"{a.name} sold {args.qty} {args.item} to the trader for {coins} coins.",
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
    target: str = Field(description="a person here, or 'chest' for the chest here (or 'treasury' where one is kept)")
    item: str = Field(description="item name or 'coins'")
    qty: int = Field(1, ge=1)


@ACTIONS.action("steal", "Try to steal from a person here or from the chest here. Others may see you.",
                StealArgs)
def steal(ctx: Ctx, a: Agent, args: StealArgs) -> None:
    cfg, w = ctx.cfg, ctx.world
    qty = min(args.qty, cfg["max_steal_qty"])
    if args.item != "coins":
        _items_known(ctx, {args.item: 1})
    seen_by: list[str] = []  # the victim who saw who did it (theft.py: owner at home, awake victim)
    books = None
    if args.target.lower() == "treasury":
        found = theft.treasury_here(w, a)
        if found is None:
            raise ActionError("there is no treasury here to steal from")
        if args.item != "coins":
            raise ActionError("a treasury holds only coins")
        holder, books, victim_name = found
        src, success = None, True
        books_key = theft.treasury_key(w, a)
    elif args.target.lower() == "chest":
        chest = _chest_here(ctx, a)
        if chest.owner == a.name:
            raise ActionError("that is your own chest")
        if chest.locked:
            raise ActionError("the chest is locked")
        victim_name, holder, src, success = chest.owner, chest, chest.items, True
        owner = w.agents.get(chest.owner)
        if theft.enabled(cfg) and owner and owner.status == "active" and not owner.asleep \
                and owner.location == a.location and ctx.rng.random() < theft.owner_chance(w):
            seen_by = [owner.name]
    else:
        victim = _agent_here(ctx, a, args.target)
        victim_name, holder, src = victim.name, victim, victim.inventory
        success = victim.asleep or ctx.rng.random() < cfg["steal_awake_target_success"]
        # An awake victim notices the attempt (always, unless theft.victim_notice_chance says otherwise).
        if not victim.asleep and (not theft.enabled(cfg) or ctx.rng.random() < theft.victim_chance(w)):
            seen_by = [victim.name]
    for v in seen_by:
        ctx.emit("steal_attempt", f"{a.name} tried to steal {args.item} from you!", actor=a.name, to=[v])
    stock = holder.coins if args.item == "coins" else ops.count(src, args.item)
    qty = min(qty, stock)
    witnesses = [o.name for o in w.agents.values()
                 if o.status == "active" and not o.asleep and o.location == a.location
                 and o.name not in (a.name, victim_name)
                 and ctx.rng.random() < theft.notice(w, cfg["steal_notice_chance"] + works.notice_bonus(w))]
    for x in witnesses:
        ctx.emit("witness", f"You saw {a.name} steal {args.item} from {victim_name}!", actor=a.name, to=[x],
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
             victim=victim_name, success=True, qty=qty, item=args.item, witnesses=witnesses,
             **({"seen_by": seen_by} if seen_by else {}), **({"treasury": books_key} if books is not None else {}))
    if books is not None:  # nobody is told; the books still show the coins until an audit
        theft.take_from_treasury(w, books, qty)
        return
    # The victim learns about the loss, but not who did it (unless they were awake and present).
    ctx.emit("robbed", f"Someone stole {qty} {args.item} from you.", to=[victim_name], victim=victim_name)
    if not seen_by and not witnesses:
        theft.clue(ctx, a, victim_name, args.item, qty)


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


@ACTIONS.action("contribute", "Give items or coins ('coins') to a village project at the square.",
                ContributeArgs, available=lambda c, a: a.location == "square" and
                any(not p.done for p in c.world.projects.values()))
def contribute(ctx: Ctx, a: Agent, args: ContributeArgs) -> None:
    if a.location != "square":
        raise ActionError("projects are at the square")
    p = ctx.world.projects.get(args.project_id)
    if p is None or p.done:
        raise ActionError(f"no open project '{args.project_id}'")
    useful = works.contribute(ctx, a, p, args.items)
    ctx.emit("contribute", f"{a.name} contributed {fmt_items(useful)} to {p.name}.", actor=a.name,
             visibility="public", project=p.id)
    works.maybe_finish(ctx, p)


class OrderArgs(BaseModel):
    order_id: str


def _remote_orders(cfg: dict) -> bool:
    """market.remote: a villager's own order (post_order) is delivered from anywhere; council orders at the square."""
    return bool(cfg.get("market", {}).get("enabled") and cfg["market"].get("remote"))


@ACTIONS.action("fulfill_order", "Deliver everything an order on the board needs and get the whole reward "
                "yourself: at the square, or from anywhere for a villager's order if World facts say so.", OrderArgs,
                available=lambda c, a: any(o.status == "open" and o.by != a.name and
                                           (a.location == "square" or (o.by and _remote_orders(c.cfg)))
                                           for o in c.world.orders.values()))
def fulfill_order(ctx: Ctx, a: Agent, args: OrderArgs) -> None:
    o = ctx.world.orders.get(args.order_id)
    if a.location != "square" and not (o is not None and o.by and _remote_orders(ctx.cfg)):
        raise ActionError("orders are delivered at the square")
    if o is None or o.status != "open":
        raise ActionError(f"no open order '{args.order_id}'")
    if o.by == a.name:
        raise ActionError("that is your own order")
    from . import taxes  # taxes imports actions
    if taxes.partial(o, ctx.cfg):
        return taxes.deliver(ctx, a, o)
    _need(a.inventory, o.needs)
    buyer = ctx.world.agents.get(o.by)
    for k, v in o.needs.items():
        if buyer is not None:  # a villager's order: the goods are carried to them wherever they are
            ops.move_items(a.inventory, buyer.inventory, {k: v})
        else:
            ops.burn(ctx.world, a.inventory, k, v)
    ops.mint_coins(ctx.world, a, o.reward)
    if buyer is None:
        taxes.record_income(ctx.world, a, o.reward)
    o.status, o.fulfilled_by = "fulfilled", a.name
    ctx.emit("order_done", f"{a.name} fulfilled order {o.id}{' for ' + o.by if o.by else ''} and received "
             f"{o.reward} coins.", actor=a.name, visibility="public", order=o.id, buyer=o.by)
    if buyer is not None:
        ctx.emit("order_delivered", f"{a.name} delivered your order {o.id}: you received {fmt_items(o.needs)}.",
                 actor=a.name, to=[buyer.name], order=o.id)


class PostOrderArgs(BaseModel):
    needs: ItemMap = Field(description="items you want delivered")
    reward: int = Field(gt=0, le=1000, description="coins you pay to whoever delivers them")
    days: int = Field(2, ge=1, le=7, description="how many days the order stays on the board")


@ACTIONS.action("post_order", "Put your own order on the board at the square, from anywhere: the coins are held by "
                "the board, the first villager to deliver the items at the square gets them, and the items are "
                "carried to you. Unclaimed coins come back when it expires.", PostOrderArgs)
def post_order(ctx: Ctx, a: Agent, args: PostOrderArgs) -> None:
    _items_known(ctx, args.needs)
    if "coins" in args.needs:
        raise ActionError("an order asks for items, not coins")
    if a.coins < args.reward:
        raise ActionError(f"you have {a.coins} coins, the reward is {args.reward}")
    mine = [o for o in ctx.world.orders.values() if o.by == a.name and o.status == "open"]
    if len(mine) >= ctx.cfg.get("max_own_orders", 3):
        raise ActionError(f"you already have {len(mine)} open orders on the board")
    ops.burn_coins(ctx.world, a, args.reward)  # held by the board: comes back as new coins on delivery / expiry
    o = Order(ctx.world.new_id("order"), dict(args.needs), args.reward, ctx.world.day + args.days - 1, by=a.name)
    ctx.world.orders[o.id] = o
    ctx.emit("order", f"{a.name} put an order on the board ({o.id}): {fmt_items(o.needs)} for {o.reward} coins, "
             f"until day {o.expires_day}.", actor=a.name, visibility="public", order=o.id, buyer=a.name)


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
