"""The village debt book: loans, IOUs, pledges, and collecting overdue debts through the mayor.

Every debt lives in `world.debts` (state.Debt) and is shown to everyone on the board (`board.debts`).
Ways a debt is born:
- `lend` (actions.py): the lender hands over coins now, the borrower owes `repay_coins` by `due_day`.
- `promise` (here): anyone writes an IOU on themselves: "I owe <to> N coins by day D (for ...)".
  Nothing changes hands, so it backs deals on credit, bribes, bets or plain promises. An optional
  pledge (items from the writer's pocket) is held by the book.
- other modules (tavern dice, ...) call `write()`.

What happens to it:
- `repay` (actions.py) pays it off, from anywhere; a full repayment returns the pledge.
- the night after `due_day`: a debt with a pledge is closed and the pledge goes to the lender
  (`forfeited`); a debt without one becomes `defaulted` (public) and keeps growing by
  `debts.late_fee_pct` of what is left each night (0 = no fee).
- `forgive_debt`: the lender cancels it (pledge back to the borrower).
- `transfer_debt`: the lender hands the right to be paid to someone else (sell it with offer/give).
- automatic collection (`debts.auto_collect`): every night a defaulted debt without a pledge takes
  coins from the debtor (pocket, then chest), then goods at the trader's buying price, each capped at
  `seize_pct` of what the debtor has; food is never taken. While it stays unpaid, `seize_pct` of any
  coins the debtor receives during the day go straight to the lender (`collect_income`). Debts are
  served oldest due day first. Events `debt_seized` / `debt_garnished` go to both sides only.
- `demand_debt`: the lender of a defaulted debt asks the mayor to collect it. The mayor sees the claim
  in `debt_claims` and `rule_debt`s: `collect` takes what is owed from the debtor's pocket, then home
  chest (coins only; goods stay), `collect_fee_pct` of it goes to the treasury; `reject` drops the
  claim. The mayor can be lender, debtor or bribed: the engine checks none of that.

Statuses: open | defaulted (still owed) | repaid | forgiven | forfeited (closed).
Config block `debts`; `collection: false` (or no government) means nobody forces repayment.
"""

from __future__ import annotations

from collections import Counter
from math import ceil

from pydantic import BaseModel, Field

from . import governance, ops
from .actions import ItemMap, _agent, _items_known, _need, _text
from .ops import Ctx, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, Debt, World

OWED = ("open", "defaulted")
# Lender of the tax and fine bills written when laws are voluntary (governance.voluntary): the treasury is not
# a villager, so these bills are only paid with pay_bill and never collected (no late fee, no seizing).
TREASURY = "treasury"
BILL_KINDS = ("tax", "fine")
# fn(world, debt) -> treasury holder or None: a bill owed to another treasury than the village's (polity.py)
BILL_PAYEES: list = []


def _cfg(cfg: dict) -> dict:
    return cfg.get("debts", {})


def collection_on(cfg: dict) -> bool:
    return (bool(_cfg(cfg).get("collection", True)) and governance.enabled(cfg)
            and "demand_debt" not in cfg.get("disabled_actions", []))


def auto_on(cfg: dict) -> bool:
    return bool(_cfg(cfg).get("auto_collect", False))


def holdings(world: World) -> Counter:
    """Pledges held by the book (counted by invariants)."""
    total: Counter = Counter()
    for d in world.debts.values():
        total.update(d.pledge)
    return total


# ---------- API for other modules ----------

def write(ctx: Ctx, lender: str, borrower: str, coins: int, due_day: int, *, kind: str = "loan",
          note: str = "", pledge: dict | None = None) -> Debt:
    """Write a debt into the book (no coins move). Pledge items must already be taken from the
    borrower by the caller (they are now held by the book)."""
    d = Debt(ctx.world.new_id("debt"), lender, borrower, coins, due_day, kind=kind, note=note,
             pledge=dict(pledge or {}), day=ctx.world.day)
    ctx.world.debts[d.id] = d
    return d


def is_bill(d: Debt) -> bool:
    return d.lender == TREASURY


