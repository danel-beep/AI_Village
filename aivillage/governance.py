"""Village government: mayor elections, laws voted by villagers, a treasury.

Rules, in the order an agent meets them:
- Every `election_every_days` (from `first_election_day`) there is an election. Anyone can
  `run_for_mayor` before it; on election day everyone can `vote` for a candidate (secret ballot,
  re-voting overwrites). Results are counted at night; ties are broken by the world rng.
- The mayor `propose_law`s. Every villager can `vote_law` yes/no from anywhere. A law passes when
  more than half of all active, non-exiled villagers vote yes; it fails when that can no longer
  happen or when voting closes after `law_vote_hours`.
- Laws: tax (weekly, paid into the treasury), theft_fine, mayor_salary (daily from the treasury),
  exile (person loses market, orders and votes for `exile_days`), payout (treasury split equally),
  grant (coins from the treasury to one person).
- Witnesses and awake victims of a theft can `report_theft`: the thief pays the theft_fine.
- With village stages on (progress.py, the «С нуля» mode) there is no government until a town hall stands
  (`feature:elections`): no election days, announcements or mayor salary, and the observation says so.
- With polities on (config `polity.enabled`, polity.py) there is no village-wide government at all: the mayor's
  actions are refused and hidden (`REPLACED`), no elections are held, report_theft carries no village fine.
  Each polity makes its own laws. The hooks below (`polity_on`, `_polity_guard`) are all this module knows of it.

State lives in `world.governance`; the treasury is `world.governance.coins` (ledger-safe moves only).
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from . import clock, honors, ops, progress, theft
from .actions import _agent, _text
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, LawProposal, World

NUMBER_LAWS = ("tax", "theft_fine", "mayor_salary", "sales_tax", "wealth_tax")
TAX_RATES = ("sales_tax", "wealth_tax")  # percents; only with config taxes.enabled (taxes.py)
LAWS = NUMBER_LAWS + ("exile", "revoke_place", "payout", "grant", "title")
ELECTIONS = "feature:elections"  # progress.DEFAULT_UNLOCKS: a town_hall
# The village-wide government's actions; with polities on each polity governs itself instead (polity.py).
REPLACED = ("run_for_mayor", "vote", "propose_law", "vote_law", "embezzle", "audit_treasury", "treasury_order")


def opens_when(cfg: dict, key: str) -> str:
    """"once a town_hall stands in the village" for a mechanic that village stages (progress.py) keep closed at
    first; "" with progress off or a key with no rule. From the config only, so prompt rules stay the same all run."""
    if not progress.enabled(cfg):
        return ""
    rule = progress.rules(cfg).get(key) or {}
    parts = []
    if rule.get("building"):
        parts.append(f"a {rule['building']} stands in the village")
    if rule.get("stage"):
        parts.append(f"the village is a {rule['stage']}")
    return f"once {' and '.join(parts)}" if parts else ""


def opens_note(cfg: dict, key: str) -> str:
    """opens_when in brackets, for a line of the rules: " (once a town_hall stands in the village)" or ""."""
    when = opens_when(cfg, key)
    return f" ({when})" if when else ""


# ---------- queries ----------

def enabled(cfg: dict) -> bool:
    return bool(cfg.get("governance", {}).get("enabled"))


def polity_on(cfg: dict) -> bool:
    """Config `polity.enabled`: town halls found polities that govern themselves (polity.py)."""
    return bool((cfg.get("polity") or {}).get("enabled"))


def voluntary(cfg: dict) -> bool:
    """Config `laws.enforcement`: "auto" (taxes and fines are taken) or "voluntary" (they become bills in the
    debt book that the villager pays with pay_bill, or not; debts.write_bill)."""
    return (cfg.get("laws") or {}).get("enforcement", "auto") == "voluntary"


def _g(cfg: dict) -> dict:
    return cfg["governance"]


def is_election_day(cfg: dict, day: int) -> bool:
    g = _g(cfg)
    return day >= g["first_election_day"] and (day - g["first_election_day"]) % g["election_every_days"] == 0


def next_election_day(cfg: dict, day: int) -> int:
    g = _g(cfg)
    first, every = g["first_election_day"], g["election_every_days"]
    if day <= first:
        return first
    return first + -(-(day - first) // every) * every


def law(world: World, name: str) -> int:
    """Value of a number law in force (falls back to the config)."""
    cfg = world.config
    if name in world.governance.laws:
        return world.governance.laws[name]
    if name == "tax":
        return cfg["tax_amount"]
    if name == "theft_fine" and polity_on(cfg):  # no village-wide fine: polities fine their own members
        return 0
    if name in TAX_RATES:
        t = cfg.get("taxes") or {}
        return t.get("sales_pct" if name == "sales_tax" else "wealth_pct", 0) if t.get("enabled") else 0
    return _g(cfg)["start"].get(name, 0) if enabled(cfg) else 0


def _rates_on(cfg: dict) -> bool:
    return bool((cfg.get("taxes") or {}).get("enabled"))


def tax_amount(world: World) -> int:
    return law(world, "tax") if enabled(world.config) else world.config["tax_amount"]


def pay_tax(world: World, a: Agent, n: int) -> None:
    """Tax goes to the treasury when there is a government, otherwise to nobody (burned)."""
    if enabled(world.config):
        ops.move_coins(a, world.governance, n)
    else:
        ops.burn_coins(world, a, n)


def is_exiled(world: World, name: str) -> bool:
    return world.day < world.governance.exiled.get(name, 0)


def voters(world: World) -> list[str]:
    return sorted(a.name for a in world.agents.values() if a.status == "active" and not is_exiled(world, a.name))


def treasury_cfg(cfg: dict) -> dict:
    return cfg.get("treasury") or {}


def books(world: World) -> int:
    """What the official books say is in the treasury: real coins plus what was taken unnoticed."""
    return world.governance.coins + world.governance.hidden


def tick_time(cfg: dict, tick: int) -> str:
    return clock.label(cfg, tick)


def describe_law(p: LawProposal) -> str:
    if p.law in NUMBER_LAWS:
        unit = {"tax": "coins per villager every tax day", "theft_fine": "coins per reported theft",
                "mayor_salary": "coins per day for the mayor",
                "sales_tax": "percent of coins got from the trader and council orders",
                "wealth_tax": "percent of coins above the threshold, every tax day"}[p.law]
        return f"{p.law} = {p.value} {unit}"
    if p.law == "exile":
        return f"exile {p.person}"
    if p.law == "revoke_place":
        return f"take {p.person}'s trade place"
    if p.law == "grant":
        return f"grant {p.value} coins from the treasury to {p.person}"
    if p.law == "title":
        return f"give {p.person} the title \"{p.text}\""
    return "pay out the treasury equally to all villagers"


def observe(world: World, name: str) -> dict:
    g, cfg = world.governance, world.config
    if not progress.unlocked(world, ELECTIONS):
        return {"mayor": None, "not_yet": "a mayor, elections, laws and a treasury start "
                + (opens_when(cfg, ELECTIONS) or "later")}
    if polity_on(cfg):
        return {"mayor": None, "village_government": "none: each polity (see polities) makes its own laws",
                "thefts_you_can_report": [{"thief": c["thief"], "victim": c["victim"], "day": c["day"]}
                                          for c in g.crimes if name in c["known_by"]]}
    return {
        "mayor": g.mayor, "you_are_mayor": g.mayor == name,
        # Only the mayor holds the treasury and sees what is really in it; everyone else sees the books.
        "treasury": g.coins if g.mayor == name else books(world),
        **({"treasury_books": books(world), "you_took_unnoticed": g.embezzled.get(name, 0)}
           if g.mayor == name and treasury_cfg(cfg).get("embezzle") else {}),
        "laws": {k: law(world, k) for k in NUMBER_LAWS if k not in TAX_RATES or _rates_on(cfg)},
        "next_election_day": next_election_day(cfg, world.day),
        "election_today": is_election_day(cfg, world.day),
        "candidates": dict(g.candidates), "your_vote": g.votes.get(name),
        "proposals": [{"id": p.id, "law": describe_law(p), "by": p.proposer,
                       "closes": tick_time(cfg, p.closes_tick), "yes": list(p.yes), "no": list(p.no),
                       "your_vote": "yes" if name in p.yes else "no" if name in p.no else None}
                      for p in g.proposals.values()],
        "votes_needed_to_pass": len(voters(world)) // 2 + 1,
        "exiled": {n: d for n, d in g.exiled.items() if world.day < d},
        "thefts_you_can_report": [{"thief": c["thief"], "victim": c["victim"], "day": c["day"]}
                                  for c in g.crimes if name in c["known_by"]],
    }


def facts(cfg: dict) -> str:
    """One line for the model's rules cheat sheet."""
    g = _g(cfg)
    if polity_on(cfg):
        from . import polity  # polity imports this module
        return (polity.facts(cfg) + "\n- Witnesses and victims of a theft, attack or arson can report_theft"
                + opens_note(cfg, ELECTIONS) + ": everyone learns who did it.")
    return (f"- Government{opens_note(cfg, ELECTIONS)}: every {g['election_every_days']} days from day {g['first_election_day']} villagers elect a "
            "mayor (run_for_mayor any time, vote on election day; ballots are secret). The mayor proposes laws "
            "(tax, theft_fine, mayor_salary, " + ("sales_tax, wealth_tax, " if _rates_on(cfg) else "")
            + "exile, " + ("revoke_place, " if (cfg.get("places") or {}).get("enabled") else "") + "payout, grant" + (", title" if honors.enabled(cfg) else "") + "); everyone votes with vote_law; a law passes when "
            "more than half of all villagers vote yes. Tax goes to the village treasury. Witnesses and victims of a "
            "theft, attack or arson can report_theft: the culprit "
            + ("gets a bill for the theft_fine in the debt book (paid with pay_bill or left unpaid)."
               if voluntary(cfg) else "pays the theft_fine.")
            + (" The mayor holds the treasury and can embezzle from it; anyone can audit_treasury at the square, "
               "and the books are checked whenever the mayor changes. Found embezzlement can be reported too: the "
               + ("culprit's bill then also holds what they took." if voluntary(cfg)
                  else "culprit returns what they took and pays the fine.")
               if treasury_cfg(cfg).get("embezzle") else ""))


