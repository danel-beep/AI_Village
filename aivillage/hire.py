"""Hiring («С нуля» plan task 18; config block `hire`, off unless a mode turns it on).

Contracts between villagers come first (opened at the hamlet stage), outsiders hired at the town hall second
(opened with the town hall) and dearer, so they are a reserve, not a stand-in for neighbours.

Contracts:
- `offer_job(to, task, hours, wage, pay)` from anywhere: `task` is a resource (the worker gathers it and every
  unit goes to the employer at once, carried), `build` (hours on a building site the employer owns or started)
  or `guard` (hours awake at the employer's house; a guard there fights anyone who steals, sets a fire or
  attacks the family). `wage` is items and/or coins. `pay`: `before` (handed over when the job is accepted)
  or `after` (owed when the job ends).
- `accept_job` / `decline_job` by the worker; one job at a time. Hours count automatically from what the
  worker does; the job ends by itself when they are done, at the deadline (`deadline_days`) or by `end_job`
  from either side.
- The end settles the wage by the hours done: paid `after`, the employer owes the share earned; paid
  `before`, the worker owes back the share not earned. Nobody is forced: `pay_job` pays what one owes on a
  job; a share still unpaid `pay_days` after the end is announced to the village once (`job_unpaid`) and
  stays on the job board until paid.
- The signing, the end, payments and unpaid shares are public events; `job_board` shows every open job.

Outsiders (`hire_npc` at the town hall, coins paid up front leave the village):
- worker: gathers one resource for `hours` day-hours at `npc.worker.per_hour`, from the place that has the
  most of it; the goods reach the hirer at once.
- guard: stands at the hirer's house for `days` and fights anyone who steals there, sets it on fire or
  attacks the family (`npc.guard`: attack, damage, health for that fight).

A guard (hired villager awake at the house, or an outsider) steps in before the act through
`ACTIONS.interceptors`: the dice of conflict.py, the guard swings first; if the guard wins the act does
not happen, if the intruder wins it goes on as usual.

State `world.hire`: {"jobs": {id: job}, "npcs": [npc]}. Log events: `job_offer` (private), `job_signed`,
`job_ended`, `job_paid`, `job_unpaid`, `npc_hired` (public; npc, npc_kind, employer, cost), `npc_left` (to the hirer), `job_progress` (the two sides),
`npc_work` (log only: npc, resource, amount, location), `guard_fight` (location: guard, intruder, act,
winner, rounds, npc).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from . import clock, conflict, construction, ops, plots, progress, tiles
from .actions import ItemMap, _agent, _check_bundle, _holds, _transfer_bundle
from .ops import Ctx, Event, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, World

JOB_ACTIONS = ("offer_job", "accept_job", "decline_job", "end_job", "pay_job")
for _n in JOB_ACTIONS:
    progress.DEFAULT_UNLOCKS.setdefault(f"action:{_n}", {"stage": "hamlet"})
progress.DEFAULT_UNLOCKS.setdefault("action:hire_npc", {"building": "town_hall"})

SPECIAL_TASKS = ("build", "guard")
GUARDED = ("steal", "steal_from_plot", "set_fire", "attack")
OPEN = ("offered", "active", "owed")


def _h(cfg: dict) -> dict:
    return cfg["hire"]


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("hire", {}).get("enabled"))


def hidden_actions(cfg: dict) -> frozenset[str]:
    """Actions to leave out of the handbook when hiring is off."""
    return frozenset() if enabled(cfg) else frozenset((*JOB_ACTIONS, "hire_npc"))


def _state(world: World) -> dict:
    if not world.hire:
        world.hire.update({"jobs": {}, "npcs": []})
    return world.hire


def jobs(world: World) -> dict[str, dict]:
    return world.hire.get("jobs", {})


def npcs(world: World) -> list[dict]:
    return world.hire.get("npcs", [])


def resources(world: World) -> set[str]:
    return {r for loc in world.locations.values() for r in loc.resources}


def _share(wage: dict, done: int, hours: int) -> dict:
    return {k: v * min(done, hours) // hours for k, v in wage.items() if v * min(done, hours) // hours > 0}


def _minus(a: dict, b: dict) -> dict:
    return {k: v - b.get(k, 0) for k, v in a.items() if v - b.get(k, 0) > 0}


def _bundle(b: dict) -> str:
    items = {k: v for k, v in b.items() if k != "coins"}
    parts = ([fmt_items(items)] if items else []) + ([f"{b['coins']} coins"] if b.get("coins") else [])
    return " and ".join(parts) or "nothing"


def _task_text(j: dict) -> str:
    if j["task"] == "build":
        return f"{j['hours']} hours of building work"
    if j["task"] == "guard":
        return f"{j['hours']} hours guarding {j['employer']}'s house"
    return f"{j['hours']} hours gathering {j['task']}"


def _active_job(world: World, worker: str) -> dict | None:
    return next((j for j in jobs(world).values() if j["worker"] == worker and j["status"] == "active"), None)


def _living(world: World, name: str) -> bool:
    a = world.agents.get(name)
    return a is not None and a.status != "dead"


# ---------- contracts ----------

class OfferJobArgs(BaseModel):
    to: str = Field(description="the villager you offer the job to")
    task: str = Field(description="a resource they gather for you, 'build' (your building sites) or 'guard' (your house)")
    hours: int = Field(ge=1, le=24)
    wage: ItemMap = Field(description="what you pay: items and/or 'coins'")
    pay: Literal["before", "after"] = Field("after", description="'before': paid when they accept; 'after': owed when the job ends")


@ACTIONS.action("offer_job", "Offer someone a job, from anywhere: a resource they gather for you (every unit is yours), "
                "'build' (hours on your building sites) or 'guard' (hours at your house); the wage is paid before "
                "or after. See World facts for how it ends.", OfferJobArgs,
                available=lambda c, a: enabled(c.cfg))
def offer_job(ctx: Ctx, a: Agent, args: OfferJobArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        raise ActionError("there is no hiring in this village")
    h = _h(cfg)
    other = _agent(ctx, args.to)
    if other.name == a.name:
        raise ActionError("you cannot hire yourself")
    if other.status != "active":
        raise ActionError(f"{other.name} cannot work now")
    task = args.task.strip().lower()
    if task not in SPECIAL_TASKS and task not in resources(w):
        raise ActionError(f"unknown task '{args.task}'; a task is a resource gathered somewhere ("
                          f"{', '.join(sorted(resources(w)))}), 'build' or 'guard'")
    if args.hours > h["max_hours"]:
        raise ActionError(f"a job is at most {h['max_hours']} hours")
    wage = {k: v for k, v in args.wage.items() if v > 0}
    if not wage:
        raise ActionError("the wage is empty")
    _check_bundle(ctx, wage)
    mine = [j for j in jobs(w).values() if j["employer"] == a.name and j["status"] == "offered"]
    if len(mine) >= h["max_open_offers"]:
        raise ActionError(f"you already have {len(mine)} job offers open (the most at once)")
    j = {"id": w.new_id("job"), "employer": a.name, "worker": other.name, "task": task, "hours": args.hours,
         "wage": wage, "pay": args.pay, "status": "offered", "day": w.day,
         "expires_tick": w.tick + clock.hours(cfg, h["offer_hours"]), "due_day": None, "done": 0,
         "delivered": {}, "ended": None, "owes": None, "owed": {}, "owed_day": None, "told": False}
    _state(w)["jobs"][j["id"]] = j
    when = "paid when you accept" if args.pay == "before" else "owed when the job ends"
    ctx.emit("job_offer", f"{a.name} offers you a job ({j['id']}): {_task_text(j)} for {_bundle(wage)}, {when}. "
             f"Work it off by the end of day {w.day + h['deadline_days'] - 1} after accepting.", actor=a.name,
             to=[other.name], job=j["id"], employer=a.name, worker=other.name, task=task, hours=args.hours,
             wage=wage, pay=args.pay)
    ctx.emit("job_offer", f"You offered {other.name} a job ({j['id']}): {_task_text(j)} for {_bundle(wage)}, "
             f"paid {args.pay}.", actor=a.name, to=[a.name], job=j["id"])


class JobIdArgs(BaseModel):
    job_id: str


def _job(ctx: Ctx, job_id: str) -> dict:
    j = jobs(ctx.world).get(job_id.strip())
    if j is None:
        raise ActionError(f"there is no job {job_id}")
    return j


def _offer_to(ctx: Ctx, a: Agent, job_id: str) -> dict:
    j = _job(ctx, job_id)
    if j["worker"] != a.name or j["status"] != "offered":
        raise ActionError(f"job {j['id']} is not an open offer to you")
    return j


def _offered_to(world: World, name: str) -> bool:
    return any(j["worker"] == name and j["status"] == "offered" for j in jobs(world).values())


@ACTIONS.action("accept_job", "Take a job offered to you, from anywhere (one job at a time).", JobIdArgs,
                available=lambda c, a: enabled(c.cfg) and _offered_to(c.world, a.name))
def accept_job(ctx: Ctx, a: Agent, args: JobIdArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    j = _offer_to(ctx, a, args.job_id)
    if (cur := _active_job(w, a.name)) is not None:
        raise ActionError(f"you already work job {cur['id']} for {cur['employer']}; end it first (end_job)")
    boss = w.agents[j["employer"]]
    if boss.status == "dead":
        raise ActionError(f"{boss.name} is dead")
    if j["pay"] == "before":
        if not _holds(boss, j["wage"]):
            raise ActionError(f"{boss.name} does not have {_bundle(j['wage'])} now, so the wage cannot be paid "
                              "before")
        _transfer_bundle(boss, a, j["wage"])
    j.update(status="active", day=w.day, due_day=w.day + _h(cfg)["deadline_days"] - 1)
    paid = (f"{boss.name} paid {_bundle(j['wage'])} up front" if j["pay"] == "before"
            else f"{boss.name} pays {_bundle(j['wage'])} after")
    ctx.emit("job_signed", f"{a.name} took a job from {boss.name} ({j['id']}): {_task_text(j)} by the end of day "
             f"{j['due_day']}; {paid}.", actor=a.name, visibility="public", job=j["id"], employer=boss.name,
             worker=a.name, task=j["task"], hours=j["hours"], wage=j["wage"], pay=j["pay"], due_day=j["due_day"])


@ACTIONS.action("decline_job", "Turn down a job offered to you.", JobIdArgs,
                available=lambda c, a: enabled(c.cfg) and _offered_to(c.world, a.name))
def decline_job(ctx: Ctx, a: Agent, args: JobIdArgs) -> None:
    j = _offer_to(ctx, a, args.job_id)
    del jobs(ctx.world)[j["id"]]
    ctx.emit("job_declined", f"{a.name} turned down your job offer {j['id']}.", actor=a.name,
             to=[j["employer"], a.name], job=j["id"])


def _in_job(world: World, name: str) -> bool:
    return any(j["status"] == "active" and name in (j["worker"], j["employer"]) for j in jobs(world).values())


@ACTIONS.action("end_job", "End a job you work or gave before its hours are done; the wage is settled by the hours "
                "worked.", JobIdArgs, available=lambda c, a: enabled(c.cfg) and _in_job(c.world, a.name))
def end_job(ctx: Ctx, a: Agent, args: JobIdArgs) -> None:
    j = _job(ctx, args.job_id)
    if j["status"] != "active" or a.name not in (j["worker"], j["employer"]):
        raise ActionError(f"job {j['id']} is not an active job of yours")
    settle(ctx, j, "ended by " + a.name)


def _owes(world: World, name: str) -> bool:
    return any(j["status"] == "owed" and j["owes"] == name for j in jobs(world).values())


@ACTIONS.action("pay_job", "Pay what you owe on a job, from anywhere (all of it at once).", JobIdArgs,
                available=lambda c, a: enabled(c.cfg) and _owes(c.world, a.name))
def pay_job(ctx: Ctx, a: Agent, args: JobIdArgs) -> None:
    j = _job(ctx, args.job_id)
    if j["status"] != "owed" or j["owes"] != a.name:
        raise ActionError(f"you owe nothing on job {j['id']}")
    to = j["employer"] if a.name == j["worker"] else j["worker"]
    if not _holds(a, j["owed"]):
        raise ActionError(f"you owe {_bundle(j['owed'])} and do not have it all")
    _transfer_bundle(a, ctx.world.agents[to], j["owed"])
    what = "the wage" if a.name == j["employer"] else "back the unearned wage"
    ctx.emit("job_paid", f"{a.name} paid {to} {what} of job {j['id']}: {_bundle(j['owed'])}.", actor=a.name,
             visibility="public", job=j["id"], payer=a.name, to_whom=to, paid=dict(j["owed"]))
    _close(ctx.world, j)


def settle(ctx: Ctx, j: dict, reason: str) -> None:
    """End an active job: work out who owes what by the hours done and tell the village."""
    w, cfg = ctx.world, ctx.cfg
    earned = _share(j["wage"], j["done"], j["hours"])
    if j["pay"] == "after":
        owes, owed = j["employer"], earned
    else:
        owes, owed = j["worker"], _minus(j["wage"], earned)
    j["ended"] = reason
    text = (f"Job {j['id']} ({j['worker']} for {j['employer']}: {_task_text(j)}) ended, {reason}: "
            f"{j['done']} of {j['hours']} hours done")
    if j["delivered"]:
        text += f", {fmt_items(j['delivered'])} delivered"
    if owed and _living(w, owes):
        j.update(status="owed", owes=owes, owed=owed, owed_day=w.day)
        text += f". {owes} owes {j['worker'] if owes == j['employer'] else j['employer']} {_bundle(owed)} (pay_job)."
    else:
        text += "."
        _close(w, j)
    ctx.emit("job_ended", text, visibility="public", job=j["id"], employer=j["employer"], worker=j["worker"],
             done=j["done"], hours=j["hours"], reason=reason, owes=j["owes"], owed=dict(j["owed"]))


def _close(world: World, j: dict) -> None:
    j.update(status="closed", owes=None, owed={})
    closed = [x for x in jobs(world).values() if x["status"] == "closed"]
    keep = int(_h(world.config).get("keep_closed", 30))
    for x in closed[: max(0, len(closed) - keep)]:
        del jobs(world)[x["id"]]


def _count_hour(ctx: Ctx, j: dict, got: dict | None = None) -> None:
    j["done"] += 1
    if got:
        for k, v in got.items():
            j["delivered"][k] = j["delivered"].get(k, 0) + v
    left = j["hours"] - j["done"]
    tail = f" ({j['id']}, {j['done']}/{j['hours']} hours)"
    if got:
        ctx.emit("job_progress", f"{j['worker']} gathered {fmt_items(got)} for you{tail}.", to=[j["employer"]],
                 job=j["id"], items=got)
        ctx.emit("job_progress", f"{fmt_items(got)} went to {j['employer']}{tail}.", to=[j["worker"]], job=j["id"])
    elif left <= 0 or j["task"] == "build":
        ctx.emit("job_progress", f"{j['worker']} worked an hour of job{tail}.", to=[j["employer"], j["worker"]],
                 job=j["id"])
    if left <= 0:
        settle(ctx, j, "all hours done")


def _on_event(ctx: Ctx, ev: Event, names: list[str]) -> None:
    """Count a worker's gathering and building hours; gathered goods go to the employer."""
    if ev.kind not in ("work", "construct") or not ev.actor or not enabled(ctx.cfg):
        return
    w = ctx.world
    j = _active_job(w, ev.actor)
    if j is None:
        return
    if ev.kind == "work" and ev.data.get("resource") == j["task"]:
        a, boss = w.agents[ev.actor], w.agents[j["employer"]]
        amount = min(int(ev.data.get("amount") or 0), ops.count(a.inventory, j["task"]))
        got = {j["task"]: amount} if amount else {}
        if got:
            ops.move_items(a.inventory, boss.inventory, got)
        _count_hour(ctx, j, got)
    elif ev.kind == "construct" and j["task"] == "build":
        s = construction.sites(w).get(ev.data.get("site"))
        if s is not None and j["employer"] in (s.get("owner"), s.get("started_by")):
            _count_hour(ctx, j)