def write_bill(ctx: Ctx, borrower: str, coins: int, kind: str, note: str = "") -> Debt:
    """A tax or fine bill owed to the treasury, due in `laws.bill_days` days (voluntary laws)."""
    days = int((ctx.cfg.get("laws") or {}).get("bill_days", 3))
    return write(ctx, TREASURY, borrower, coins, ctx.world.day + max(1, days) - 1, kind=kind, note=note)


def board(world: World) -> list[dict]:
    """Debts still owed, compact (empty fields left out)."""
    out = []
    for d in world.debts.values():
        if d.status not in OWED:
            continue
        row = {"id": d.id, "lender": d.lender, "borrower": d.borrower, "coins_owed": d.coins_owed,
               "due_day": d.due_day, "status": d.status}
        if d.kind != "loan":
            row["kind"] = d.kind
        if d.note:
            row["note"] = d.note
        if d.pledge:
            row["pledge"] = dict(d.pledge)
        if d.claim:
            row["claimed"] = True
        out.append(row)
    return out


def observe(world: World, name: str) -> dict:
    """The mayor sees open claims to rule on."""
    if not collection_on(world.config) or world.governance.mayor != name:
        return {}
    claims = [{"debt_id": d.id, "lender": d.lender, "borrower": d.borrower, "coins_owed": d.coins_owed,
               "debtor_coins": world.agents[d.borrower].coins + _chest_coins(world, d.borrower)}
              for d in world.debts.values() if d.claim and d.status in OWED]
    return {"debt_claims": claims} if claims else {}


def fact(cfg: dict) -> str:
    c = _cfg(cfg)
    s = ("- Debts and IOUs are written in the village book (board.debts); repay works from anywhere. "
         "A pledge is held by the book: it goes back when the debt is paid in full, to the lender if it is "
         "not paid by the due day.")
    if c.get("late_fee_pct"):
        s += f" An overdue debt without a pledge grows by {c['late_fee_pct']}% each night."
    if auto_on(cfg):
        pct = c.get("seize_pct", 50)
        s += (f" Every night after the due day, an unpaid debt without a pledge"
              + (" (tax and fine bills excepted)" if governance.voluntary(cfg) else "") + f" is collected by the village: up to "
              f"{pct}% of the debtor's coins (pocket, then chest), then goods up to {pct}% of their value at "
              f"the trader's price; food is never taken. Until it is paid, {pct}% of any coins the debtor "
              f"receives go to the lender.")
    if collection_on(cfg):
        s += (f" The lender of an overdue debt can demand_debt: the mayor decides whether to collect it from the "
              f"debtor's coins (pocket, then chest; {c.get('collect_fee_pct', 0)}% goes to the treasury).")
    elif not auto_on(cfg):
        s += " Nobody forces repayment."
    return s


# ---------- helpers ----------

def _chest_coins(world: World, name: str) -> int:
    c = world.chests.get(f"chest_{name}")
    return c.coins if c else 0


def _debt(ctx: Ctx, debt_id: str) -> Debt:
    d = ctx.world.debts.get(debt_id.strip())
    if d is None:
        raise ActionError(f"there is no debt '{debt_id}' in the book")
    if d.status not in OWED:
        raise ActionError(f"debt {d.id} is already closed ({d.status})")
    return d


def _own(ctx: Ctx, a: Agent, debt_id: str) -> Debt:
    d = _debt(ctx, debt_id)
    if d.lender != a.name:
        raise ActionError(f"you are not the lender of {d.id} ({d.lender} is)")
    return d


def _return_pledge(ctx: Ctx, d: Debt, to: str) -> str:
    if not d.pledge:
        return ""
    what = fmt_items(d.pledge)
    ops.move_items(d.pledge, ctx.world.agents[to].inventory, dict(d.pledge))
    return what


def on_repaid(ctx: Ctx, d: Debt) -> None:
    """Called by `repay` when a debt is paid in full."""
    if what := _return_pledge(ctx, d, d.borrower):
        ctx.emit("pledge_returned", f"Your pledge ({what}) came back: {d.id} is paid.", to=[d.borrower])