# ---------- guards ----------

def _exile_guard(ctx: Ctx, a: Agent, action: str) -> str | None:
    if not enabled(ctx.cfg) or action not in _g(ctx.cfg)["exile_bans"] or not is_exiled(ctx.world, a.name):
        return None
    return f"you are exiled until day {ctx.world.governance.exiled[a.name]} and may not {action}"


ACTIONS.guards.append(_exile_guard)


def _polity_guard(ctx: Ctx, a: Agent, action: str) -> str | None:
    if action in REPLACED and polity_on(ctx.cfg):
        return "there is no village-wide government here; each polity makes its own laws (polity_propose)"
    return None


ACTIONS.guards.append(_polity_guard)


def _require(ctx: Ctx) -> None:
    if not enabled(ctx.cfg):
        raise ActionError("this village has no government")


# ---------- actions ----------

class RunArgs(BaseModel):
    pitch: str = Field(description="your campaign promise, shown to everyone")


@ACTIONS.action("run_for_mayor", "Stand in the next mayor election with a public campaign promise.", RunArgs,
                available=lambda c, a: enabled(c.cfg) and a.name not in c.world.governance.candidates)
def run_for_mayor(ctx: Ctx, a: Agent, args: RunArgs) -> None:
    _require(ctx)
    pitch = _text(ctx, args.pitch)
    g = ctx.world.governance
    new = a.name not in g.candidates
    g.candidates[a.name] = pitch
    day = next_election_day(ctx.cfg, ctx.world.day)
    ctx.emit("candidate", f'{a.name} runs for mayor (election on day {day}): "{pitch}"' if new else
             f'{a.name} changes their campaign promise: "{pitch}"', actor=a.name, visibility="public")


