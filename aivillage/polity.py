"""Polities: a town hall founds a community that governs itself (config `polity`, off by default; on in «С нуля»).

Rules, in the order a villager meets them:
- A finished town_hall (construction.py; any common place) founds a polity there. Its builders who belong to no
  polity are the first members. Anyone may join_polity (from anywhere; it leaves their old polity) or
  leave_polity. Another town hall founds another polity, with its own name, laws and treasury.
- Founding ballot (polity_vote, members only): the polity's name, the name of its coins, its form of government
  and, for a council or a ruler, who. It closes `vote_hours` after founding; a question nobody voted on stays
  open for another `vote_hours`. Most votes wins, a tie is broken by the world rng. The forms are listed in a
  random order per polity and described by their rules only, no judgement.
- Forms: assembly (every member votes on laws; yes from more than half of the members passes one), council
  (the `council_size` most voted members; yes from more than half of the council), ruler (the most voted member;
  the ruler's own proposals pass at once).
- Laws (polity_propose / polity_vote_law): tax (coins per member every tax day), income_tax (percent of the coins
  a member got from the trader and orders since the polity's last tax day), wealth_tax (percent of a member's coins
  on tax day), tax_every (days between the polity's tax days; the village's `tax_every_days` until a law sets it),
  fine (a member owes the treasury), grant (treasury coins to a member), payout (the treasury split among the
  members), expel (a member leaves and may not join again for `expel_days`). A new polity taxes nothing: whether
  there is a tax, how much and how often is only what its laws say (no world rule taxes anyone).
- sign_petition(form): when more than half of the members signed for the same form, the polity takes it (open
  proposals lapse) and elects its council or ruler anew. So no form lasts unless the members keep it.
- Tax day (every `tax_every` days per polity): a member's bill is tax + income_tax% + wealth_tax%;
  laws.enforcement "auto" takes it (what they lack stays unpaid, said in public); "voluntary" writes a bill in
  the debt book owed to the polity's treasury, paid with pay_bill or left unpaid (public when overdue). Nobody
  outside a polity pays it; income from before joining is not taxed. give_to_polity is a gift.
- One physical coin: a polity's coin name is only what its members call the coins.
- The treasury holder (the ruler, the most voted councillor, or the member an assembly elects as treasurer) can
  polity_embezzle: coins leave unnoticed, the books still show them. polity_audit at the town hall, or a change of
  holder (`audit_on_handover`), makes the shortfall and who took it public. What follows is up to the members
  (a fine law, a petition, leaving).

Nothing here treats members or non-members, payers or non-payers differently beyond these rules.
With polities on the village-wide government is off (governance.polity_on / REPLACED).

State: `world.polities[id]` (dict, see `_found`); `coins` is the treasury (counted by invariants).
Log: public `polity_founded`, `polity_named`, `polity_form`, `polity_leaders`, `polity_joined`, `polity_left`,
`polity_law_proposed`, `polity_law_passed`, `polity_law_failed`, `polity_petition`, `polity_tax_bills`,
`polity_tax_short`, `polity_audit_clean`, `polity_embezzlement_found`; private `polity_vote`, `polity_tax`,
`polity_embezzle`. Spec: docs/specs/survival.md (Polity).
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from . import clock, construction, debts, governance, honors, ops, progress, theft
from .actions import _agent, _text
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, Debt, World

HALL = "town_hall"
FORMS = ("assembly", "council", "ruler")
TOPICS = ("name", "coin", "form", "leader")
TAX_LAWS = ("tax", "income_tax", "wealth_tax", "tax_every")  # numbers kept in p["laws"]
LAWS = TAX_LAWS + ("fine", "grant", "payout", "expel", "title")
ACTION_NAMES = ("join_polity", "leave_polity", "polity_vote", "polity_propose", "polity_vote_law", "sign_petition",
                "give_to_polity", "polity_embezzle", "polity_audit")
for _n in ACTION_NAMES:
    progress.DEFAULT_UNLOCKS.setdefault(f"action:{_n}", {"building": HALL})


def enabled(cfg: dict) -> bool:
    return governance.polity_on(cfg)


def _c(cfg: dict) -> dict:
    return cfg["polity"]


class _Purse:
    """A polity's treasury as a coin holder for ops.move_coins."""

    def __init__(self, p: dict) -> None:
        self.p = p

    @property
    def coins(self) -> int:
        return self.p["coins"]

    @coins.setter
    def coins(self, v: int) -> None:
        self.p["coins"] = v


# ---------- queries ----------

def title(p: dict) -> str:
    return p["name"] or p["id"]


def coin_name(p: dict) -> str:
    return p["coin"] or "coins"


def of(world: World, name: str) -> dict | None:
    """The polity `name` belongs to, if any."""
    return next((p for p in world.polities.values() if name in p["members"]), None)


def find(ctx: Ctx, key: str) -> dict:
    k = key.strip().lower()
    for p in ctx.world.polities.values():
        if k in (p["id"].lower(), (p["name"] or "").lower()):
            return p
    names = ", ".join(f"{title(p)} ({p['id']})" for p in ctx.world.polities.values())
    raise ActionError(f"there is no polity '{key}'; polities: {names or 'none'}")