def _owes(world: World, name: str) -> bool:
    return any(d.borrower == name and d.status in OWED for d in world.debts.values())


def _lends(world: World, name: str, status: tuple = OWED) -> bool:
    return any(d.lender == name and d.status in status for d in world.debts.values())


# ---------- actions ----------

class PromiseArgs(BaseModel):
    to: str = Field(description="who you will owe")
    coins: int = Field(gt=0, description="how much you promise to pay")
    due_day: int = Field(description="day by which you will pay")
    note: str = Field("", description="what it is for, written in the book")
    pledge: ItemMap = Field(default_factory=dict, description="items from your pocket held by the book until paid")


@ACTIONS.action("promise", "Write an IOU on yourself in the village book: you owe a person coins by a day. "
                "Nothing is paid now. An optional pledge is held by the book.", PromiseArgs)
def promise(ctx: Ctx, a: Agent, args: PromiseArgs) -> None:
    other = _agent(ctx, args.to)
    if other.name == a.name:
        raise ActionError("you cannot owe yourself")
    if other.status == "dead":
        raise ActionError(f"{other.name} is dead")
    if args.due_day <= ctx.world.day:
        raise ActionError("due_day must be in the future")
    if args.coins > _cfg(ctx.cfg).get("max_promise", 500):
        raise ActionError(f"at most {_cfg(ctx.cfg).get('max_promise', 500)} coins per IOU")
    _items_known(ctx, args.pledge)
    if "coins" in args.pledge:
        raise ActionError("a pledge is made of items, not coins")
    _need(a.inventory, args.pledge)
    note = _text(ctx, args.note) if args.note.strip() else ""
    pledge: dict = {}
    ops.move_items(a.inventory, pledge, args.pledge)
    d = write(ctx, other.name, a.name, args.coins, args.due_day, kind="iou", note=note, pledge=pledge)
    extra = (f" for \"{note}\"" if note else "") + (f", pledge: {fmt_items(pledge)}" if pledge else "")
    ctx.emit("promise", f"{a.name} wrote an IOU: owes {other.name} {args.coins} coins by day {args.due_day}"
             f"{extra} ({d.id}).", actor=a.name, visibility="public", debt=d.id, lender=other.name,
             coins=args.coins, due_day=args.due_day)


class DebtArgs(BaseModel):
    debt_id: str


@ACTIONS.action("forgive_debt", "Cancel a debt someone owes you. Any pledge goes back to them.", DebtArgs,
                available=lambda c, a: _lends(c.world, a.name))
def forgive_debt(ctx: Ctx, a: Agent, args: DebtArgs) -> None:
    d = _own(ctx, a, args.debt_id)
    d.status, d.claim = "forgiven", None
    what = _return_pledge(ctx, d, d.borrower)
    ctx.emit("debt_forgiven", f"{a.name} forgave {d.borrower} a debt of {d.coins_owed} coins ({d.id})"
             + (f"; the pledge ({what}) went back." if what else "."), actor=a.name, visibility="public",
             debt=d.id)


class TransferArgs(BaseModel):
    debt_id: str
    to: str = Field(description="who will be paid from now on")


@ACTIONS.action("transfer_debt", "Hand over a debt owed to you: from now on the debtor owes the new person. "
                "Sell it with offer or give if you want something for it.", TransferArgs,
                available=lambda c, a: _lends(c.world, a.name))
def transfer_debt(ctx: Ctx, a: Agent, args: TransferArgs) -> None:
    d = _own(ctx, a, args.debt_id)
    other = _agent(ctx, args.to)
    if other.name == a.name or other.status == "dead":
        raise ActionError(f"cannot hand it to {other.name}")
    if other.name == d.borrower:
        raise ActionError("to cancel it, use forgive_debt")
    d.lender, d.claim = other.name, None
    ctx.emit("debt_transferred", f"{a.name} handed {d.id} to {other.name}: {d.borrower} now owes "
             f"{other.name} {d.coins_owed} coins.", actor=a.name, visibility="public", debt=d.id)