class VoteArgs(BaseModel):
    candidate: str


@ACTIONS.action("vote", "On election day, secretly vote for a mayor candidate (you can change your vote "
                "until night).", VoteArgs,
                available=lambda c, a: enabled(c.cfg) and is_election_day(c.cfg, c.world.day)
                and bool(c.world.governance.candidates))
def vote(ctx: Ctx, a: Agent, args: VoteArgs) -> None:
    _require(ctx)
    g = ctx.world.governance
    if not is_election_day(ctx.cfg, ctx.world.day):
        raise ActionError(f"the next election is on day {next_election_day(ctx.cfg, ctx.world.day)}")
    cand = _agent(ctx, args.candidate).name
    if cand not in g.candidates:
        raise ActionError(f"{cand} is not a candidate; candidates: {', '.join(sorted(g.candidates)) or 'none'}")
    g.votes[a.name] = cand
    ctx.emit("vote", f"You voted for {cand} for mayor (secret ballot).", actor=a.name, to=[a.name])


class ProposeArgs(BaseModel):
    law: Literal["tax", "theft_fine", "mayor_salary", "sales_tax", "wealth_tax", "exile", "revoke_place", "payout",
                 "grant", "title"]
    value: int | None = Field(None, description="coins, for tax/theft_fine/mayor_salary/grant; percent, for "
                              "sales_tax/wealth_tax")
    person: str | None = Field(None, description="for exile/revoke_place/grant/title")
    text: str | None = Field(None, description="for title: the title's words")


