"""Taxes, the treasury loop and council orders (config blocks `taxes` and `council_orders`).

Off by default; the default "crafts" mode turns both on. Before, the tax was flat (the same 20 coins from the
poorest and the richest), the treasury filled up and was hardly spent, and a council order paid its whole
reward to whoever raced to it first. Now, by world rules only:

- one bill per villager on a tax day: the flat land tax (`tax_amount`, law "tax") + `sales_pct`% of the
  coins they got from the trader and council orders since the last tax day (law "sales_tax") +
  `wealth_pct`% of their coins above `wealth_above` (law "wealth_tax"). Trades between villagers are free;
- `burn_pct`% of every bill leaves the game (keeps coins from piling up), the rest goes to the treasury;
- the mayor spends the treasury: `treasury_order` buys goods for a village project from villagers (they
  deliver at the square and are paid from the treasury), next to fund_project, grant and payout;
- a surplus nobody spends (above `surplus_per_villager` x villagers for `surplus_idle_days`) goes to those
  who worked on village projects since the last payout, or to everyone;
- council orders pay `reward_mult` x the base value of what they need and take part deliveries: every
  delivery is paid at once, its share of the order's value, so villagers can fill one order together.

State: `Agent.earned_since_tax`, `Governance.last_spent_day` / `work_hours`, `Order.payer` / `project` /
`delivered` / `paid`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import governance, ops, works
from .actions import ItemMap, _items_known
from .ops import Ctx, Event, fmt_items
from .registry import ACTIONS, ActionError
from .state import Agent, Order, World

TREASURY = "treasury"


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("taxes", {}).get("enabled"))


def _t(cfg: dict) -> dict:
    return cfg["taxes"]


def council_on(cfg: dict) -> bool:
    return bool(cfg.get("council_orders", {}).get("enabled"))


# ---------- the tax bill ----------

def rate(world: World, name: str) -> int:
    """Percent in force for "sales_tax" / "wealth_tax" (a law overrides the config)."""
    if name in world.governance.laws:
        return world.governance.laws[name]
    return _t(world.config)["sales_pct" if name == "sales_tax" else "wealth_pct"] if enabled(world.config) else 0


def bill(world: World, a: Agent) -> dict:
    """What `a` owes on the next tax day, if nothing changes until then."""
    land = governance.tax_amount(world)
    if not enabled(world.config):
        return {"total": land}
    above = _t(world.config)["wealth_above"]
    sales = a.earned_since_tax * rate(world, "sales_tax") // 100
    wealth = max(0, a.coins - above) * rate(world, "wealth_tax") // 100
    return {"total": land + sales + wealth, "land": land, "sales": sales, "wealth": wealth}


def record_income(world: World, a: Agent, n: int) -> None:
    """Coins `a` got from outside the village (the trader, council orders): the base of the sales tax."""
    if enabled(world.config):
        a.earned_since_tax += n


def pay(world: World, a: Agent, n: int) -> int:
    """`a` pays `n` coins of tax: `burn_pct`% leaves the game, the rest goes to the treasury. Returns burned."""
    if n <= 0:
        return 0
    if not enabled(world.config):
        governance.pay_tax(world, a, n)
        return 0
    burned = n if not governance.enabled(world.config) else n * _t(world.config)["burn_pct"] // 100
    ops.burn_coins(world, a, burned)
    if n - burned:
        governance.pay_tax(world, a, n - burned)
    return burned


def collect(ctx: Ctx) -> None:
    """Tax day: every living villager pays their bill; who cannot pay gives all coins and is evicted."""
    w, cfg = ctx.world, ctx.cfg
    for a in w.agents.values():
        if a.status == "dead":
            continue
        b = bill(w, a)
        a.earned_since_tax = 0
        tax = b["total"]
        if a.coins >= tax:
            pay(w, a, tax)
            parts = ", ".join(f"{k} {b[k]}" for k in ("land", "sales", "wealth") if b.get(k))
            ctx.emit("tax", f"You paid {tax} coins of tax" + (f" ({parts})." if len(b) > 1 else "."), to=[a.name],
                     **{k: v for k, v in b.items() if k != "total"})
        else:
            pay(w, a, a.coins)
            a.evicted_until_day = w.day + cfg["eviction_days"]
            ctx.emit("evicted", f"{a.name} could not pay the tax and is locked out of their house "
                     f"for {cfg['eviction_days']} days.", visibility="public")


# ---------- treasury spending ----------

def spent(world: World) -> None:
    """The treasury paid for something today (fund_project, treasury_order, grant, payout)."""
    world.governance.last_spent_day = world.day


def worked(world: World, name: str) -> None:
    """One hour of build_work: counts toward the surplus payout."""
    g = world.governance
    g.work_hours[name] = g.work_hours.get(name, 0) + 1


def _on_event(ctx: Ctx, ev: Event, names: list[str]) -> None:
    """ops.EVENT_HOOKS: notice treasury spending and build_work without touching works/governance."""
    if not enabled(ctx.cfg):
        return
    if ev.kind == "fund_project" or (ev.kind == "law_passed" and ev.data.get("law_kind") in ("grant", "payout")):
        spent(ctx.world)
    elif ev.kind == "build_work" and ev.actor:
        worked(ctx.world, ev.actor)


ops.EVENT_HOOKS.append(_on_event)


def after_night(ctx: Ctx) -> None:
    """Pay out a treasury surplus that nobody spent for `surplus_idle_days`."""
    w, cfg = ctx.world, ctx.cfg
    if not (enabled(cfg) and governance.enabled(cfg)):
        return
    t, g = _t(cfg), w.governance
    alive = governance.voters(w)
    cap = t.get("surplus_per_villager", 0) * len(alive)
    idle = t.get("surplus_idle_days", 0)
    if not cap or not alive or g.coins <= cap or w.day - g.last_spent_day < idle:
        return
    excess = g.coins - cap
    hours = {n: h for n, h in g.work_hours.items() if n in alive}
    weights = hours or {n: 1 for n in alive}
    total = sum(weights.values())
    got: dict[str, int] = {}
    for n in sorted(weights):
        share = excess * weights[n] // total
        if share:
            ops.move_coins(g, w.agents[n], share)
            got[n] = share
    g.work_hours.clear()
    spent(w)
    if not got:
        return
    who = "worked on village projects" if hours else "live in the village"
    ctx.emit("treasury_surplus", f"The treasury held more than {cap} coins for {idle} days without spending; "
             f"{sum(got.values())} coins went to those who {who}: "
             + ", ".join(f"{n} {c}" for n, c in got.items()) + ".", visibility="public", paid=got)


# ---------- orders: value, rewards, part deliveries ----------

def value(cfg: dict, items: dict) -> int:
    return sum(cfg["items"].get(k, {}).get("value", 0) * v for k, v in items.items())


def council_reward(cfg: dict, tpl: dict) -> int:
    if not council_on(cfg):
        return tpl["reward"]
    return max(1, round(cfg["council_orders"]["reward_mult"] * value(cfg, tpl["needs"])))


def partial(o: Order, cfg: dict) -> bool:
    """Orders that take part deliveries: the mayor's (treasury) and, with council_orders on, the council's."""
    return o.payer == TREASURY or (not o.by and council_on(cfg))


def left(o: Order) -> dict[str, int]:
    got: dict[str, int] = {}
    for items in o.delivered.values():
        for k, v in items.items():
            got[k] = got.get(k, 0) + v
    return {k: v - got.get(k, 0) for k, v in o.needs.items() if v > got.get(k, 0)}


def deliver(ctx: Ctx, a: Agent, o: Order) -> None:
    """actions.fulfill_order for an order that takes part deliveries: hand over what you have of what it
    still needs and be paid your share at once (the last delivery gets what is left of the reward)."""
    w = ctx.world
    need = left(o)
    p = None
    if o.payer == TREASURY:
        p = w.projects.get(o.project)
        if p is None or p.done:
            raise ActionError(f"{o.id} was for a project that is finished")
        still = works.remaining(p)
        need = {k: min(v, still.get(k, 0)) for k, v in need.items()}
        need = {k: v for k, v in need.items() if v > 0}
        if not need:
            raise ActionError(f"{p.name} no longer needs what {o.id} asks for")
    give = {k: min(v, ops.count(a.inventory, k)) for k, v in need.items()}
    give = {k: v for k, v in give.items() if v > 0}
    if not give:
        raise ActionError(f"you have none of what {o.id} still needs: {fmt_items(need)}")
    for k, v in give.items():
        ops.burn(w, a.inventory, k, v)
    mine = o.delivered.setdefault(a.name, {})
    for k, v in give.items():
        mine[k] = mine.get(k, 0) + v
    done = not left(o)
    pay_now = o.reward - o.paid if done else min(o.reward - o.paid,
                                                  o.reward * value(ctx.cfg, give) // max(1, value(ctx.cfg, o.needs)))
    o.paid += pay_now
    ops.mint_coins(w, a, pay_now)  # held by the board (treasury orders) or paid by the council
    if o.payer != TREASURY:
        record_income(w, a, pay_now)
    if p is not None:
        for k, v in give.items():
            p.contributed[k] = p.contributed.get(k, 0) + v
        p.contributors[a.name] = p.contributors.get(a.name, 0) + sum(give.values())
    if done:
        o.status, o.fulfilled_by = "fulfilled", a.name
    rest = left(o)
    ctx.emit("order_done" if done else "order_part",
             f"{a.name} delivered {fmt_items(give)} to order {o.id} and received {pay_now} coins."
             + ("" if done else f" It still needs {fmt_items(rest)}."),
             actor=a.name, visibility="public", order=o.id, coins=pay_now, items=give)
    if p is not None:
        works.maybe_finish(ctx, p)
        if p.done and o.status == "open":
            expire(ctx, o)


def expire(ctx: Ctx, o: Order) -> None:
    """A treasury order ends: the coins not yet paid go back to the treasury."""
    o.status = "expired"
    back = o.reward - o.paid
    if back:
        ops.mint_coins(ctx.world, ctx.world.governance, back)
    ctx.emit("order_expired", f"Order {o.id} for the village is closed; {back} unpaid coins went back to the "
             "treasury.", visibility="public", order=o.id)


# ---------- the mayor's purchase ----------

class TreasuryOrderArgs(BaseModel):
    project_id: str
    needs: ItemMap = Field(description="goods the project still needs")
    reward: int = Field(gt=0, le=10000, description="coins paid from the treasury for all of them")
    days: int = Field(2, ge=1, le=7, description="how many days the order stays on the board")


@ACTIONS.action("treasury_order", "Mayor only: put an order on the board paid from the treasury: villagers deliver "
                "goods a village project needs at the square, each delivery is paid its share at once, the goods go "
                "into the project, unpaid coins come back when it closes.", TreasuryOrderArgs,
                available=lambda c, a: enabled(c.cfg) and works.enabled(c.cfg) and governance.enabled(c.cfg)
                and c.world.governance.mayor == a.name and c.world.governance.coins > 0
                and any(k not in ("labor", "coins") for p in works.open_projects(c.world) for k in works.remaining(p)))
def treasury_order(ctx: Ctx, a: Agent, args: TreasuryOrderArgs) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg) or not governance.enabled(cfg):
        raise ActionError("there is no village treasury here")
    g = w.governance
    if g.mayor != a.name:
        raise ActionError(f"only the mayor ({g.mayor or 'nobody yet'}) pays from the treasury")
    p = w.projects.get(args.project_id)
    if p is None or p.done:
        raise ActionError(f"no open project '{args.project_id}'")
    _items_known(ctx, args.needs)
    still = works.remaining(p)
    extra = {k: v for k, v in args.needs.items() if v > still.get(k, 0) or k in ("labor", "coins")}
    if extra:
        goods = {k: v for k, v in still.items() if k not in ("labor", "coins")}
        raise ActionError(f"{p.name} needs only {fmt_items(goods) or 'no goods'}")
    lo, hi = _t(cfg).get("order_price", [0.5, 2.0])
    base = value(cfg, args.needs)
    if not lo * base <= args.reward <= hi * base:
        raise ActionError(f"the reward for {fmt_items(args.needs)} must be between {round(lo * base)} and "
                          f"{int(hi * base)} coins")
    if g.coins < args.reward:
        raise ActionError(f"the treasury has {g.coins} coins")
    ops.burn_coins(w, g, args.reward)  # held by the board; paid out on delivery, the rest back on closing
    spent(w)
    o = Order(w.new_id("order"), dict(args.needs), args.reward, w.day + args.days - 1, payer=TREASURY, project=p.id)
    w.orders[o.id] = o
    ctx.emit("order", f"Mayor {a.name} put an order for the village on the board ({o.id}): {fmt_items(o.needs)} for "
             f"{p.name}, {o.reward} coins from the treasury, paid per delivery, until day {o.expires_day}.",
             actor=a.name, visibility="public", order=o.id, project=p.id)


# ---------- what villagers see ----------

def observe(world: World, name: str) -> dict:
    if not enabled(world.config):
        return {}
    a = world.agents[name]
    return {"tax_bill": bill(world, a), "earned_since_tax": a.earned_since_tax}


def facts(cfg: dict) -> str:
    base = (f"- Tax: every {cfg['tax_every_days']} days. If you cannot pay, it takes all your coins and you are "
            f"locked out of your house for {cfg['eviction_days']} days.")
    if not enabled(cfg):
        return base.replace("- Tax:", f"- Tax: {cfg['tax_amount']} coins", 1)
    t = _t(cfg)
    gov = governance.enabled(cfg)
    text = (base + f" The bill: land tax {cfg['tax_amount']} coins + {t['sales_pct']}% of the coins you got from the "
            f"trader and council orders since the last tax day + {t['wealth_pct']}% of your coins above "
            f"{t['wealth_above']}; trades between villagers are not taxed. \"time.tax\" is your bill so far. "
            f"{t['burn_pct']}% of all tax leaves the village"
            + (", the rest goes to the treasury. The mayor can change the rates by law (tax, sales_tax, wealth_tax) "
               "and buy goods for village projects with treasury_order." if gov else "."))
    if gov and t.get("surplus_per_villager"):
        text += (f" When the treasury holds more than {t['surplus_per_villager']} coins per villager and has spent "
                 f"nothing for {t['surplus_idle_days']} days, the excess goes to those who did build_work since "
                 "the last such payout (or to everyone).")
    return text


def orders_fact(cfg: dict) -> str:
    if not council_on(cfg):
        return "- Orders on the board pay the whole reward to the first person who delivers."
    return (f"- Council orders pay {cfg['council_orders']['reward_mult']}x the base value of the goods. Anyone can "
            "deliver part of a council or treasury order: each delivery is paid at once, its share of the "
            "order's value. A villager's own order pays the whole reward to the first person who delivers it all.")