@ACTIONS.action("demand_debt", "Ask the mayor to collect an overdue debt owed to you.", DebtArgs,
                available=lambda c, a: collection_on(c.cfg) and _lends(c.world, a.name, ("defaulted",)))
def demand_debt(ctx: Ctx, a: Agent, args: DebtArgs) -> None:
    if not collection_on(ctx.cfg):
        raise ActionError("nobody here collects debts")
    d = _own(ctx, a, args.debt_id)
    if d.status != "defaulted":
        raise ActionError(f"{d.id} is not overdue yet (due day {d.due_day})")
    if d.claim:
        raise ActionError(f"you already asked the mayor about {d.id}")
    if d.claim_day == ctx.world.day:
        raise ActionError("the mayor already ruled on it today; ask again tomorrow")
    mayor = ctx.world.governance.mayor
    if mayor is None:
        raise ActionError("the village has no mayor to ask")
    d.claim = {"tick": ctx.world.tick, "day": ctx.world.day}
    ctx.emit("debt_claim", f"{a.name} asks mayor {mayor} to make {d.borrower} pay {d.coins_owed} coins ({d.id}).",
             actor=a.name, visibility="public", debt=d.id)


class RuleArgs(BaseModel):
    debt_id: str
    decision: str = Field(description="collect | reject")


@ACTIONS.action("rule_debt", "Mayor only: decide a debt claim. collect takes what is owed from the debtor's coins "
                "(pocket, then chest) for the lender; reject drops the claim.", RuleArgs,
                available=lambda c, a: collection_on(c.cfg) and c.world.governance.mayor == a.name
                and any(d.claim and d.status in OWED for d in c.world.debts.values()))
def rule_debt(ctx: Ctx, a: Agent, args: RuleArgs) -> None:
    w = ctx.world
    if not collection_on(ctx.cfg) or w.governance.mayor != a.name:
        raise ActionError("only the mayor rules on debts")
    d = _debt(ctx, args.debt_id)
    if not d.claim:
        raise ActionError(f"nobody asked you to collect {d.id}")
    decision = args.decision.strip().lower()
    if decision not in ("collect", "reject"):
        raise ActionError("decision must be collect or reject")
    d.claim, d.claim_day = None, w.day
    if decision == "reject":
        ctx.emit("debt_rejected", f"Mayor {a.name} refused to collect {d.borrower}'s debt to {d.lender} ({d.id}).",
                 actor=a.name, visibility="public", debt=d.id)
        return
    debtor, lender = w.agents[d.borrower], w.agents[d.lender]
    take = min(d.coins_owed, debtor.coins)
    ops.move_coins(debtor, lender, take)
    chest = w.chests.get(f"chest_{debtor.name}")
    if chest and take < d.coins_owed:
        more = min(d.coins_owed - take, chest.coins)
        ops.move_coins(chest, lender, more)
        take += more
    fee = take * int(_cfg(ctx.cfg).get("collect_fee_pct", 0)) // 100
    ops.move_coins(lender, w.governance, fee)
    d.coins_owed -= take
    if d.coins_owed == 0:
        d.status = "repaid"
        on_repaid(ctx, d)
    left = f"{d.coins_owed} coins still owed" if d.coins_owed else "the debt is closed"
    ctx.emit("debt_collected", f"Mayor {a.name} collected {take} coins from {d.borrower} for {d.lender} "
             f"({fee} to the treasury; {left}; {d.id}).", actor=a.name, visibility="public", debt=d.id,
             coins=take, fee=fee)


class PayBillArgs(BaseModel):
    debt_id: str = Field(description="the bill's id in board.debts")
    coins: int | None = Field(None, gt=0, description="pay only part of it; leave out to pay it all")


@ACTIONS.action("pay_bill", "Pay a tax or fine bill you owe the treasury (board.debts, lender treasury), in full "
                "or in part, from anywhere.", PayBillArgs,
                available=lambda c, a: any(d.borrower == a.name and is_bill(d) and d.status in OWED
                                           for d in c.world.debts.values()))