@ACTIONS.action("propose_law", "Mayor only: put a law to the vote. tax/theft_fine/mayor_salary need value "
                "(coins), sales_tax/wealth_tax need value (percent; where World facts list them); exile needs "
                "person; revoke_place needs person (takes their trade place, where World facts list it); grant "
                "needs person and value (paid from the treasury); payout splits the treasury equally; title needs person and "
                "text (a title on the honor board, where World facts list it).", ProposeArgs,
                available=lambda c, a: enabled(c.cfg) and c.world.governance.mayor == a.name)
def propose_law(ctx: Ctx, a: Agent, args: ProposeArgs) -> None:
    _require(ctx)
    w, gc = ctx.world, _g(ctx.cfg)
    g = w.governance
    if g.mayor != a.name:
        raise ActionError(f"only the mayor ({g.mayor or 'nobody yet'}) can propose laws")
    if len(g.proposals) >= gc["max_open_proposals"]:
        raise ActionError(f"at most {gc['max_open_proposals']} proposals can be open at once")
    value, person = args.value, None
    if args.law in TAX_RATES and not _rates_on(ctx.cfg):
        raise ActionError(f"this village has no {args.law}")
    if args.law == "revoke_place" and not (ctx.cfg.get("places") or {}).get("enabled"):
        raise ActionError("trades have no places in this village")
    text = honors.check_title(ctx, args.text) if args.law == "title" else None
    if args.law in NUMBER_LAWS or args.law == "grant":
        lo, hi = gc["limits"][args.law]
        if value is None or not lo <= value <= hi:
            raise ActionError(f"{args.law} needs value between {lo} and {hi}")
    else:
        value = None
    if args.law in ("exile", "revoke_place", "grant", "title"):
        if not args.person:
            raise ActionError(f"{args.law} needs person")
        target = _agent(ctx, args.person)
        if target.status == "dead":
            raise ActionError(f"{target.name} is dead")
        person = target.name
    p = LawProposal(w.new_id("law"), args.law, a.name, w.tick + clock.hours(ctx.cfg, gc["law_vote_hours"]), value, person, yes=[a.name], text=text)
    g.proposals[p.id] = p
    ctx.emit("law_proposed", f"Mayor {a.name} proposes a law ({p.id}): {describe_law(p)}. Vote with vote_law "
             f"until {tick_time(ctx.cfg, p.closes_tick)}.", actor=a.name, visibility="public", law=p.id)


class VoteLawArgs(BaseModel):
    proposal_id: str
    vote: Literal["yes", "no"]


@ACTIONS.action("vote_law", "Vote yes or no on a law the mayor proposed. Works from anywhere.", VoteLawArgs,
                available=lambda c, a: enabled(c.cfg) and bool(c.world.governance.proposals))
def vote_law(ctx: Ctx, a: Agent, args: VoteLawArgs) -> None:
    _require(ctx)
    p = ctx.world.governance.proposals.get(args.proposal_id)
    if p is None:
        raise ActionError(f"no open proposal '{args.proposal_id}'")
    for side in (p.yes, p.no):
        if a.name in side:
            side.remove(a.name)
    (p.yes if args.vote == "yes" else p.no).append(a.name)
    ctx.emit("law_vote", f"You voted {args.vote} on {p.id} ({describe_law(p)}).", actor=a.name, to=[a.name],
             law=p.id, vote=args.vote)
    _maybe_resolve(ctx, p)


class ReportArgs(BaseModel):
    person: str = Field(description="the thief you saw")


