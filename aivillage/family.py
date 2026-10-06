"""Friendship, courtship, marriage and inheritance.

Feelings are directed scores (what A feels about B). They move when villagers interact
(config `family.on_event`: gifts, loans, trades, thefts, help with a fire...), when they
`hang_out`, and drift back toward 0 each night. A villager who feels close enough can
propose; an accepted proposal is a wedding: the couple shares the proposer's house and
both chests. When a villager dies (or ends up in another `estate_statuses` state), their
belongings pass to the living spouse, else to the person they liked most among friends.

Feelings hook in via `ops.EVENT_HOOKS`; the engine calls `after_hour` (estates) and
`after_night` (decay, spouses, proposals); agents see `observe()["relations"]`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import ops
from .actions import _agent, _agent_here, _own_chest
from .ops import Ctx, Event, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, Marriage, Proposal, World


def _cfg(world: World) -> dict:
    return world.config["family"]


# ---------- feelings ----------

def feeling(world: World, a: str, b: str) -> int:
    return world.kin.feelings.get(a, {}).get(b, 0)


def change(world: World, a: str, b: str, delta: int) -> None:
    if a == b or delta == 0 or a not in world.agents or b not in world.agents:
        return
    cap = _cfg(world)["feeling_max"]
    row = world.kin.feelings.setdefault(a, {})
    v = max(-cap, min(cap, row.get(b, 0) + delta))
    if v:
        row[b] = v
    else:
        row.pop(b, None)
    if not row:
        del world.kin.feelings[a]


def label(world: World, v: int) -> str:
    t = _cfg(world)["friend_at"]
    return "friend" if v >= t else "enemy" if v <= -t else "liked" if v > 0 else "disliked" if v < 0 else "neutral"


def on_event(ctx: Ctx, ev: Event, recipients: list[str]) -> None:
    """ops.EVENT_HOOKS: move feelings as events happen."""
    world = ctx.world
    rule = _cfg(world)["on_event"].get(ev.kind)
    debt = world.debts.get(ev.data.get("debt", ""))
    actor = ev.actor or (debt.borrower if debt and ev.kind == "default" else None)
    if not rule or not actor:
        return
    who, delta = rule
    if who in ("to", "both"):
        for n in ev.to:
            if n != actor:
                change(world, n, actor, delta)
                if who == "both":
                    change(world, actor, n, delta)
    elif who == "lender":
        if debt:
            change(world, debt.lender, actor, delta)
    elif who == "owner":
        place = ev.location or world.agents[actor].location
        for o in world.agents.values():
            if o.home == place:
                change(world, o.name, actor, delta)


# ---------- marriage ----------

def spouse_of(world: World, name: str) -> str | None:
    for m in world.kin.marriages.values():
        if name in m.spouses:
            return next(s for s in m.spouses if s != name)
    return None


def _marriage(world: World, name: str) -> Marriage | None:
    return next((m for m in world.kin.marriages.values() if name in m.spouses), None)


def _end_marriage(world: World, m: Marriage) -> None:
    del world.kin.marriages[m.id]
    a, b = m.spouses
    for x, y in ((a, b), (b, a)):
        chest = world.chests.get(f"chest_{x}")
        if chest and y in chest.shared_with:
            chest.shared_with.remove(y)
        world.agents[x].home = f"home_{x}"


def _pair(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


class PersonArgs(BaseModel):
    person: str


class ProposeArgs(BaseModel):
    person: str
    public: bool = Field(True, description="true: the wedding is announced to the whole village; "
                                           "false: a secret wedding only you two know about")


class AnswerArgs(BaseModel):
    person: str
    accept: bool


@ACTIONS.action("hang_out", "Spend this hour with someone here; you both grow closer (once a day per person).",
                PersonArgs, available=lambda c, a: any(o.location == a.location and o.status == "active"
                                                       and o.name != a.name for o in c.world.agents.values()))
def hang_out(ctx: Ctx, a: Agent, args: PersonArgs) -> None:
    other = _agent_here(ctx, a, args.person)
    if other.asleep:
        raise ActionError(f"{other.name} is asleep")
    w, key = ctx.world, _pair(a.name, other.name)
    if w.kin.hung_out.get(key) == w.day:
        raise ActionError(f"you already spent time with {other.name} today")
    w.kin.hung_out[key] = w.day
    gain = _cfg(w)["hang_out_gain"]
    change(w, a.name, other.name, gain)
    change(w, other.name, a.name, gain)
    ctx.emit("hang_out", f"{a.name} spent time with {other.name}.", actor=a.name, location=a.location,
             visibility="location", to=[other.name])


@ACTIONS.action("propose", "Ask someone here to marry you (you share a house and chests). Needs real closeness. "
                "public: announce the wedding to the village, or keep it secret between you two.",
                ProposeArgs, available=lambda c, a: spouse_of(c.world, a.name) is None)
def propose(ctx: Ctx, a: Agent, args: ProposeArgs) -> None:
    w, cfg = ctx.world, _cfg(ctx.world)
    other = _agent_here(ctx, a, args.person)
    if spouse_of(w, a.name):
        raise ActionError("you are already married")
    if spouse_of(w, other.name):
        raise ActionError(f"{other.name} is already married")
    if feeling(w, a.name, other.name) < cfg["propose_min"]:
        raise ActionError(f"you do not feel close enough to {other.name} yet "
                          f"({feeling(w, a.name, other.name)}/{cfg['propose_min']}); spend time together")
    if any(p.sender == a.name and p.to == other.name for p in w.kin.proposals.values()):
        raise ActionError(f"you already proposed to {other.name}; wait for the answer")
    if a.coins < cfg["wedding_cost"]:
        raise ActionError(f"a wedding costs {cfg['wedding_cost']} coins, you have {a.coins}")
    p = Proposal(w.new_id("proposal"), a.name, other.name, w.day + cfg["proposal_ttl_days"], args.public)
    w.kin.proposals[p.id] = p
    kind = "" if args.public else " in a secret wedding"
    ctx.emit("proposal", f"{a.name} asked {other.name} to marry them{kind}!", actor=a.name, location=a.location,
             visibility="location" if args.public else "private", to=[other.name])


@ACTIONS.action("answer_proposal", "Accept or refuse someone's marriage proposal (accept: true/false).",
                AnswerArgs, available=lambda c, a: any(p.to == a.name for p in c.world.kin.proposals.values()))
def answer_proposal(ctx: Ctx, a: Agent, args: AnswerArgs) -> None:
    w, cfg = ctx.world, _cfg(ctx.world)
    other = _agent(ctx, args.person)
    p = next((p for p in w.kin.proposals.values() if p.sender == other.name and p.to == a.name), None)
    if p is None:
        raise ActionError(f"{other.name} has not proposed to you")
    if not args.accept:
        del w.kin.proposals[p.id]
        change(w, other.name, a.name, -5)
        ctx.emit("proposal_refused", f"{a.name} refused to marry {other.name}.", actor=a.name,
                 visibility="public", to=[other.name])
        return
    if spouse_of(w, a.name) or spouse_of(w, other.name):
        del w.kin.proposals[p.id]
        raise ActionError("one of you is already married")
    if other.status != "active":
        raise ActionError(f"{other.name} cannot marry right now ({other.status})")
    if feeling(w, a.name, other.name) < cfg["propose_min"]:
        raise ActionError(f"you do not feel close enough to {other.name} "
                          f"({feeling(w, a.name, other.name)}/{cfg['propose_min']}); refuse or wait")
    if other.coins < cfg["wedding_cost"]:
        raise ActionError(f"{other.name} cannot pay the {cfg['wedding_cost']}-coin wedding now")
    del w.kin.proposals[p.id]
    for q in [q for q in w.kin.proposals.values() if {q.sender, q.to} & {a.name, other.name}]:
        del w.kin.proposals[q.id]
    ops.burn_coins(w, other, cfg["wedding_cost"])
    m = Marriage(w.new_id("marriage"), [other.name, a.name], other.home, w.day, p.public)
    w.kin.marriages[m.id] = m
    a.home = other.home
    for x, y in ((other.name, a.name), (a.name, other.name)):
        chest = w.chests[f"chest_{x}"]
        if y not in chest.shared_with:
            chest.shared_with.append(y)
    floor = cfg["propose_min"] + cfg["wedding_boost"]
    for x, y in ((a.name, other.name), (other.name, a.name)):
        change(w, x, y, max(0, floor - feeling(w, x, y)))
    secret = "" if m.public else " (a secret wedding: only you two know)"
    ctx.emit("wedding", f"{other.name} and {a.name} are married{secret}! They now share {w.locations[m.home].name} "
             f"and each other's chests.", actor=a.name, visibility="public" if m.public else "private",
             to=[other.name], marriage=m.id)


@ACTIONS.action("divorce", "End your marriage: you move back to your own house and chests are no longer shared.",
                available=lambda c, a: spouse_of(c.world, a.name) is not None)
def divorce(ctx: Ctx, a: Agent, args) -> None:
    w = ctx.world
    m = _marriage(w, a.name)
    if m is None:
        raise ActionError("you are not married")
    other = spouse_of(w, a.name)
    _end_marriage(w, m)
    change(w, other, a.name, -_cfg(w)["divorce_hurt"])
    ctx.emit("divorce", f"{a.name} divorced {other}.", actor=a.name, visibility="public" if m.public else "private",
             to=[other])


# ---------- inheritance ----------

def heir_of(world: World, name: str) -> str | None:
    """Living spouse, else the friend the deceased liked most (ties: alphabetical)."""
    gone = set(_cfg(world)["estate_statuses"])
    sp = spouse_of(world, name)
    if sp and world.agents[sp].status not in gone:
        return sp
    t = _cfg(world)["friend_at"]
    friends = [(-v, b) for b, v in world.kin.feelings.get(name, {}).items()
               if v >= t and world.agents[b].status not in gone]
    return min(friends)[1] if friends else None


def settle_estate(ctx: Ctx, name: str) -> None:
    w = ctx.world
    a = w.agents[name]
    w.kin.settled.append(name)
    heir = heir_of(w, name)
    m = _marriage(w, name)
    spouse_of_before = spouse_of(w, name)
    if m:
        _end_marriage(w, m)
    for p in [p for p in w.kin.proposals.values() if name in (p.sender, p.to)]:
        del w.kin.proposals[p.id]
    own = w.chests[f"chest_{name}"]
    if _cfg(w).get("pay_debts_first", True):
        _pay_debts(ctx, a, own)
    if heir is None:
        return
    dst = w.chests[f"chest_{heir}"]
    items: dict[str, int] = {}
    for src in (a.inventory, own.items):
        for k, v in list(src.items()):
            items[k] = items.get(k, 0) + v
            ops.move_items(src, dst.items, {k: v})
    coins = a.coins + own.coins
    ops.move_coins(a, dst, a.coins)
    ops.move_coins(own, dst, own.coins)
    houses = sorted(h for h, p in w.plots.items() if p.owner == name)
    for h in houses:
        w.plots[h].owner, w.plots[h].sale = heir, None
    places = "".join(f", {w.locations[h].name}" for h in houses)
    secret = m is not None and not m.public and heir == spouse_of_before
    ctx.emit("inheritance", f"{heir} inherits from {name}: {fmt_items(items)}, {coins} coins{places} "
             f"(things now in {heir}'s chest).", actor=heir, visibility="private" if secret else "public",
             to=[heir], deceased=name, houses=houses)


def _pay_debts(ctx: Ctx, a: Agent, own) -> None:
    """Open debts of the deceased are paid from their coins first (to living lenders, oldest first)."""
    w = ctx.world
    gone = set(_cfg(w)["estate_statuses"])
    for d in sorted(w.debts.values(), key=lambda d: (d.due_day, d.id)):
        if (d.borrower != a.name or d.status == "repaid" or d.lender not in w.agents  # treasury bills
                or w.agents[d.lender].status in gone):
            continue
        paid = 0
        for src in (a, own):
            n = min(src.coins, d.coins_owed - paid)
            ops.move_coins(src, w.agents[d.lender], n)
            paid += n
        if not paid:
            continue
        d.coins_owed -= paid
        if d.coins_owed == 0:
            d.status = "repaid"
        ctx.emit("estate_debt", f"{d.lender} got {paid} coins back from {a.name}'s estate"
                 f"{'' if d.coins_owed == 0 else f' ({d.coins_owed} still unpaid)'}.", to=[d.lender],
                 deceased=a.name, debt=d.id)


# ---------- engine hooks ----------

ops.EVENT_HOOKS.append(on_event)


def after_hour(ctx: Ctx) -> None:
    """Estates of anyone who just left the village (death, exile)."""
    _settle_all(ctx)


def after_night(ctx: Ctx) -> None:
    w, cfg = ctx.world, _cfg(ctx.world)
    for row in list(w.kin.feelings.values()):
        for b, v in list(row.items()):
            row[b] = v - cfg["decay_per_night"] if v > 0 else v + cfg["decay_per_night"]
            if v * row[b] <= 0:
                del row[b]
    for k in [k for k, row in w.kin.feelings.items() if not row]:
        del w.kin.feelings[k]
    for m in w.kin.marriages.values():
        a, b = m.spouses
        change(w, a, b, cfg["spouse_night_gain"] + cfg["decay_per_night"])
        change(w, b, a, cfg["spouse_night_gain"] + cfg["decay_per_night"])
    for p in [p for p in w.kin.proposals.values() if w.day > p.expires_day]:
        del w.kin.proposals[p.id]
    _settle_all(ctx)


def _settle_all(ctx: Ctx) -> None:
    gone = set(_cfg(ctx.world)["estate_statuses"])
    for a in ctx.world.agents.values():
        if a.status in gone and a.name not in ctx.world.kin.settled:
            settle_estate(ctx, a.name)


def observe(world: World, name: str) -> dict:
    m = _marriage(world, name)
    return {
        "feelings": {b: {"score": v, "label": label(world, v)}
                     for b, v in sorted(world.kin.feelings.get(name, {}).items())},
        "spouse": spouse_of(world, name),
        "family_home": m.home if m else None,
        "proposals_to_you": [{"from": p.sender, "expires_day": p.expires_day}
                             for p in world.kin.proposals.values() if p.to == name],
        "your_proposals": [{"to": p.to, "expires_day": p.expires_day}
                           for p in world.kin.proposals.values() if p.sender == name],
    }