def deciders(p: dict) -> list[str]:
    """Who votes on laws: every member (assembly) or the council / the ruler. Nobody before a form is chosen."""
    if p["form"] == "assembly":
        return list(p["members"])
    return list(p["rulers"]) if p["form"] else []


def form_text(cfg: dict, form: str) -> str:
    return {"assembly": "every member votes on each law; a law passes with yes from more than half of the members; "
                        "the member most voted as leader holds the treasury",
            "council": f"the members elect a council of {_c(cfg)['council_size']}; a law passes with yes from more "
                       "than half of the council; the most voted councillor holds the treasury",
            "ruler": "the members elect one ruler; a law the ruler proposes passes at once; the ruler holds the "
                     "treasury"}[form]


def _needs_leaders(p: dict) -> bool:
    """Every form elects someone: the ruler, the council, or (assembly) the member who holds the treasury."""
    return p["form"] is not None


def seat(p: dict) -> str:
    return {"council": "council", "ruler": "ruler"}.get(p["form"], "treasurer")


def embezzle_on(cfg: dict) -> bool:
    return bool(_c(cfg).get("embezzle"))


def books(p: dict) -> int:
    """What the polity's books say is in its treasury: real coins plus what its holder took unnoticed."""
    return p["coins"] + p.get("hidden", 0)


def _member(ctx: Ctx, a: Agent) -> dict:
    p = of(ctx.world, a.name)
    if p is None:
        raise ActionError("you are not a member of any polity (join_polity)")
    return p


def _payee(world: World, d: Debt) -> _Purse | None:
    """debts.BILL_PAYEES: a polity's tax or fine bill is paid into that polity's treasury."""
    p = next((p for p in world.polities.values() if d.id in p["bills"]), None)
    return _Purse(p) if p is not None else None


debts.BILL_PAYEES.append(_payee)


def _say_time(cfg: dict, tick: int) -> str:
    return clock.label(cfg, tick)


# ---------- founding and membership ----------

def halls(world: World) -> list[dict]:
    """Town halls that stand: built ones (construction.py) and those a later start stage counts as standing
    (progress `prebuilt`, at the square, built by nobody)."""
    out = [b for b in construction.common(world) if b["kind"] == HALL]
    square = "square" if "square" in world.locations else next(iter(world.locations))
    pre = int(((world.progress or {}).get("prebuilt") or {}).get(HALL, 0))
    return out + [{"id": f"prebuilt_hall{i + 1}", "location": square, "builders": []} for i in range(pre)]


def _found(ctx: Ctx, hall: dict) -> dict:
    w, cfg = ctx.world, ctx.cfg
    options = list(FORMS)
    ctx.rng.shuffle(options)
    members = [n for n in hall.get("builders", []) if n in w.agents and w.agents[n].status != "dead"
               and of(w, n) is None]
    p = {"id": w.new_id("polity"), "hall": hall["id"], "location": hall["location"], "founded_day": w.day,
         "name": None, "coin": None, "members": members, "form": None, "rulers": [], "keeper": None, "coins": 0,
         "hidden": 0, "embezzled": {},
         "laws": {"tax": 0}, "options": options, "ballot": {t: {} for t in TOPICS},
         "closes": w.tick + clock.hours(cfg, _c(cfg)["vote_hours"]), "proposals": {}, "petition": {},
         "expelled": {}, "bills": []}
    w.polities[p["id"]] = p
    for n in members:  # income from before the polity is not its to tax
        w.agents[n].earned_since_tax = 0
    where = w.locations[hall["location"]].name if hall["location"] in w.locations else hall["location"]
    ctx.emit("polity_founded", f"The town hall at {where} founds a polity ({p['id']}). Members: "
             f"{', '.join(members) or 'nobody yet (join_polity)'}. Members vote with polity_vote on its name, the name "
             f"of its coins, its form of government ({', '.join(options)}) and who leads it, until "
             f"{_say_time(cfg, p['closes'])}.", location=hall["location"], visibility="public", polity=p["id"],
             members=members, options=options)
    return p


def _drop(ctx: Ctx, p: dict, name: str) -> None:
    """`name` is no longer a member: out of the council, the ballots, the petition and open proposals."""
    p["members"].remove(name)
    for votes in p["ballot"].values():
        votes.pop(name, None)
    leader = p["ballot"].get("leader", {})
    for voter in [v for v, c in leader.items() if c == name]:  # votes for them as leader lapse
        del leader[voter]
    p["petition"].pop(name, None)
    for pr in p["proposals"].values():
        for side in (pr["yes"], pr["no"]):
            if name in side:
                side.remove(name)
    keeper = p.get("keeper") == name
    if keeper:
        handover(ctx, p, name)
        p["keeper"] = None
    if name in p["rulers"]:
        p["rulers"].remove(name)
    if _needs_leaders(p) and (keeper or (p["form"] != "assembly" and not p["rulers"])):
        p["rulers"] = []  # the whole seat is elected again
        _open_leaders(ctx, p, f"{name} left")


def _open_leaders(ctx: Ctx, p: dict, why: str) -> None:
    w, cfg = ctx.world, ctx.cfg
    p["ballot"]["leader"] = {}
    p["closes"] = w.tick + clock.hours(cfg, _c(cfg)["vote_hours"])
    ctx.emit("polity_leaders", f"{title(p)} has no {seat(p)} ({why}). Members elect a {seat(p)} with polity_vote "
             f"(topic leader) until {_say_time(cfg, p['closes'])}.", visibility="public", polity=p["id"], rulers=[],
             keeper=None)