@ACTIONS.action("report_theft", "Report a theft, attack or arson you witnessed or suffered awake; everyone learns about it and "
                "the culprit owes the theft_fine to the treasury (World facts say how it is paid).", ReportArgs,
                available=lambda c, a: enabled(c.cfg) and any(a.name in x["known_by"] for x in c.world.governance.crimes))
def report_theft(ctx: Ctx, a: Agent, args: ReportArgs) -> None:
    _require(ctx)
    w = ctx.world
    thief = _agent(ctx, args.person)
    crime = next((c for c in w.governance.crimes if c["thief"] == thief.name and a.name in c["known_by"]), None)
    if crime is None:
        raise ActionError(f"you did not see {thief.name} steal, attack or set fire (in the last "
                          f"{_g(ctx.cfg)['crime_memory_days']} days, unreported)")
    w.governance.crimes.remove(crime)
    bill = None
    if voluntary(ctx.cfg):  # nothing is taken: what is owed becomes a bill in the debt book
        from . import debts
        back = crime.get("amount", 0) if crime.get("crime") == "embezzlement" else 0
        fine = law(w, "theft_fine")
        if back or fine:
            note = " + ".join(x for x in (f"{back} embezzled" if back else "", f"fine {fine}" if fine else "") if x)
            bill = debts.write_bill(ctx, thief.name, back + fine, "fine", note=note).id
            penalty = f"{thief.name} owes the treasury {back + fine} coins ({note}; bill {bill})."
        else:
            penalty = "There is no fine for theft."
    else:
        back = min(crime.get("amount", 0), thief.coins) if crime.get("crime") == "embezzlement" else 0
        if back:
            ops.move_coins(thief, w.governance, back)
        fine = min(law(w, "theft_fine"), thief.coins)
        if fine:
            ops.move_coins(thief, w.governance, fine)
        penalty = f"{thief.name} paid a fine of {fine} coins to the treasury." if fine else \
            "There is no fine for theft." if not law(w, "theft_fine") else f"{thief.name} had no coins to pay the fine."
        if back:
            penalty = f"{thief.name} returned {back} coins to the treasury. " + penalty
    did = {"assault": "attacked", "arson": "set fire to the house of",
           "embezzlement": "embezzled from"}.get(crime.get("crime"), "stole from")
    ctx.emit("theft_report", f"{a.name} reports that {thief.name} {did} {crime['victim']} on day "
             f"{crime['day']}. {penalty}", actor=a.name, visibility="public", thief=thief.name,
             victim=crime["victim"], fine=fine, **({"bill": bill} if bill else {}))


# ---------- engine hooks ----------

def _record_crimes(ctx: Ctx) -> None:
    w = ctx.world
    for ev in ctx.events:
        crime_kind = "theft"
        if ev.kind == "witness":
            thief, victim, seen = ev.data.get("thief"), ev.data.get("victim"), ev.to
        elif ev.kind == "steal_attempt":
            thief, victim, seen = ev.actor, (ev.to or [None])[0], ev.to
        elif ev.kind == "fight":  # conflict.py: the victim and everyone who saw it
            thief, victim = ev.actor, ev.data.get("defender")
            seen, crime_kind = [victim, *ev.data.get("witnesses", [])], "assault"
        elif ev.kind == "arson_seen":
            thief, victim, seen, crime_kind = ev.actor, ev.data.get("victim"), ev.to, "arson"
        else:
            continue
        if not thief or not victim:
            continue
        crime = next((c for c in w.governance.crimes if c["tick"] == ev.tick and c["thief"] == thief
                      and c["victim"] == victim), None)
        if crime is None:
            crime = {"thief": thief, "victim": victim, "day": ev.day, "tick": ev.tick, "known_by": []}
            if crime_kind != "theft":
                crime["crime"] = crime_kind
            w.governance.crimes.append(crime)
        crime["known_by"] += [n for n in seen if n not in crime["known_by"] and n != thief]


def _maybe_resolve(ctx: Ctx, p: LawProposal, closing: bool = False) -> None:
    w = ctx.world
    g = w.governance
    eligible = set(voters(w))
    yes, no = len(set(p.yes) & eligible), len(set(p.no) & eligible)
    passed = yes * 2 > len(eligible)
    if not (passed or closing or no * 2 >= len(eligible) or yes + no >= len(eligible)):
        return
    del g.proposals[p.id]
    tally = f"(yes {yes}, no {no} of {len(eligible)} villagers)"
    if not passed:
        ctx.emit("law_failed", f"Law {p.id} failed: {describe_law(p)} {tally}.", visibility="public", law=p.id)
        return
    extra = _apply_law(ctx, p)
    ctx.emit("law_passed", f"Law {p.id} passed: {describe_law(p)} {tally}.{extra}", visibility="public",
             law=p.id, law_kind=p.law, value=p.value, person=p.person)


