"""Reputation and rumors: what each villager knows about the others.

Reputation is subjective. Nobody has a global score: each agent keeps its own tally of
deeds it saw or lived through (a theft it witnessed, a debt repaid to it, someone putting
out a fire). Public events (a default on the board, a fire put out) reach everyone.

Rumors are claims, not facts. `gossip` tells people here something about a third villager;
it may be true or false and the engine never judges it. Hearers store it in `rumors` with
who said it, and decide for themselves whether to believe it. Rumors never change a score.

State lives on the agent (`Agent.reputation`, `Agent.rumors`), so old logs load unchanged.
The engine reaches this module only through `ops.EVENT_HOOKS` and `observe()`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import ops
from .actions import _agent, _text
from .ops import Ctx, Event
from .registry import ACTIONS, ActionError
from .state import Agent


def _cfg(world) -> dict:
    return world.config["reputation"]


def _debt_party(world, ev: Event, field: str) -> str | None:
    d = world.debts.get(ev.data.get("debt", ""))
    return getattr(d, field) if d else None


def _subject(world, ev: Event, recipient: str) -> str | None:
    """Who the event says something about, from `recipient`'s point of view."""
    k = ev.kind
    if k == "witness":
        return ev.data.get("thief")
    if k == "default":
        return _debt_party(world, ev, "borrower")
    if k == "repay":
        d = world.debts.get(ev.data.get("debt", ""))
        # Only a full repayment on time counts as a good deed.
        return d.borrower if d and d.status == "repaid" and world.day <= d.due_day else None
    if k in ("fire_out", "extinguish"):
        return ev.data.get("helper")
    if k == "trade":
        partner = ev.data.get("partner")
        if recipient == ev.actor:
            return partner
        return ev.actor if recipient == partner else None  # bystanders learn nothing about fairness
    if k in ("steal_attempt", "give", "lend", "contribute"):
        return ev.actor
    return None


def on_event(ctx: Ctx, ev: Event, recipients: list[str]) -> None:
    w = ctx.world
    if "reputation" not in w.config:
        return
    cfg = _cfg(w)
    if not cfg["enabled"]:
        return
    if ev.kind == "gossip_heard":
        _store_rumor(w, ev, recipients)
        return
    delta = cfg["deltas"].get(ev.kind)
    if delta is None:
        return
    for name in recipients:
        subject = _subject(w, ev, name)
        a = w.agents.get(name)
        if a is None or subject is None or subject == name or subject not in w.agents:
            continue
        rec = a.reputation.setdefault(subject, {"score": 0, "seen": []})
        rec["score"] = max(-cfg["score_cap"], min(cfg["score_cap"], rec["score"] + delta))
        rec["seen"].append(f"day {ev.day}: {ev.text}")
        del rec["seen"][: -cfg["notes_per_person"]]


def _store_rumor(w, ev: Event, recipients: list[str]) -> None:
    cfg = _cfg(w)
    for name in recipients:
        a = w.agents.get(name)
        if a is None or name in (ev.actor, ev.data["about"]):
            continue
        a.rumors.append({"day": ev.day, "from": ev.actor, "about": ev.data["about"], "text": ev.data["text_raw"]})
        del a.rumors[: -cfg["rumors_kept"]]


ops.EVENT_HOOKS.append(on_event)


def observe(world, name: str) -> dict:
    """Fields added to the agent's observation; empty ones are left out to save tokens."""
    if not world.config.get("reputation", {}).get("enabled"):
        return {}
    a = world.agents[name]
    out: dict = {}
    if a.reputation:
        out["reputation"] = {k: dict(v, seen=list(v["seen"])) for k, v in sorted(a.reputation.items())}
    if a.rumors:
        out["rumors"] = [dict(r) for r in a.rumors]
    return out


def fact(cfg: dict) -> str | None:
    """One neutral line for the LLM rules cheat sheet."""
    if not cfg.get("reputation", {}).get("enabled"):
        return None
    return ("- \"reputation\" is what YOU saw others do (score: your own tally, good deeds up, bad deeds down). "
            "\"rumors\" are what others told you with gossip: they may be true or false, nobody checks.")


# ---- action ----

class GossipArgs(BaseModel):
    about: str = Field(description="the villager the rumor is about")
    text: str = Field(description="what you claim about them (true or not)")
    to: str | None = Field(None, description="one person here; leave empty to tell everyone here")


def _can_gossip(ctx: Ctx, a: Agent) -> bool:
    return any(o.name != a.name and o.status == "active" and not o.asleep and o.location == a.location
               for o in ctx.world.agents.values())


@ACTIONS.action("gossip", "Tell people here something about another villager (true or false). "
                "They remember who told them.", GossipArgs, available=_can_gossip)
def gossip(ctx: Ctx, a: Agent, args: GossipArgs) -> None:
    about = _agent(ctx, args.about)
    if about.name == a.name:
        raise ActionError("gossip is about someone else")
    t = _text(ctx, args.text)
    if args.to:
        other = _agent(ctx, args.to)
        if other.name == a.name:
            raise ActionError("you cannot gossip to yourself")
        if other.status != "active" or other.location != a.location or other.asleep:
            raise ActionError(f"{other.name} is not here and awake")
        if other.name == about.name:
            raise ActionError(f"that is {about.name} themselves; use say or whisper")
        hearers = [other.name]
    else:
        hearers = [o.name for o in ctx.world.agents.values()
                   if o.name not in (a.name, about.name) and o.status == "active"
                   and not o.asleep and o.location == a.location]
        if not hearers:
            raise ActionError(f"nobody here to tell (besides {about.name})" if any(
                o.name == about.name and o.location == a.location for o in ctx.world.agents.values())
                else "nobody here to tell")
    ctx.emit("gossip_heard", f'{a.name} tells you about {about.name}: "{t}"', actor=a.name, to=hearers,
             about=about.name, text_raw=t)
    ctx.emit("gossip", f"You told {', '.join(hearers)} about {about.name}.", actor=a.name, to=[a.name],
             about=about.name, text_raw=t, hearers=hearers)