class JoinArgs(BaseModel):
    polity: str = Field(description="polity id or name")


@ACTIONS.action("join_polity", "Become a member of a polity (from anywhere). You leave the polity you were in.",
                JoinArgs, available=lambda c, a: enabled(c.cfg) and any(a.name not in p["members"]
                                                                     for p in c.world.polities.values()))
def join_polity(ctx: Ctx, a: Agent, args: JoinArgs) -> None:
    if not enabled(ctx.cfg):
        raise ActionError("there are no polities in this village")
    p = find(ctx, args.polity)
    if a.name in p["members"]:
        raise ActionError(f"you are already a member of {title(p)}")
    until = p["expelled"].get(a.name, 0)
    if ctx.world.day < until:
        raise ActionError(f"{title(p)} expelled you; you may join again on day {until}")
    old = of(ctx.world, a.name)
    if old is not None:
        _drop(ctx, old, a.name)
        ctx.emit("polity_left", f"{a.name} leaves {title(old)} ({len(old['members'])} members now).", actor=a.name,
                 visibility="public", polity=old["id"])
    p["members"].append(a.name)
    a.earned_since_tax = 0  # income from before joining is not this polity's to tax
    ctx.emit("polity_joined", f"{a.name} joins {title(p)} ({len(p['members'])} members now).", actor=a.name,
             visibility="public", polity=p["id"])


@ACTIONS.action("leave_polity", "Stop being a member of your polity (from anywhere). Bills you owe stay in the "
                "debt book.", available=lambda c, a: enabled(c.cfg) and of(c.world, a.name) is not None)
def leave_polity(ctx: Ctx, a: Agent, args) -> None:
    p = _member(ctx, a)
    _drop(ctx, p, a.name)
    ctx.emit("polity_left", f"{a.name} leaves {title(p)} ({len(p['members'])} members now).", actor=a.name,
             visibility="public", polity=p["id"])


# ---------- the founding ballot and leader elections ----------

class PolityVoteArgs(BaseModel):
    topic: Literal["name", "coin", "form", "leader"]
    choice: str = Field(description="a name (name/coin), one of the forms (form), a member (leader)")


@ACTIONS.action("polity_vote", "In your polity's open ballot, vote on its name, the name of its coins, its form "
                "of government or who leads it (topic leader: a member; the ruler, the council (the most voted) or "
                "an assembly's treasurer). You can "
                "change your vote until the ballot closes.", PolityVoteArgs,
                available=lambda c, a: enabled(c.cfg) and bool((of(c.world, a.name) or {}).get("ballot")))
def polity_vote(ctx: Ctx, a: Agent, args: PolityVoteArgs) -> None:
    p = _member(ctx, a)
    if args.topic not in p["ballot"]:
        open_ = ", ".join(p["ballot"]) or "none"
        raise ActionError(f"{title(p)} has no open vote on {args.topic}; open: {open_}")
    if args.topic in ("name", "coin"):
        choice = _text(ctx, args.choice)[: _c(ctx.cfg)["max_name_len"]]
    elif args.topic == "form":
        choice = args.choice.strip().lower()
        if choice not in FORMS:
            raise ActionError(f"form is one of: {', '.join(p['options'])}")
    else:
        choice = _agent(ctx, args.choice).name
        if choice not in p["members"]:
            raise ActionError(f"{choice} is not a member of {title(p)}")
    p["ballot"][args.topic][a.name] = choice
    ctx.emit("polity_vote", f"You voted {choice} for the {args.topic} of {title(p)}.", actor=a.name, to=[a.name],
             polity=p["id"], topic=args.topic)


def _winner(ctx: Ctx, votes: dict[str, str], valid=lambda c: True) -> tuple[str | None, Counter]:
    counts = Counter(c for c in votes.values() if valid(c))
    if not counts:
        return None, counts
    top = max(counts.values())
    return ctx.rng.choice(sorted(c for c, n in counts.items() if n == top)), counts


def _tally(counts: Counter) -> str:
    return ", ".join(f"{c} {n}" for c, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])))


def _close_ballot(ctx: Ctx, p: dict) -> None:
    """Close the questions that got votes; the rest stay open for another `vote_hours`."""
    w, cfg = ctx.world, ctx.cfg
    b = p["ballot"]
    for topic in ("name", "coin"):
        if topic in b:
            win, counts = _winner(ctx, {v: c for v, c in b[topic].items() if v in p["members"]})
            if win:
                del b[topic]
                p[topic] = win
                what = "is named" if topic == "name" else "calls its coins"
                ctx.emit("polity_named", f"Polity {p['id']} {what} {win} (votes: {_tally(counts)}).",
                         visibility="public", polity=p["id"], topic=topic, choice=win, votes=dict(counts))
    if "form" in b:
        win, counts = _winner(ctx, {v: c for v, c in b["form"].items() if v in p["members"]})
        if win:
            del b["form"]
            p["form"] = win
            ctx.emit("polity_form", f"{title(p)} chooses its form of government: {win} ({form_text(cfg, win)}; "
                     f"votes: {_tally(counts)}).", visibility="public", polity=p["id"], form=win,
                     votes=dict(counts))
    if "leader" in b and p["form"] is not None:
        _close_leaders(ctx, p)
    if b:
        p["closes"] = w.tick + clock.hours(cfg, _c(cfg)["vote_hours"])