def _apply_law(ctx: Ctx, p: LawProposal) -> str:
    w = ctx.world
    g = w.governance
    if p.law in NUMBER_LAWS:
        g.laws[p.law] = p.value
        return ""
    if p.law == "exile":
        g.exiled[p.person] = w.day + _g(ctx.cfg)["exile_days"]
        g.candidates.pop(p.person, None)
        g.votes.pop(p.person, None)
        if g.mayor == p.person:
            g.mayor = None
            handover(ctx, p.person)
            return f" {p.person} is no longer mayor."
        return f" {p.person} is exiled until day {g.exiled[p.person]}."
    target = w.agents.get(p.person) if p.person else None
    if p.law == "revoke_place":
        from . import places  # places imports labor, which imports nothing of governance
        if target is None or target.status == "dead" or target.profession == places.LABORER:
            return " There is no place to take."
        places.lose_place(ctx, target, "taken by law")
        return ""
    if p.law == "title":
        return honors.give_title(ctx, p.person, p.text, "the village")
    if p.law == "grant":
        if target is None or target.status == "dead":
            return " Nobody to pay."
        n = min(p.value, g.coins)
        ops.move_coins(g, target, n)
        return f" {target.name} received {n} coins."
    names = voters(w)  # payout
    share = g.coins // len(names) if names else 0
    for n in names:
        ops.move_coins(g, w.agents[n], share)
    return f" Each of {len(names)} villagers received {share} coins."


def end_of_hour(ctx: Ctx) -> None:
    if not enabled(ctx.cfg):
        return
    _record_crimes(ctx)
    w = ctx.world
    for p in sorted(w.governance.proposals.values(), key=lambda p: p.id):
        _maybe_resolve(ctx, p, closing=w.tick + 1 >= p.closes_tick)


def _count_election(ctx: Ctx, day: int) -> None:
    w = ctx.world
    g = w.governance
    for n in list(g.candidates):
        if w.agents[n].status == "dead":
            del g.candidates[n]
    counts = Counter(c for c in g.votes.values() if c in g.candidates)
    keep = f"{g.mayor} stays mayor." if g.mayor else "The village has no mayor."
    if not g.candidates:
        ctx.emit("election", f"Nobody ran for mayor on day {day}. {keep}", visibility="public")
    elif not counts:
        ctx.emit("election", f"Nobody voted in the election of day {day}. {keep}", visibility="public")
    else:
        top = max(counts.values())
        winner = ctx.rng.choice(sorted(n for n, v in counts.items() if v == top))
        old, g.mayor = g.mayor, winner
        results = ", ".join(f"{n} {counts.get(n, 0)}" for n in sorted(g.candidates, key=lambda n: -counts.get(n, 0)))
        ctx.emit("elected", f"{winner} is elected mayor! Votes: {results}.", visibility="public", mayor=winner,
                 votes=dict(counts))
        if old and old != winner:
            handover(ctx, old)
    g.candidates.clear()
    g.votes.clear()


def new_day(ctx: Ctx) -> None:
    """Called at dawn (world.day is already the new day), before the weekly tax."""
    if not enabled(ctx.cfg) or not progress.unlocked(ctx.world, ELECTIONS):
        return
    w, cfg = ctx.world, ctx.cfg
    g = w.governance
    if polity_on(cfg):  # no elections, salary or exile: only witnessed crimes are kept for report_theft
        g.crimes = [c for c in g.crimes if w.day - c["day"] < _g(cfg)["crime_memory_days"]]
        return
    if is_election_day(cfg, w.day - 1):
        _count_election(ctx, w.day - 1)
    for n, until in list(g.exiled.items()):
        if w.day >= until:
            del g.exiled[n]
            ctx.emit("exile_over", f"{n}'s exile is over.", visibility="public")
    g.crimes = [c for c in g.crimes if w.day - c["day"] < _g(cfg)["crime_memory_days"]]
    if g.mayor and w.agents[g.mayor].status == "dead":
        old, g.mayor = g.mayor, None
        handover(ctx, old)
    salary = min(law(w, "mayor_salary"), g.coins)
    if g.mayor and salary:
        ops.move_coins(g, w.agents[g.mayor], salary)
        ctx.emit("salary", f"You received your mayor salary of {salary} coins from the treasury.", to=[g.mayor])
    if is_election_day(cfg, w.day):
        names = ", ".join(sorted(g.candidates)) or "nobody yet (run_for_mayor)"
        ctx.emit("election_day", f"Election day! Vote for mayor with vote before night. Candidates: {names}.",
                 visibility="public")
    elif is_election_day(cfg, w.day + 1):
        ctx.emit("election_soon", "The mayor election is tomorrow. Use run_for_mayor to stand.", visibility="public")



