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

import random
import re

from pydantic import BaseModel, Field

from . import governance, ops
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
    if k in ("construct", "site_supplied"):  # help on a building site: not on one's own
        return ev.actor if ev.data.get("owner") != ev.actor else None
    if k in ("steal_attempt", "give", "lend", "contribute", "build_work"):
        return ev.actor
    if k == "embezzlement_found":
        return ev.data.get("mayor")
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
    if ev.kind == "whisper" and ev.actor and ev.to and ev.to != [ev.actor]:
        _overhear_whisper(ctx, ev)
        return
    delta = cfg["deltas"].get(ev.kind)
    if delta is None:
        return
    for name in recipients:
        note(w, name, _subject(w, ev, name), delta, f"day {ev.day}: {ev.text}")


def note(w, name: str, subject: str | None, delta: int, text: str) -> None:
    """`name` saw `subject` do something: move their own score by delta and keep the note."""
    if not w.config.get("reputation", {}).get("enabled"):
        return
    cfg = _cfg(w)
    a = w.agents.get(name)
    if a is None or subject is None or subject == name or subject not in w.agents:
        return
    rec = a.reputation.setdefault(subject, {"score": 0, "seen": []})
    rec["score"] = max(-cfg["score_cap"], min(cfg["score_cap"], rec["score"] + delta))
    rec["seen"].append(text)
    del rec["seen"][: -cfg["notes_per_person"]]


def _store_rumor(w, ev: Event, recipients: list[str]) -> None:
    cfg = _cfg(w)
    for name in recipients:
        a = w.agents.get(name)
        if a is None or name in (ev.actor, ev.data["about"]):
            continue
        if "rumor" not in ev.data:  # logs from before rumor chains: keep their exact state
            a.rumors.append({"day": ev.day, "from": ev.actor, "about": ev.data["about"], "text": ev.data["text_raw"]})
        else:
            keep(a, ev.day, ev.actor, ev.data, ev.data["about"], ev.data["text_raw"])
        del a.rumors[: -cfg["rumors_kept"]]


def keep(a: Agent, day: int, teller: str, data: dict, about: str, text: str, overheard: bool = False) -> None:
    """Store what `a` heard. Hearing the same rumor again moves it to the end and adds the teller."""
    old = next((r for r in a.rumors if r.get("id") == data["rumor"]), None)
    told_by = [] if old is None else [n for n in [old["from"], *old.get("also_from", [])] if n != teller]
    if old is not None:
        a.rumors.remove(old)
    r = {"id": data["rumor"], "day": day, "from": teller, "about": about, "text": text,
         "started_by": data["origin"], "retold": data["hops"] - 1}
    if told_by:
        r["also_from"] = told_by
    if overheard:
        r["overheard"] = True
    a.rumors.append(r)


# ---- word of mouth: mishearing and overhearing ----
# Each hearer rolls on its own rng stream (seed, tick, teller, hearer), so these rolls never shift
# any other random draw and replay stays exact.

def _rng(w, *salt: str) -> random.Random:
    return random.Random(f"{w.config['seed']}:{w.tick}:rumor:{':'.join(salt)}")


_NUMBER = re.compile(r"\d+")