def pay_bill(ctx: Ctx, a: Agent, args: PayBillArgs) -> None:
    d = ctx.world.debts.get(args.debt_id.strip())
    if d is None or d.borrower != a.name or not is_bill(d):
        raise ActionError(f"you have no bill '{args.debt_id}'")
    settle_bill(ctx, a, d, args.coins)


def settle_bill(ctx: Ctx, a: Agent, d: Debt, coins: int | None) -> None:
    """`a` pays `coins` (or all) of bill `d`: a tax is split like any tax (taxes.pay), a fine goes to the treasury."""
    from . import taxes
    if d.status not in OWED:
        raise ActionError(f"that bill is already closed ({d.status})")
    n = min(coins or d.coins_owed, d.coins_owed)
    if a.coins < n:
        raise ActionError(f"you only have {a.coins} coins (the bill is {d.coins_owed})")
    payee = next((h for f in BILL_PAYEES if (h := f(ctx.world, d)) is not None), None)
    if payee is not None:
        ops.move_coins(a, payee, n)
    elif d.kind == "tax":
        taxes.pay(ctx.world, a, n)
    else:
        governance.pay_tax(ctx.world, a, n)
    d.coins_owed -= n
    if d.coins_owed == 0:
        d.status, d.claim = "repaid", None
        on_repaid(ctx, d)
    ctx.emit("bill_paid", f"{a.name} paid {n} coins of their {d.kind} bill to the treasury ({d.id}, "
             f"{d.coins_owed} left).", actor=a.name, visibility="public", debt=d.id, coins=n, bill_kind=d.kind)


# ---------- night ----------

def night(ctx: Ctx) -> None:
    """Engine night: due debts default (or lose their pledge), defaulted debts grow by the late fee, then the
    village collects what it can of them (`auto_collect`)."""
    w = ctx.world
    pct = int(_cfg(ctx.cfg).get("late_fee_pct", 0))
    for d in w.debts.values():
        if d.status == "defaulted" and pct and not d.pledge and not is_bill(d):
            d.coins_owed += ceil(d.coins_owed * pct / 100)
        if d.status != "open" or w.day <= d.due_day:
            continue
        if is_bill(d):  # not a "default": no reputation rule, nobody collects it
            d.status = "defaulted"
            ctx.emit("bill_overdue", f"{d.borrower} has not paid their {d.kind} bill to the treasury by day "
                     f"{d.due_day} ({d.coins_owed} coins, {d.id}).", visibility="public", debt=d.id,
                     borrower=d.borrower, bill_kind=d.kind, coins=d.coins_owed)
        elif d.pledge:
            what = _return_pledge(ctx, d, d.lender)
            d.status = "forfeited"
            ctx.emit("pledge_forfeited", f"{d.borrower} did not repay {d.lender} on time ({d.coins_owed} coins, "
                     f"{d.id}); the pledge ({what}) went to {d.lender}.", visibility="public", debt=d.id)
        else:
            d.status = "defaulted"
            ctx.emit("default", f"{d.borrower} failed to repay {d.lender} on time ({d.coins_owed} coins, "
                     f"{d.id}).", visibility="public", debt=d.id)
    if auto_on(ctx.cfg):
        seize(ctx)


# ---------- automatic collection ----------

def _overdue(world: World, name: str) -> list[Debt]:
    """Defaulted debts the village collects from this debtor, oldest due day first."""
    out = [d for d in world.debts.values() if d.borrower == name and d.status == "defaulted" and not d.pledge
           and not is_bill(d) and world.agents[d.lender].status != "dead"]
    return sorted(out, key=lambda d: (d.due_day, d.day, d.id))


def _settle(ctx: Ctx, d: Debt, n: int) -> str:
    d.coins_owed -= n
    if d.coins_owed > 0:
        return f"{d.coins_owed} coins still owed"
    d.status = "repaid"
    on_repaid(ctx, d)
    return "the debt is closed"


def coin_snapshot(world: World) -> dict[str, int]:
    """Coins (pocket + chest) of every debtor in default, taken at the start of a tick."""
    if not auto_on(world.config):
        return {}
    names = {d.borrower for d in world.debts.values() if d.status == "defaulted" and not d.pledge and not is_bill(d)}
    return {n: world.agents[n].coins + _chest_coins(world, n) for n in sorted(names)}