ops.EVENT_HOOKS.append(_on_event)


# ---------- outsiders hired at the town hall ----------

def hall(world: World) -> str:
    """Where the town hall stands (the square if it only counts from a later start stage)."""
    return next((b["location"] for b in construction.common(world) if b["kind"] == "town_hall"), "square")


class HireNpcArgs(BaseModel):
    kind: Literal["worker", "guard"]
    resource: str | None = Field(None, description="worker: the resource they gather for you")
    hours: int = Field(4, ge=1, le=24, description="worker: day-hours of work")
    days: int = Field(1, ge=1, le=10, description="guard: days at your house")


def _npc_cost(cfg: dict, kind: str, hours: int, days: int) -> int:
    n = _h(cfg)["npc"][kind]
    return n["wage_per_hour"] * hours if kind == "worker" else n["wage_per_day"] * days


@ACTIONS.action("hire_npc", "At the town hall: hire an outsider for coins paid now, which leave the village: a worker "
                "who gathers one resource for you, or a guard for your house. Prices in World facts.", HireNpcArgs,
                available=lambda c, a: enabled(c.cfg) and a.location == hall(c.world))
def hire_npc(ctx: Ctx, a: Agent, args: HireNpcArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        raise ActionError("there is no hiring in this village")
    if a.location != hall(w):
        raise ActionError(f"outsiders are hired at the town hall ({hall(w)})")
    n, spec = _h(cfg)["npc"], _h(cfg)["npc"][args.kind]
    if sum(1 for x in npcs(w) if x["employer"] == a.name) >= n["max_per_person"]:
        raise ActionError(f"you already have {n['max_per_person']} hired outsiders (the most at once)")
    if len(npcs(w)) >= n["max_in_village"]:
        raise ActionError(f"{n['max_in_village']} outsiders already work in the village (the most at once)")
    x = {"id": w.new_id("npc"), "kind": args.kind, "employer": a.name}
    if args.kind == "worker":
        res = (args.resource or "").strip().lower()
        if res not in resources(w):
            raise ActionError(f"a hired worker gathers one of: {', '.join(sorted(resources(w)))}")
        if args.hours > spec["max_hours"]:
            raise ActionError(f"a hired worker works at most {spec['max_hours']} hours")
        x.update(resource=res, hours_left=args.hours, got={}, location=None)
        what = f"a worker to gather {res} for {args.hours} hours"
    else:
        if args.days > spec["max_days"]:
            raise ActionError(f"a guard is hired for at most {spec['max_days']} days")
        if a.home not in w.locations:
            raise ActionError("you have no house to guard")
        x.update(home=a.home, until_day=w.day + args.days - 1, location=a.home)
        what = f"a guard for their house until the end of day {x['until_day']}"
    cost = _npc_cost(cfg, args.kind, args.hours, args.days)
    if a.coins < cost:
        raise ActionError(f"that costs {cost} coins; you have {a.coins}")
    ops.burn_coins(w, a, cost)
    _state(w)["npcs"].append(x)
    ctx.emit("npc_hired", f"{a.name} hired {what} from outside the village for {cost} coins.", actor=a.name,
             visibility="public", npc=x["id"], npc_kind=args.kind, employer=a.name, cost=cost,
             **({"resource": x["resource"], "hours": args.hours} if args.kind == "worker"
                else {"home": x["home"], "until_day": x["until_day"]}))


def _npc_work(ctx: Ctx, x: dict) -> None:
    w = ctx.world
    boss = w.agents[x["employer"]]
    places = sorted((loc for loc in w.locations.values() if loc.resources.get(x["resource"], 0) > 0),
                    key=lambda loc: (-loc.resources[x["resource"]], loc.id))
    amount = 0
    if places:
        loc = places[0]
        amount = sum(n for _, n in tiles.take(loc, x["resource"], _h(ctx.cfg)["npc"]["worker"]["per_hour"]))
        x["location"] = loc.id
    if amount:
        ops.mint(w, boss.inventory, x["resource"], amount)
        x["got"][x["resource"]] = x["got"].get(x["resource"], 0) + amount
    x["hours_left"] -= 1
    ctx.emit("npc_work", f"A hired worker gathered {amount} {x['resource']} for {boss.name}.", location=x["location"], npc=x["id"], employer=boss.name, resource=x["resource"],
             amount=amount)


def _leave(ctx: Ctx, x: dict, why: str) -> None:
    npcs(ctx.world).remove(x)
    if _living(ctx.world, x["employer"]):
        ctx.emit("npc_left", why, to=[x["employer"]], npc=x["id"], npc_kind=x["kind"], employer=x["employer"])


# ---------- guards ----------

def _household(world: World, loc: str) -> list[str]:
    plot = world.plots.get(loc)
    if plot is not None and plot.kind == "home":
        fam = plots.household(world, plot)
        if fam:
            return fam
    return [a.name for a in world.agents.values() if a.home == loc]


def guards_at(world: World, loc: str) -> list[dict]:
    """Who guards the house at `loc` right now: [{"name", "npc": bool}] (outsiders first)."""
    fam = set(_household(world, loc))
    if not fam:
        return []
    out = [{"name": x["id"], "npc": True} for x in npcs(world) if x["kind"] == "guard" and x["home"] == loc]
    for j in jobs(world).values():
        g = world.agents.get(j["worker"])
        if (j["status"] == "active" and j["task"] == "guard" and j["employer"] in fam and g is not None
                and g.location == loc and ops.can_act(g)):
            out.append({"name": g.name, "npc": False})
    return out


def _target(world: World, a: Agent, name: str, args: BaseModel) -> bool:
    """Is this act aimed at the house where `a` stands or its family?"""
    fam = _household(world, a.location)
    if not fam or a.name in fam:
        return False
    if name == "attack":
        return any(n.lower() == str(args.target).strip().lower() for n in fam)
    if name == "steal":
        t = str(args.target).strip().lower()
        return t == "chest" or any(n.lower() == t for n in fam)
    return True  # steal_from_plot, set_fire: the house itself


def _intercept(ctx: Ctx, a: Agent, name: str, args: BaseModel) -> bool:
    if name not in GUARDED or not enabled(ctx.cfg) or not _target(ctx.world, a, name, args):
        return False
    for g in guards_at(ctx.world, a.location):
        if g["name"] == a.name:
            continue
        if _fight(ctx, a, g, name):
            return True
    return False


ACTIONS.interceptors.append(_intercept)


def _fight(ctx: Ctx, thief: Agent, g: dict, act: str) -> bool:
    """A guard against an intruder caught in the act; True when the guard wins (the act is stopped)."""
    w, cfg, rng = ctx.world, ctx.cfg, ctx.rng
    c = cfg["combat"]
    if g["npc"]:
        s = _h(cfg)["npc"]["guard"]
        guard, gname, gear, hp = None, "a hired guard", (None, s["attack"], s["damage"]), [s["health"]]
    else:
        guard = w.agents[g["name"]]
        guard.asleep = False
        gname, gear, hp = guard.name, conflict.weapon(cfg, guard), None
    tgear = conflict.weapon(cfg, thief)
    dealt = {"guard": 0, "intruder": 0}
    rounds, quit_by = [], None
    for r in range(1, c["rounds"] + 1):
        for side in ("guard", "intruder"):
            atk, dmg = (gear if side == "guard" else tgear)[1:]
            roll = rng.randint(1, c["die"])
            hit = roll == c["die"] or (roll != 1 and roll + atk >= c["hit_at"])
            raw = rng.randint(1, c["damage_die"]) + dmg if hit else 0
            if side == "guard":
                hurt = min(thief.health, conflict.soak(ctx, thief, raw)) if hit else 0
                thief.health -= hurt
                low = thief.health <= c["give_up_health"]
            elif guard is None:
                hurt = min(hp[0], raw)
                hp[0] -= hurt
                low = hp[0] <= c["give_up_health"]
            else:
                hurt = min(guard.health, conflict.soak(ctx, guard, raw)) if hit else 0
                guard.health -= hurt
                low = guard.health <= c["give_up_health"]
            dealt[side] += hurt
            rounds.append({"round": r, "by": gname if side == "guard" else thief.name, "roll": roll,
                           "bonus": atk, "hit": hit, "damage": hurt})
            if low:
                quit_by = "intruder" if side == "guard" else "guard"
                break
        if quit_by:
            break
    won = quit_by == "intruder" or (quit_by is None and dealt["guard"] >= dealt["intruder"])
    conflict.wear(ctx, thief, tgear[0])
    if guard is not None:
        conflict.wear(ctx, guard, gear[0])
    owner = _household(w, thief.location)[0]
    doing = {"steal": "steal", "steal_from_plot": "steal from the yard", "set_fire": "set the house on fire",
             "attack": "attack the family"}[act]
    end = (f"{gname} won: {thief.name} was driven off." if won
           else f"{thief.name} won and went on.")
    fam = [n for n in _household(w, thief.location) if n != thief.name]
    ctx.emit("guard_fight", f"{gname.capitalize() if g['npc'] else gname} guarding {owner}'s house caught "
             f"{thief.name} trying to {doing} and fought: {thief.name} lost {dealt['guard']} health, the guard "
             f"{dealt['intruder']}. {end}", actor=thief.name, location=thief.location, visibility="location",
             to=fam + ([guard.name] if guard is not None else []), guard=gname, npc=g["npc"], intruder=thief.name,
             act=act, owner=owner, winner=gname if won else thief.name, rounds=rounds, damage=dealt)
    return won


# ---------- hours, deadlines, observation ----------

def end_of_hour(ctx: Ctx) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg) or not w.hire:
        return
    for j in list(jobs(w).values()):
        if j["status"] == "offered" and (j["expires_tick"] <= w.tick or not _living(w, j["employer"])
                                         or not _living(w, j["worker"])):
            del jobs(w)[j["id"]]
        elif j["status"] == "active":
            if not _living(w, j["worker"]) or not _living(w, j["employer"]):
                settle(ctx, j, "a side died")
            elif j["task"] == "guard" and w.agents[j["worker"]].location == w.agents[j["employer"]].home \
                    and ops.can_act(w.agents[j["worker"]]):
                _count_hour(ctx, j)
            if j["status"] == "active" and w.day > j["due_day"]:
                settle(ctx, j, f"the deadline (day {j['due_day']}) passed")
        elif j["status"] == "owed":
            if not _living(w, j["owes"]) or not _living(w, j["employer"] if j["owes"] == j["worker"] else j["worker"]):
                _close(w, j)
            elif not j["told"] and w.day >= j["owed_day"] + _h(cfg)["pay_days"]:
                j["told"] = True
                to = j["employer"] if j["owes"] == j["worker"] else j["worker"]
                ctx.emit("job_unpaid", f"{j['owes']} has not paid {to} {_bundle(j['owed'])} for job {j['id']} "
                         f"(ended day {j['owed_day']}).", visibility="public", job=j["id"], owes=j["owes"],
                         to_whom=to, owed=dict(j["owed"]))
    for x in list(npcs(w)):
        if not _living(w, x["employer"]):
            _leave(ctx, x, "")
        elif x["kind"] == "worker":
            _npc_work(ctx, x)
            if x["hours_left"] <= 0:
                _leave(ctx, x, f"The hired worker finished and left: {fmt_items(x['got'])} came to you in all.")
        elif w.day > x["until_day"]:
            _leave(ctx, x, "Your hired guard's days are over; the guard left.")