def mishear(w, hearer: str, teller: str, about: str, text: str) -> tuple[str, str, list[str]]:
    """What `hearer` actually catches of a rumor: a number may come out different, and now and then the
    rumor lands on the wrong villager. Returns (about, text, what changed)."""
    cfg = _cfg(w)
    r = _rng(w, teller, hearer)
    changed = []
    nums = _NUMBER.findall(text)
    if nums and r.random() < cfg.get("mishear_number", 0):
        m = r.choice(list(_NUMBER.finditer(text)))
        n = int(m.group())
        new = max(1, n * 2) if r.random() < 0.6 else max(1, n // 2) if n > 1 else n + 2
        text = text[:m.start()] + str(new) + text[m.end():]
        changed.append(f"number {n}->{new}")
    if r.random() < cfg.get("mishear_name", 0):
        others = sorted(n for n, o in w.agents.items() if n not in (hearer, teller, about) and o.status != "dead")
        if others:
            new = r.choice(others)
            text = re.sub(rf"\b{re.escape(about)}\b", new, text)
            changed.append(f"name {about}->{new}")
            about = new
    return about, text, changed


def overhearers(w, speaker: str, listener: str) -> list[str]:
    """Bystanders who catch a private word (whisper, gossip to one person) said at `speaker`'s place."""
    p = _cfg(w).get("overhear", 0)
    if not p:
        return []
    loc = w.agents[speaker].location
    return [o.name for o in w.agents.values()
            if o.name not in (speaker, listener) and o.status == "active" and not o.asleep and o.location == loc
            and _rng(w, "overhear", speaker, o.name).random() < p]


def _overhear_whisper(ctx: Ctx, ev: Event) -> None:
    listener = ev.to[0]
    for name in overhearers(ctx.world, ev.actor, listener):
        ctx.emit("overheard", f'You overhear {ev.actor} whisper to {listener}: "{ev.data["text_raw"]}"',
                 actor=ev.actor, to=[name], listener=listener, text_raw=ev.data["text_raw"])


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
    if "announce_cost" in _cfg(world):
        out["notice_board"] = {"at": _cfg(world)["announce_at"], "notice_cost": _cfg(world)["announce_cost"]}
    return out


def fact(cfg: dict) -> str | None:
    """One neutral line for the LLM rules cheat sheet."""
    if not cfg.get("reputation", {}).get("enabled"):
        return None
    line = ("- \"reputation\" is what YOU saw others do (score: your own tally; it falls after thefts, violence and "
            "unpaid debts you saw, rises after help, gifts, trades and repaid debts). "
            "\"rumors\" are what others told you with gossip: they may be true or false, nobody checks.")
    if "origin_hops" in cfg["reputation"]:
        line += (" Pass one on with gossip(rumor=id). Words change from mouth to mouth: a retold rumor may lose "
                 "who started it, and a hearer may catch a detail wrong. A whisper or gossip to one person "
                 "may be overheard by others there.")
    return line


# ---- action ----

class GossipArgs(BaseModel):
    about: str | None = Field(None, description="the villager the rumor is about (may be left out when passing on a rumor)")
    text: str | None = Field(None, description="what you claim about them, true or not (left out: you repeat the rumor as you heard it)")
    to: str | None = Field(None, description="one person here; leave empty to tell everyone here")
    rumor: str | None = Field(None, description="id of a rumor you heard, to pass it on")


def _can_gossip(ctx: Ctx, a: Agent) -> bool:
    return any(o.name != a.name and o.status == "active" and not o.asleep and o.location == a.location
               for o in ctx.world.agents.values())


@ACTIONS.action("gossip", "Tell people here something about another villager, or pass on a rumor you heard. "
                "They remember who told them.", GossipArgs, available=_can_gossip)
def gossip(ctx: Ctx, a: Agent, args: GossipArgs) -> None:
    w = ctx.world
    chains = "origin_hops" in _cfg(w)  # False only for configs from logs older than rumor chains
    heard = None
    if args.rumor:
        if not chains:
            raise ActionError("rumor ids are not used in this village")
        heard = next((r for r in a.rumors if r.get("id") == args.rumor), None)
        if heard is None:
            raise ActionError(f"you have not heard a rumor {args.rumor!r}; see your rumors")
    about_name = args.about or (heard and heard["about"])
    if not about_name:
        raise ActionError("say who the rumor is about")
    about = _agent(ctx, about_name)
    if about.name == a.name:
        raise ActionError("gossip is about someone else")
    t = _text(ctx, args.text if args.text or heard is None else heard["text"])
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
        hearers = [o.name for o in w.agents.values()
                   if o.name not in (a.name, about.name) and o.status == "active"
                   and not o.asleep and o.location == a.location]
        if not hearers:
            raise ActionError(f"nobody here to tell (besides {about.name})" if any(
                o.name == about.name and o.location == a.location for o in w.agents.values())
                else "nobody here to tell")
    if not chains:
        ctx.emit("gossip_heard", f'{a.name} tells you about {about.name}: "{t}"', actor=a.name, to=hearers,
                 about=about.name, text_raw=t)
        ctx.emit("gossip", f"You told {', '.join(hearers)} about {about.name}.", actor=a.name, to=[a.name],
                 about=about.name, text_raw=t, hearers=hearers)
        return
    # A retold rumor keeps its id; who started it is passed along for `origin_hops` retellings, then lost.
    same = heard is not None and about.name == heard["about"]
    rid = heard["id"] if same else f"r{w.tick}.{a.name}"
    hops = heard.get("retold", 0) + 2 if same else 1
    origin = (heard.get("started_by") if same else a.name) if hops <= _cfg(w)["origin_hops"] else None
    chain = {"rumor": rid, "origin": origin, "hops": hops}
    src = "" if hops == 1 else f" (they heard it from {origin})" if origin else " (they heard it from someone)"
    for name in hearers:
        h_about, h_text, changed = mishear(w, name, a.name, about.name, t)
        ctx.emit("gossip_heard", f'{a.name} tells you about {h_about}{src}: "{h_text}"', actor=a.name, to=[name],
                 about=h_about, text_raw=h_text, said=t, misheard=changed, **chain)
    ctx.emit("gossip", f"You told {', '.join(hearers)} about {about.name}.", actor=a.name, to=[a.name],
             about=about.name, text_raw=t, hearers=hearers, **chain)
    if len(hearers) == 1:  # told to one person: others here may catch it
        for name in overhearers(w, a.name, hearers[0]):
            if name == about.name:
                ctx.emit("overheard", f'You overhear {a.name} tell {hearers[0]} about you: "{t}"', actor=a.name,
                         to=[name], listener=hearers[0], about=about.name, text_raw=t)
                continue
            h_about, h_text, changed = mishear(w, name, a.name, about.name, t)
            ev = ctx.emit("overheard", f'You overhear {a.name} tell {hearers[0]} about {h_about}{src}: "{h_text}"',
                          actor=a.name, to=[name], listener=hearers[0], about=h_about, text_raw=h_text,
                          misheard=changed, **chain)
            keep(w.agents[name], ev.day, a.name, chain, h_about, h_text, overheard=True)
            del w.agents[name].rumors[: -_cfg(w)["rumors_kept"]]


# ---- notice board: paid, public, exact ----
# The opposite of a rumor: it costs coins, but every villager learns it at once, word for word,
# under the author's name. Villagers use it for whatever they make up (a wedding, a funeral, a sale).

class AnnounceArgs(BaseModel):
    text: str = Field(description="the notice, seen by every villager at once under your name")


def _can_announce(ctx: Ctx, a: Agent) -> bool:
    cfg = _cfg(ctx.world)
    return "announce_cost" in cfg and a.location == cfg["announce_at"] and a.coins >= cfg["announce_cost"]


@ACTIONS.action("announce", "Pin a notice on the village board: every villager reads it at once. Costs coins "
                "(see the board's notice_cost).", AnnounceArgs, available=_can_announce)
def announce(ctx: Ctx, a: Agent, args: AnnounceArgs) -> None:
    w = ctx.world
    cfg = _cfg(w)
    if "announce_cost" not in cfg:
        raise ActionError("there is no notice board in this village")
    if a.location != cfg["announce_at"]:
        raise ActionError(f"the notice board is at {cfg['announce_at']}")
    cost = cfg["announce_cost"]
    if a.coins < cost:
        raise ActionError(f"a notice costs {cost} coins, you have {a.coins}")
    t = _text(ctx, args.text)
    governance.pay_tax(w, a, cost)  # to the treasury when there is a government, else burned
    ctx.emit("announcement", f'NOTICE from {a.name}: "{t}"', actor=a.name, location=a.location,
             visibility="public", text_raw=t, cost=cost)
