"""Dice for coins: the village's one game of chance.

`dice(person, stake)` at a dice place (`dice.places`, the square by default). The first call is a
challenge that waits `offer_hours`; the game is played when the other person calls `dice` back with
the same stake (a different stake is a counter-offer that replaces theirs). Each player rolls
`dice` d`sides` (seeded engine dice, so replay is exact), the higher total takes the stake; a tie is
rolled again up to `rerolls` times, then it is a draw and no coins move.

Losing on credit: a player may stake up to their coins + `credit`. A loser who cannot cover the
stake pays what they carry and owes the rest to the winner as an ordinary debt (world.debts, the
public board, `repay` as usual) due in `debt_days` days.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import clock, ops
from .actions import _agent_here
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, Debt


def _c(cfg: dict) -> dict:
    return cfg["dice"]


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("dice", {}).get("enabled"))


def _offer(ctx: Ctx, a: Agent) -> dict | None:
    o = a.dice_offer
    return o if o and o["expires_tick"] > ctx.world.tick else None


class DiceArgs(BaseModel):
    person: str = Field(description="a person here to play against")
    stake: int = Field(description="coins the loser pays the winner")


def _can_dice(ctx: Ctx, a: Agent) -> bool:
    return enabled(ctx.cfg) and a.location in _c(ctx.cfg)["places"] and any(
        o.name != a.name and o.status == "active" and o.location == a.location for o in ctx.world.agents.values())


def _roll(ctx: Ctx) -> int:
    c = _c(ctx.cfg)
    return sum(ctx.rng.randint(1, c["sides"]) for _ in range(c["dice"]))


@ACTIONS.action("dice", "Play dice for coins with a person here: you challenge them, the game is played when they "
                "answer dice with you for the same stake. Higher roll takes the stake; a loser short of coins owes "
                "the rest as a debt.", DiceArgs, available=_can_dice)
def dice(ctx: Ctx, a: Agent, args: DiceArgs) -> None:
    c, w = _c(ctx.cfg), ctx.world
    if not enabled(ctx.cfg):
        raise ActionError("dice are not played in this village")
    if a.location not in c["places"]:
        raise ActionError(f"dice are played at: {', '.join(w.locations[p].name for p in c['places'])}")
    other = _agent_here(ctx, a, args.person)
    if other.asleep:
        raise ActionError(f"{other.name} is asleep")
    if not 1 <= args.stake <= c["max_stake"]:
        raise ActionError(f"the stake must be 1..{c['max_stake']} coins")
    for p in (a, other):
        if p.coins + c["credit"] < args.stake:
            who = "you have" if p is a else f"{p.name} has"
            raise ActionError(f"{who} {p.coins} coins; the stake can be at most coins + {c['credit']} on credit")
    theirs = _offer(ctx, other)
    if not (theirs and theirs["to"] == a.name and theirs["stake"] == args.stake):
        a.dice_offer = {"to": other.name, "stake": args.stake,
                        "expires_tick": w.tick + clock.hours(ctx.cfg, c["offer_hours"])}
        counter = " instead" if theirs and theirs["to"] == a.name else ""
        ctx.emit("dice_challenge", f"{a.name} challenged {other.name} to dice for {args.stake} coins{counter}.",
                 actor=a.name, location=a.location, visibility="location", to=[other.name], stake=args.stake)
        return
    a.dice_offer = other.dice_offer = None
    rolls: list[list[int]] = []
    for _ in range(c["rerolls"] + 1):
        rolls.append([_roll(ctx), _roll(ctx)])  # [challenger, answerer]
        if rolls[-1][0] != rolls[-1][1]:
            break
    x, y = rolls[-1]
    shown = "; ".join(f"{other.name} {r[0]} vs {a.name} {r[1]}" for r in rolls)
    if x == y:
        ctx.emit("dice", f"{other.name} and {a.name} played dice for {args.stake} coins: {shown}. A draw.",
                 actor=a.name, location=a.location, visibility="location", to=[other.name],
                 stake=args.stake, rolls=rolls, winner=None)
        return
    win, lose = (other, a) if x > y else (a, other)
    paid = min(lose.coins, args.stake)
    ops.move_coins(lose, win, paid)
    text = f"{other.name} and {a.name} played dice for {args.stake} coins: {shown}. {win.name} won"
    data: dict = {}
    if paid < args.stake:
        d = Debt(w.new_id("debt"), win.name, lose.name, args.stake - paid, w.day + c["debt_days"])
        w.debts[d.id] = d
        data["debt"] = d.id
        text += f"; {lose.name} paid {paid} and owes {d.coins_owed} by day {d.due_day} ({d.id})"
    ctx.emit("dice", text + ".", actor=a.name, location=a.location, visibility="location", to=[other.name],
             stake=args.stake, rolls=rolls, winner=win.name, loser=lose.name, paid=paid, **data)


def observe(world, name: str) -> dict:
    if not enabled(world.config):
        return {}
    return {"dice_challenges_to_you": [{"from": o.name, "stake": o.dice_offer["stake"]}
                                       for o in world.agents.values()
                                       if o.dice_offer and o.dice_offer["to"] == name
                                       and o.dice_offer["expires_tick"] > world.tick]}


def facts(cfg: dict) -> str:
    c = _c(cfg)
    return (f"- Dice at the {', '.join(c['places'])}: dice(person, stake) challenges someone there; it is played "
            f"when they answer dice with you for the same stake (within {c['offer_hours']} h). Each rolls "
            f"{c['dice']}d{c['sides']}, the higher total takes the stake (up to {c['max_stake']}). You may stake "
            f"up to your coins + {c['credit']}: a loser short of coins owes the rest as a debt due in "
            f"{c['debt_days']} days.")