def _close_leaders(ctx: Ctx, p: dict) -> None:
    votes = {v: c for v, c in p["ballot"]["leader"].items() if v in p["members"] and c in p["members"]}
    counts = Counter(votes.values())
    if not counts:
        return
    k = _c(ctx.cfg)["council_size"] if p["form"] == "council" else 1
    ranked = sorted(counts, key=lambda c: (-counts[c], c))
    cut = counts[ranked[min(k, len(ranked)) - 1]]
    sure = [c for c in ranked if counts[c] > cut]
    tied = sorted(c for c in ranked if counts[c] == cut)
    ctx.rng.shuffle(tied)
    chosen = sure + tied[: k - len(sure)]  # most voted first
    keeper, old = chosen[0], p.get("keeper")
    if old and old != keeper:
        handover(ctx, p, old)
    p["keeper"] = keeper
    p["rulers"] = sorted(chosen) if p["form"] != "assembly" else []
    del p["ballot"]["leader"]
    who = {"council": f"council: {', '.join(p['rulers'])} (the treasury is held by {keeper})",
           "ruler": f"ruler: {keeper}"}.get(p["form"], f"treasurer: {keeper}")
    ctx.emit("polity_leaders", f"{title(p)} elects its {who} (votes: {_tally(counts)}).", visibility="public",
             polity=p["id"], rulers=list(p["rulers"]), keeper=keeper, votes=dict(counts))


# ---------- petitions ----------

class PetitionArgs(BaseModel):
    form: Literal["assembly", "council", "ruler"]


@ACTIONS.action("sign_petition", "Sign a petition that your polity take this form of government (the same form "
                "elects its council or ruler anew). It happens when more than half of the members signed for it; "
                "signing again moves your signature.", PetitionArgs,
                available=lambda c, a: enabled(c.cfg) and bool((of(c.world, a.name) or {}).get("form")))
def sign_petition(ctx: Ctx, a: Agent, args: PetitionArgs) -> None:
    p = _member(ctx, a)
    if p["form"] is None:
        raise ActionError(f"{title(p)} has not chosen its form of government yet (polity_vote, topic form)")
    p["petition"][a.name] = args.form
    signed = sorted(n for n, f in p["petition"].items() if f == args.form)
    need = len(p["members"]) // 2 + 1
    if len(signed) < need:
        ctx.emit("polity_petition", f"{a.name} signs the petition that {title(p)} become a {args.form} "
                 f"({len(signed)} of {need} signatures needed: {', '.join(signed)}).", actor=a.name,
                 visibility="public", polity=p["id"], form=args.form, signed=signed, needed=need)
        return
    if p.get("keeper"):
        handover(ctx, p, p["keeper"])
    old, p["form"], p["rulers"], p["keeper"], p["petition"] = p["form"], args.form, [], None, {}
    lapsed = sorted(p["proposals"])
    p["proposals"] = {}
    p["ballot"].pop("leader", None)
    ctx.emit("polity_form", f"Petition signed by {len(signed)} of {len(p['members'])} members ({', '.join(signed)}): "
             f"{title(p)} is now a {args.form} ({form_text(ctx.cfg, args.form)}), it was a {old}."
             + (f" Open proposals lapse: {', '.join(lapsed)}." if lapsed else ""), actor=a.name,
             visibility="public", polity=p["id"], form=args.form, old_form=old, signed=signed)
    _open_leaders(ctx, p, "the form changed")


# ---------- the treasury holder: embezzlement and audits ----------

class EmbezzleArgs(BaseModel):
    coins: int = Field(gt=0, le=100000)


@ACTIONS.action("polity_embezzle", "Treasury holder only: quietly take coins from your polity's treasury for "
                "yourself. Its books still show them until someone runs polity_audit at its town hall or the "
                "treasury changes hands.", EmbezzleArgs,
                available=lambda c, a: enabled(c.cfg) and embezzle_on(c.cfg)
                and (of(c.world, a.name) or {}).get("keeper") == a.name and of(c.world, a.name)["coins"] > 0)
def polity_embezzle(ctx: Ctx, a: Agent, args: EmbezzleArgs) -> None:
    p = _member(ctx, a)
    if not embezzle_on(ctx.cfg):
        raise ActionError("the treasury cannot be touched in this village")
    if p.get("keeper") != a.name:
        raise ActionError(f"{p.get('keeper') or 'nobody yet'} holds the treasury of {title(p)}")
    n = min(args.coins, p["coins"])
    if n <= 0:
        raise ActionError("the treasury is empty")
    ops.move_coins(_Purse(p), a, n)
    p["hidden"] = p.get("hidden", 0) + n
    p.setdefault("embezzled", {})[a.name] = p["embezzled"].get(a.name, 0) + n
    ctx.emit("polity_embezzle", f"You quietly took {n} {coin_name(p)} from the treasury of {title(p)}. The books "
             f"still show {books(p)}; {p['coins']} are really there.", actor=a.name, to=[a.name], polity=p["id"],
             coins=n)