def collect_income(ctx: Ctx, before: dict[str, int]) -> None:
    """End of tick: `seize_pct` of what each debtor in default gained this tick goes to their lenders."""
    w = ctx.world
    pct = int(_cfg(ctx.cfg).get("seize_pct", 50))
    for name, was in before.items():
        a = w.agents[name]
        gain = a.coins + _chest_coins(w, name) - was
        cut = gain * pct // 100
        for d in _overdue(w, name):
            if cut <= 0:
                break
            n = _take_coins(w, a, w.agents[d.lender], min(cut, d.coins_owed))
            if not n:
                break
            cut -= n
            left = _settle(ctx, d, n)
            ctx.emit("debt_garnished", f"{n} of the coins {name} just received went to {d.lender} for the overdue "
                     f"debt ({left}; {d.id}).", to=[name, d.lender], debt=d.id, coins=n, lender=d.lender,
                     borrower=name)


def _take_coins(world: World, debtor: Agent, lender: Agent, n: int) -> int:
    """Move up to n coins from the debtor's pocket, then chest, to the lender."""
    take = min(n, debtor.coins)
    ops.move_coins(debtor, lender, take)
    chest = world.chests.get(f"chest_{debtor.name}")
    if chest and take < n:
        more = min(n - take, chest.coins)
        ops.move_coins(chest, lender, more)
        take += more
    return take


def unit_price(cfg: dict, item: str) -> int:
    """What a seized item counts for: the trader's buying price (no crisis factors)."""
    return max(1, int(cfg["items"][item]["value"] * cfg["npc_buy_ratio"]))


def _seizable(cfg: dict, item: str) -> bool:
    spec = cfg["items"].get(item, {})
    return not spec.get("food") and spec.get("tradable", True) and "value" in spec


def seize(ctx: Ctx) -> None:
    """Night: each debtor in default loses up to `seize_pct` of their coins, then of their goods' value."""
    w = ctx.world
    pct = int(_cfg(ctx.cfg).get("seize_pct", 50))
    for name in sorted({d.borrower for d in w.debts.values() if d.status == "defaulted" and not is_bill(d)}):
        debtor = w.agents[name]
        if debtor.status == "dead":
            continue
        chest = w.chests.get(f"chest_{name}")
        coin_cap = (debtor.coins + (chest.coins if chest else 0)) * pct // 100
        stores = [debtor.inventory] + ([chest.items] if chest else [])
        goods_cap = sum(unit_price(ctx.cfg, i) * q for st in stores for i, q in st.items()
                        if q > 0 and _seizable(ctx.cfg, i)) * pct // 100
        for d in _overdue(w, name):
            lender = w.agents[d.lender]
            coins = _take_coins(w, debtor, lender, min(coin_cap, d.coins_owed))
            coin_cap -= coins
            goods: dict[str, int] = {}
            value = 0
            # dearest goods first, only whole items that fit both what is owed and the cap
            for item in sorted({i for st in stores for i in st if _seizable(ctx.cfg, i)},
                               key=lambda i: (-unit_price(ctx.cfg, i), i)):
                price = unit_price(ctx.cfg, item)
                for st in stores:
                    q = min(st.get(item, 0), (d.coins_owed - coins - value) // price, (goods_cap - value) // price)
                    if q > 0:
                        ops.move_items(st, lender.inventory, {item: q})
                        goods[item] = goods.get(item, 0) + q
                        value += q * price
            goods_cap -= value
            if not coins and not goods:
                continue
            left = _settle(ctx, d, coins + value)
            took = " and ".join(x for x in (f"{coins} coins" if coins else "",
                                            f"{fmt_items(goods)} (worth {value})" if goods else "") if x)
            ctx.emit("debt_seized", f"For the overdue debt to {d.lender} ({d.id}) the village took {took} from "
                     f"{name} and gave it to {d.lender}; {left}.", to=[name, d.lender], debt=d.id, coins=coins,
                     goods=goods, goods_value=value, lender=d.lender, borrower=name)