def _row(j: dict) -> dict:
    out = {"id": j["id"], "employer": j["employer"], "worker": j["worker"], "task": j["task"], "hours": j["hours"],
           "wage": j["wage"], "pay": j["pay"], "status": j["status"]}
    if j["status"] == "active":
        out.update(hours_done=j["done"], due_day=j["due_day"])
    if j["status"] == "owed":
        out.update(hours_done=j["done"], owes=j["owes"], owed=j["owed"], ended_day=j["owed_day"])
    return out


def observe(world: World, name: str) -> dict:
    cfg = world.config
    if not enabled(cfg):
        return {}
    out: dict = {}
    js = [j for j in jobs(world).values() if j["status"] in OPEN]
    offers = [_row(j) for j in js if j["status"] == "offered" and j["worker"] == name]
    if offers:
        out["jobs_offered_to_you"] = offers
    board = [_row(j) for j in js if j["status"] != "offered"]
    if board:
        out["job_board"] = board
    mine = [{"id": x["id"], "kind": x["kind"], **({"resource": x["resource"], "hours_left": x["hours_left"]}
                                                  if x["kind"] == "worker" else {"until_day": x["until_day"]})}
            for x in npcs(world) if x["employer"] == name]
    if mine:
        out["your_hired_outsiders"] = mine
    a = world.agents.get(name)
    if a is not None and a.location == hall(world) and progress.unlocked(world, "action:hire_npc"):
        n = _h(cfg)["npc"]
        out["outsiders_for_hire"] = {"worker": f"{n['worker']['wage_per_hour']} coins an hour, gathers "
                                               f"{n['worker']['per_hour']} of one resource an hour",
                                     "guard": f"{n['guard']['wage_per_day']} coins a day"}
    return out