def _here(world: World, a: Agent) -> dict | None:
    return next((p for p in world.polities.values() if p["location"] == a.location), None)


@ACTIONS.action("polity_audit", "Count the treasury of the polity whose town hall is here against its books; any "
                "missing coins and who took them become public.",
                available=lambda c, a: enabled(c.cfg) and embezzle_on(c.cfg) and _here(c.world, a) is not None)
def polity_audit(ctx: Ctx, a: Agent, args) -> None:
    p = _here(ctx.world, a)
    if p is None:
        raise ActionError("there is no polity's town hall here")
    audit(ctx, p, f"{a.name} counted the treasury of {title(p)}", actor=a.name)


def audit(ctx: Ctx, p: dict, who: str, actor: str | None = None) -> None:
    """Compare the treasury with the books; missing coins and the holders who took them become public."""
    if not p.get("hidden"):
        ctx.emit("polity_audit_clean", f"{who}: the books are in order, the treasury holds {p['coins']} "
                 f"{coin_name(p)}.", actor=actor, visibility="public", polity=p["id"], coins=p["coins"])
        return
    for name, n in sorted(p["embezzled"].items()):
        if name == theft.UNKNOWN:  # theft.py: a thief, not the holder, took these
            ctx.emit("polity_embezzlement_found", f"{who}: {n} {coin_name(p)} are missing from the treasury of "
                     f"{title(p)}; nobody knows who took them. The books now show {p['coins']}.",
                     actor=actor, visibility="public", polity=p["id"], coins=n)
            continue
        ctx.emit("polity_embezzlement_found", f"{who}: {n} {coin_name(p)} are missing from the treasury of "
                 f"{title(p)}. They were taken by {name} while holding it. The books now show {p['coins']}.",
                 actor=actor, visibility="public", polity=p["id"], keeper=name, coins=n)
    p["hidden"], p["embezzled"] = 0, {}


def handover(ctx: Ctx, p: dict, old: str) -> None:
    """The treasury changes hands: it is counted in public (config polity.audit_on_handover), if anything is missing."""
    if _c(ctx.cfg).get("audit_on_handover") and p.get("hidden"):
        audit(ctx, p, f"The treasury of {title(p)} was counted when {old} stopped holding it")


# ---------- laws ----------

class ProposeArgs(BaseModel):
    law: Literal["tax", "income_tax", "wealth_tax", "tax_every", "fine", "grant", "payout", "expel", "title"]
    value: int | None = Field(None, description="tax: coins per member each tax day; income_tax, wealth_tax: "
                                                "percent; tax_every: days; fine, grant: coins")
    person: str | None = Field(None, description="a member, for fine/grant/expel/title")
    text: str | None = Field(None, description="for title: the title's words")


def _describe(p: dict, pr: dict) -> str:
    coin = coin_name(p)
    return {"tax": f"tax = {pr['value']} {coin} per member every tax day",
            "income_tax": f"income tax = {pr['value']}% of the coins a member got from the trader and orders "
                          "since the last tax day",
            "wealth_tax": f"wealth tax = {pr['value']}% of a member's coins on tax day",
            "tax_every": f"tax day every {pr['value']} days",
            "fine": f"fine {pr['person']} {pr['value']} {coin}",
            "grant": f"grant {pr['value']} {coin} from the treasury to {pr['person']}",
            "payout": "split the treasury equally among the members",
            "expel": f"expel {pr['person']}",
            "title": f"give {pr['person']} the title \"{pr.get('text')}\""}[pr["law"]]


@ACTIONS.action("polity_propose", "Put a law to your polity, the way its form of government says (assembly: any "
                "member proposes, all members vote; council: a council member proposes, the council votes; ruler: "
                "the ruler's law passes at once). tax/fine/grant need value (coins), income_tax/wealth_tax value "
                "(percent), tax_every value (days); 0 for a tax law means no such tax; fine/grant/expel need person "
                "(a member); payout splits the treasury among the members; title needs person (a member) and text (a "
                "title on the honor board, where World facts list it).", ProposeArgs,
                available=lambda c, a: enabled(c.cfg) and a.name in deciders(of(c.world, a.name) or
                                                                             {"form": None, "members": []}))
