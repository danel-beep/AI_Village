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


def _cfg(cfg: dict) -> dict:
    return cfg.get("debts", {})


def collection_on(cfg: dict) -> bool:
    return bool(_cfg(cfg).get("collection", True)) and governance.enabled(cfg)


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
    if collection_on(cfg):
        s += (f" The lender of an overdue debt can demand_debt: the mayor decides whether to collect it from the "
              f"debtor's coins (pocket, then chest; {c.get('collect_fee_pct', 0)}% goes to the treasury).")
    else:
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


# ---------- night ----------

def night(ctx: Ctx) -> None:
    """Engine night: due debts default (or lose their pledge), defaulted debts grow by the late fee."""
    w = ctx.world
    pct = int(_cfg(ctx.cfg).get("late_fee_pct", 0))
    for d in w.debts.values():
        if d.status == "defaulted" and pct and not d.pledge:
            d.coins_owed += ceil(d.coins_owed * pct / 100)
        if d.status != "open" or w.day <= d.due_day:
            continue
        if d.pledge:
            what = _return_pledge(ctx, d, d.lender)
            d.status = "forfeited"
            ctx.emit("pledge_forfeited", f"{d.borrower} did not repay {d.lender} on time ({d.coins_owed} coins, "
                     f"{d.id}); the pledge ({what}) went to {d.lender}.", visibility="public", debt=d.id)
        else:
            d.status = "defaulted"
            ctx.emit("default", f"{d.borrower} failed to repay {d.lender} on time ({d.coins_owed} coins, "
                     f"{d.id}).", visibility="public", debt=d.id)