def facts(cfg: dict, outsiders: bool = True) -> str:
    """Rules lines on jobs; `outsiders` False (no town hall yet, llm.world_facts) leaves out hire_npc."""
    h = _h(cfg)
    n = h["npc"]
    out = (f"- Jobs: offer_job hires a villager for hours of work for a wage (items and/or coins) paid before (when "
           f"they accept) or after (owed when it ends). A job ends when its hours are done, by end_job, or when "
           f"{h['deadline_days']} day(s) counting the day it was accepted are over; then the wage is settled by the hours done: "
           f"the employer owes the share earned, or the worker owes back the share not earned. Nobody is forced: "
           f"pay_job pays it, an unpaid share is announced to the village after {h['pay_days']} day(s). Gathered "
           f"goods of a job go to the employer at once. A guard (task 'guard') counts hours awake at the employer's "
           f"house and fights whoever steals there, sets it on fire or attacks the family.")
    if not outsiders:
        return out
    return out + (f"\n- Outsiders (hire_npc at the town hall, coins paid now leave the village): a worker gathers "
                  f"{n['worker']['per_hour']} of one resource an hour for {n['worker']['wage_per_hour']} coins an hour; a "
                  f"guard stands at your house for {n['guard']['wage_per_day']} coins a day and fights intruders the same way.")


def view(world: World) -> dict:
    """Viewer: hired outsiders and where they are; open jobs."""
    if not enabled(world.config) or not world.hire:
        return {}
    return {"hire": {"npcs": [{"id": x["id"], "kind": x["kind"], "employer": x["employer"],
                               "location": x.get("location")} for x in npcs(world)],
                     "jobs": [_row(j) for j in jobs(world).values() if j["status"] in ("active", "owed")]}}