def polity_propose(ctx: Ctx, a: Agent, args: ProposeArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    c = _c(cfg)
    p = _member(ctx, a)
    if p["form"] is None:
        raise ActionError(f"{title(p)} has not chosen its form of government yet (polity_vote, topic form)")
    if a.name not in deciders(p):
        who = "the council" if p["form"] == "council" else "the ruler"
        raise ActionError(f"in {title(p)} only {who} ({', '.join(p['rulers']) or 'not elected yet'}) proposes laws")
    if len(p["proposals"]) >= c["max_open_proposals"]:
        raise ActionError(f"at most {c['max_open_proposals']} proposals can be open at once")
    value = person = None
    text = honors.check_title(ctx, args.text) if args.law == "title" else None
    if args.law in ("tax", "income_tax", "wealth_tax", "tax_every", "fine", "grant"):
        lo, hi = c["limits"][args.law]
        if args.value is None or not lo <= args.value <= hi:
            raise ActionError(f"{args.law} needs value between {lo} and {hi}")
        value = args.value
    if args.law in ("fine", "grant", "expel", "title"):
        if not args.person:
            raise ActionError(f"{args.law} needs person")
        person = _agent(ctx, args.person).name
        if person not in p["members"]:
            raise ActionError(f"{person} is not a member of {title(p)}")
    pr = {"id": w.new_id("plaw"), "law": args.law, "value": value, "person": person, "by": a.name,
          "closes": w.tick + clock.hours(cfg, c["law_vote_hours"]), "yes": [a.name], "no": []}
    if text is not None:
        pr["text"] = text
    p["proposals"][pr["id"]] = pr
    if p["form"] != "ruler":
        ctx.emit("polity_law_proposed", f"{a.name} proposes a law in {title(p)} ({pr['id']}): {_describe(p, pr)}. "
                 f"{'Members' if p['form'] == 'assembly' else 'The council'} vote with polity_vote_law until "
                 f"{_say_time(cfg, pr['closes'])}.", actor=a.name, visibility="public", polity=p["id"], law=pr["id"])
    _maybe_resolve(ctx, p, pr)


class VoteLawArgs(BaseModel):
    proposal_id: str
    vote: Literal["yes", "no"]


@ACTIONS.action("polity_vote_law", "Vote yes or no on a law proposed in your polity, if your polity's form lets "
                "you vote on laws. Works from anywhere.", VoteLawArgs,
                available=lambda c, a: enabled(c.cfg) and bool((of(c.world, a.name) or {}).get("proposals"))
                and a.name in deciders(of(c.world, a.name)))
def polity_vote_law(ctx: Ctx, a: Agent, args: VoteLawArgs) -> None:
    p = _member(ctx, a)
    pr = p["proposals"].get(args.proposal_id.strip())
    if pr is None:
        raise ActionError(f"no open proposal '{args.proposal_id}' in {title(p)}")
    if a.name not in deciders(p):
        raise ActionError(f"in {title(p)} the {'council' if p['form'] == 'council' else 'ruler'} votes on laws")
    for side in (pr["yes"], pr["no"]):
        if a.name in side:
            side.remove(a.name)
    (pr["yes"] if args.vote == "yes" else pr["no"]).append(a.name)
    ctx.emit("polity_vote", f"You voted {args.vote} on {pr['id']} ({_describe(p, pr)}).", actor=a.name, to=[a.name],
             polity=p["id"], law=pr["id"], vote=args.vote)
    _maybe_resolve(ctx, p, pr)


def _maybe_resolve(ctx: Ctx, p: dict, pr: dict, closing: bool = False) -> None:
    who = set(deciders(p))
    yes, no = len(set(pr["yes"]) & who), len(set(pr["no"]) & who)
    passed = bool(who) and yes * 2 > len(who)
    if not (passed or closing or no * 2 >= len(who) or yes + no >= len(who)):
        return
    del p["proposals"][pr["id"]]
    tally = f"(yes {yes}, no {no} of {len(who)})"
    if not passed:
        ctx.emit("polity_law_failed", f"Law {pr['id']} of {title(p)} failed: {_describe(p, pr)} {tally}.",
                 visibility="public", polity=p["id"], law=pr["id"])
        return
    how = f"decided by ruler {pr['by']}" if p["form"] == "ruler" else tally
    extra = _apply(ctx, p, pr)
    ctx.emit("polity_law_passed", f"Law {pr['id']} of {title(p)} passed: {_describe(p, pr)} ({how}).{extra}",
             visibility="public", polity=p["id"], law=pr["id"], law_kind=pr["law"], value=pr["value"],
             person=pr["person"], form=p["form"])


def _apply(ctx: Ctx, p: dict, pr: dict) -> str:
    w, purse = ctx.world, _Purse(p)
    target = w.agents.get(pr["person"]) if pr["person"] else None
    if pr["law"] in TAX_LAWS:
        p["laws"][pr["law"]] = pr["value"]
        return ""
    if pr["law"] != "payout" and (target is None or target.status == "dead" or target.name not in p["members"]):
        return f" {pr['person']} is not a member any more; nothing happens."
    if pr["law"] == "title":
        return honors.give_title(ctx, target.name, pr["text"], title(p))
    if pr["law"] == "fine":
        return " " + _charge(ctx, p, target, pr["value"], "fine")
    if pr["law"] == "grant":
        n = min(pr["value"], p["coins"])
        ops.move_coins(purse, target, n)
        return f" {target.name} received {n} {coin_name(p)}."
    if pr["law"] == "expel":
        _drop(ctx, p, target.name)
        until = w.day + _c(ctx.cfg)["expel_days"]
        p["expelled"][target.name] = until
        return f" {target.name} is no longer a member and may not join again before day {until}."
    names = sorted(n for n in p["members"] if w.agents[n].status != "dead")  # payout
    share = p["coins"] // len(names) if names else 0
    for n in names:
        ops.move_coins(purse, w.agents[n], share)
    return f" Each of {len(names)} members received {share} {coin_name(p)}."


def _charge(ctx: Ctx, p: dict, a: Agent, n: int, kind: str) -> str:
    """`a` owes `n` to the polity: taken now (laws auto) or written as a bill (laws voluntary). Returns a text."""
    if governance.voluntary(ctx.cfg):
        d = debts.write_bill(ctx, a.name, n, kind, note=f"{title(p)} ({p['id']}) {kind}, day {ctx.world.day}")
        p["bills"].append(d.id)
        return f"{a.name} owes {title(p)} {n} {coin_name(p)} (bill {d.id}, due day {d.due_day})."
    paid = min(n, a.coins)
    if paid:
        ops.move_coins(a, _Purse(p), paid)
    return f"{a.name} paid {paid} of {n} {coin_name(p)} to {title(p)}." + (
        f" {n - paid} stay unpaid." if paid < n else "")


class GiveArgs(BaseModel):
    coins: int = Field(gt=0, le=100000)
    polity: str | None = Field(None, description="polity id or name; default your own")


@ACTIONS.action("give_to_polity", "Give coins to a polity's treasury (from anywhere).", GiveArgs,
                available=lambda c, a: enabled(c.cfg) and bool(c.world.polities) and a.coins > 0)
def give_to_polity(ctx: Ctx, a: Agent, args: GiveArgs) -> None:
    p = find(ctx, args.polity) if args.polity else _member(ctx, a)
    if a.coins < args.coins:
        raise ActionError(f"you only have {a.coins} coins")
    ops.move_coins(a, _Purse(p), args.coins)
    ctx.emit("polity_gift", f"{a.name} gives {args.coins} {coin_name(p)} to the treasury of {title(p)} "
             f"(it holds {p['coins']}).", actor=a.name, visibility="public", polity=p["id"], coins=args.coins)


# ---------- engine hooks ----------

def end_of_hour(ctx: Ctx) -> None:
    """Found polities at new town halls, forget dead members, close ballots and law votes."""
    if not enabled(ctx.cfg):
        return
    w = ctx.world
    have = {p["hall"] for p in w.polities.values()}
    for b in halls(w):
        if b["id"] not in have:
            _found(ctx, b)
    for pid in sorted(w.polities):
        p = w.polities[pid]
        for n in [n for n in p["members"] if w.agents[n].status == "dead"]:
            _drop(ctx, p, n)
        if p["ballot"] and w.tick + 1 >= p["closes"]:
            _close_ballot(ctx, p)
        for pr in sorted(p["proposals"].values(), key=lambda x: x["id"]):
            _maybe_resolve(ctx, p, pr, closing=w.tick + 1 >= pr["closes"])


def every(cfg: dict, p: dict) -> int:
    """Days between the polity's tax days: its tax_every law, else the village's `tax_every_days`."""
    return int(p["laws"].get("tax_every") or cfg["tax_every_days"])


def next_tax_day(world: World, p: dict) -> int:
    n = every(world.config, p)
    return ((world.day - 1) // n + 1) * n + 1


def bill(world: World, p: dict, a: Agent) -> dict:
    """What member `a` owes `p` on its next tax day if nothing changes until then: the flat tax, income_tax% of
    what they got from the trader and orders since the last tax day, wealth_tax% of the coins they hold."""
    laws = p["laws"]
    out = {"per_member": laws.get("tax", 0),
           "income": a.earned_since_tax * laws.get("income_tax", 0) // 100,
           "wealth": a.coins * laws.get("wealth_tax", 0) // 100}
    return {"total": sum(out.values()), **{k: v for k, v in out.items() if v}}


def _parts(b: dict) -> str:
    parts = [f"{k.replace('_', ' ')} {v}" for k, v in b.items() if k != "total"]
    return f" ({', '.join(parts)})" if len(parts) > 1 else ""


def set_laws(ctx: Ctx, p: dict, laws: dict[str, int]) -> None:
    """Tax laws set from outside the polity's own vote (god mode): public, like any law in force."""
    p["laws"].update(laws)
    said = "; ".join(_describe(p, {"law": k, "value": v, "person": None}) for k, v in laws.items())
    ctx.emit("polity_tax_set", f"The tax law of {title(p)} is now: {said}.", visibility="public", polity=p["id"],
             laws=dict(laws))


def after_night(ctx: Ctx) -> None:
    """Tax day of each polity (its own tax_every): members pay their bill, or get it in the debt book (laws
    voluntary). The base of the income tax starts again from zero for every member."""
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        return
    for pid in sorted(w.polities):
        p = w.polities[pid]
        if (w.day - 1) % every(cfg, p) != 0:
            continue
        names = sorted(n for n in p["members"] if w.agents[n].status != "dead")
        bills = {n: bill(w, p, w.agents[n]) for n in names}
        for n in names:
            w.agents[n].earned_since_tax = 0
        bills = {n: b for n, b in bills.items() if b["total"] > 0}
        if not bills:
            continue
        if governance.voluntary(cfg):
            rows = []
            for n, b in bills.items():
                d = debts.write_bill(ctx, n, b["total"], "tax", note=f"{title(p)} ({pid}) tax, day {w.day}"
                                     + _parts(b))
                p["bills"].append(d.id)
                rows.append(f"{n} {b['total']} ({d.id})")
            due = w.day + max(1, int((cfg.get("laws") or {}).get("bill_days", 3))) - 1
            ctx.emit("polity_tax_bills", f"Tax day in {title(p)}: bills in {coin_name(p)} to its treasury are "
                     f"written in the debt book, due by day {due}: {', '.join(rows)}.", visibility="public",
                     polity=pid, bills={n: b["total"] for n, b in bills.items()}, due_day=due)
            continue
        short = []
        for n, b in bills.items():
            a, tax = w.agents[n], b["total"]
            paid = min(tax, a.coins)
            if paid:
                ops.move_coins(a, _Purse(p), paid)
            ctx.emit("polity_tax", f"You paid {paid} of {tax} {coin_name(p)} of tax to {title(p)}{_parts(b)}.",
                     to=[n], polity=pid, paid=paid, tax=tax)
            if paid < tax:
                short.append(f"{n} {tax - paid}")
        if short:
            ctx.emit("polity_tax_short", f"Tax day in {title(p)}: unpaid for lack of coins: {', '.join(short)}.",
                     visibility="public", polity=pid)


def observe(world: World, name: str) -> dict:
    cfg = world.config
    if not enabled(cfg) or not progress.unlocked(world, f"action:{ACTION_NAMES[0]}"):
        return {}
    out = []
    for p in world.polities.values():
        row = {"id": p["id"], "name": p["name"], "coin_name": p["coin"], "town_hall_at": p["location"],
               "members": list(p["members"]), "form": p["form"],
               # only the holder sees what is really in the treasury; everyone else sees the books
               "treasury": p["coins"] if p.get("keeper") == name else books(p), "treasury_held_by": p.get("keeper"),
               "tax_per_member": p["laws"].get("tax", 0), "tax_every_days": every(cfg, p),
               "next_tax_day": next_tax_day(world, p)}
        for law in ("income_tax", "wealth_tax"):
            if p["laws"].get(law):
                row[f"{law}_pct"] = p["laws"][law]
        if p["form"] == "council":
            row["council"] = list(p["rulers"])
        elif p["form"] == "ruler":
            row["ruler"] = p["rulers"][0] if p["rulers"] else None
        if p.get("keeper") == name and embezzle_on(cfg):
            row["treasury_books"], row["you_took_unnoticed"] = books(p), p["embezzled"].get(name, 0)
        if name in p["members"]:
            row["you_are_member"] = True
            if any(p["laws"].get(k) for k in ("tax", "income_tax", "wealth_tax")):
                row["your_tax_so_far"] = bill(world, p, world.agents[name])
            if p["ballot"]:
                ballot = {t: {"votes": dict(Counter(v.values())), "your_vote": v.get(name)}
                          for t, v in p["ballot"].items()}
                if "form" in ballot:
                    ballot["form"]["options"] = {f: form_text(cfg, f) for f in p["options"]}
                row["open_ballot"] = {"closes": _say_time(cfg, p["closes"]), **ballot}
            if p["proposals"]:
                row["proposals"] = [{"id": pr["id"], "law": _describe(p, pr), "by": pr["by"],
                                     "closes": _say_time(cfg, pr["closes"]), "yes": list(pr["yes"]),
                                     "no": list(pr["no"])} for pr in p["proposals"].values()]
            if p["petition"]:
                row["petition"] = {f: sorted((n for n, x in p["petition"].items() if x == f), key=ops.name_key(world))
                                   for f in sorted(set(p["petition"].values()))}
            if p["form"]:
                row["votes_on_laws"] = deciders(p)
                row["signatures_to_change_form"] = len(p["members"]) // 2 + 1
        out.append(row)
    res = {"polities": out} if out else {}
    # the village-wide government's actions are off: keep them out of the handbook too (llm.LLMAgent)
    res["locked_actions"] = sorted(set(progress.locked_actions(world)) | set(governance.REPLACED))
    return res


def facts(cfg: dict) -> str:
    c = _c(cfg)
    how = ("their tax is a bill in the debt book (pay_bill, or left unpaid)" if governance.voluntary(cfg)
           else "their tax is taken (what they lack stays unpaid)")
    return (f"- Polities{governance.opens_note(cfg, 'action:join_polity')}: every finished town_hall (any common "
            "place) founds a polity; its builders are its first members, anyone can join_polity (one polity at a "
            "time) or leave_polity. There is no village-wide mayor or law. Members vote (polity_vote) on the "
            f"polity's name, its coin name (the coins are the same everywhere), its form of government and who "
            f"leads it; the ballot closes after {c['vote_hours']} hours. Forms: assembly ({form_text(cfg, 'assembly')}); "
            f"council ({form_text(cfg, 'council')}); ruler ({form_text(cfg, 'ruler')}). More than half of the "
            "members can change the form with sign_petition. Laws: tax (coins per member every tax day), income_tax "
            "(percent of the coins a member got from the trader and orders since the last tax day), wealth_tax "
            "(percent of a member's coins on tax day), tax_every (days between tax days, "
            f"{cfg['tax_every_days']} until a law sets it), fine, grant, payout, expel (no rejoining for {c['expel_days']} days)" + (", title" if honors.enabled(cfg) else "")
            + ". A new polity has no tax until a law sets one. On tax day members pay their own polity "
            f"only; {how}. Non-members pay no polity tax, and income from before joining is not taxed."
            + (" The treasury holder can polity_embezzle (take coins unnoticed: the books still show them); anyone at "
               "a polity's town hall can polity_audit it, and it is counted whenever the holder changes; then the "
               "missing coins and who took them become public." if embezzle_on(cfg) else ""))