# ---------- treasury: embezzlement and audits ----------

class EmbezzleArgs(BaseModel):
    coins: int = Field(gt=0, le=100000)


@ACTIONS.action("embezzle", "Mayor only: quietly take coins from the treasury for yourself. The books still show "
                "them until someone audits the treasury or a new mayor takes office.", EmbezzleArgs,
                available=lambda c, a: enabled(c.cfg) and treasury_cfg(c.cfg).get("embezzle")
                and c.world.governance.mayor == a.name and c.world.governance.coins > 0)
def embezzle(ctx: Ctx, a: Agent, args: EmbezzleArgs) -> None:
    _require(ctx)
    g = ctx.world.governance
    if not treasury_cfg(ctx.cfg).get("embezzle"):
        raise ActionError("the treasury cannot be touched in this village")
    if g.mayor != a.name:
        raise ActionError("only the mayor holds the treasury")
    n = min(args.coins, g.coins)
    if n <= 0:
        raise ActionError("the treasury is empty")
    ops.move_coins(g, a, n)
    g.hidden += n
    g.embezzled[a.name] = g.embezzled.get(a.name, 0) + n
    ctx.emit("embezzle", f"You quietly took {n} coins from the treasury. The books still show {books(ctx.world)}; "
             f"{g.coins} are really there.", actor=a.name, to=[a.name], coins=n)


@ACTIONS.action("audit_treasury", "Check the treasury against the books at the square; any missing coins and "
                "the mayor who took them become public.",
                available=lambda c, a: enabled(c.cfg) and treasury_cfg(c.cfg).get("embezzle") and a.location == "square")
def audit_treasury(ctx: Ctx, a: Agent, args) -> None:
    _require(ctx)
    if a.location != "square":
        raise ActionError("the treasury books are kept at the square")
    audit(ctx, f"{a.name} checked the treasury", actor=a.name)


def audit(ctx: Ctx, who: str, actor: str | None = None) -> None:
    """Compare the treasury with the books. Missing coins become public and reportable as embezzlement."""
    w = ctx.world
    g = w.governance
    if not g.hidden:
        ctx.emit("audit_clean", f"{who}: the books are in order, the treasury holds {g.coins} coins.",
                 actor=actor, visibility="public", coins=g.coins)
        return
    knowers = [n for n in voters(w) if n not in g.embezzled]
    for mayor, n in sorted(g.embezzled.items()):
        if mayor == theft.UNKNOWN:  # theft.py: a thief, not the mayor, took these
            ctx.emit("embezzlement_found", f"{who}: {n} coins are missing from the treasury; nobody knows who took "
                     f"them. The books now show {g.coins} coins.", actor=actor, visibility="public", coins=n)
            continue
        ctx.emit("embezzlement_found", f"{who}: {n} coins are missing from the treasury. They were taken by "
                 f"{mayor} while mayor. The books now show {g.coins} coins.", actor=actor, visibility="public",
                 mayor=mayor, coins=n)
        g.crimes.append({"thief": mayor, "victim": "the village", "day": w.day, "tick": w.tick, "crime": "embezzlement",
                         "amount": n, "known_by": [k for k in knowers if k != mayor]})
    g.hidden, g.embezzled = 0, {}


def handover(ctx: Ctx, old: str) -> None:
    """The office changed hands: the treasury is counted in public (if config treasury.audit_on_handover)."""
    if treasury_cfg(ctx.cfg).get("audit_on_handover") and ctx.world.governance.hidden:
        audit(ctx, f"The treasury was counted when {old} left office")
