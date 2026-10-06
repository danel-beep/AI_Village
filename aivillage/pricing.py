"""The trader's prices: base value x ratio x crises x village works x his stock (config block `trader_pricing`).

The final live runs showed one good (gold) paying ~7x any other work: the trader bought any amount at a
fixed price. With `trader_pricing.stock_prices` on (the "crafts" mode turns it on) the trader remembers how much of
each good villagers sold him lately (`World.trader_stock`); every unit he holds lowers both his buying and
his selling price of that good by `drop_per_unit` (scaled to the population), down to `floor` of the base.
Each dawn he keeps only `keep_per_day` of his stock (he ships the rest away), so a glut wears off in a day
or two. Selling to villagers takes units out of his stock first. Prices are always shown in `trader_prices`.
"""

from __future__ import annotations

import math

from . import crises, population, works
from .state import World


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("trader_pricing", {}).get("stock_prices"))


def stock_factor(world: World, item: str) -> float:
    cfg = world.config
    if not enabled(cfg):
        return 1.0
    m = cfg["trader_pricing"]
    held = world.trader_stock.get(item, 0)
    drop = m["drop_per_unit"] / max(population.resource_scale(cfg), 1e-9)
    return max(m["floor"], 1.0 - drop * held)


def price(world: World, item: str, side: str) -> int:
    """side "buy": what a villager pays the trader; "sell": what the trader pays a villager."""
    cfg = world.config
    ratio = cfg["npc_sell_ratio"] if side == "buy" else cfg["npc_buy_ratio"]
    return max(1, int(cfg["items"][item]["value"] * ratio * crises.price_factor(world, item, side)
                      * works.sell_factor(world, side) * stock_factor(world, item)))


def prices(world: World) -> dict:
    return {i: {"buy": price(world, i, "buy"), "sell": price(world, i, "sell")}
            for i, v in world.config["items"].items() if v.get("tradable", True)}


def trader_bought(world: World, item: str, qty: int) -> None:
    """A villager sold `qty` of `item` to the trader."""
    if enabled(world.config):
        world.trader_stock[item] = world.trader_stock.get(item, 0) + qty


def trader_sold(world: World, item: str, qty: int) -> None:
    """The trader sold `qty` of `item` to a villager: it comes out of his stock first."""
    if enabled(world.config) and item in world.trader_stock:
        left = world.trader_stock[item] - qty
        if left > 0:
            world.trader_stock[item] = left
        else:
            del world.trader_stock[item]


def new_day(world: World) -> None:
    if not enabled(world.config):
        return
    keep = world.config["trader_pricing"]["keep_per_day"]
    world.trader_stock = {i: k for i, n in sorted(world.trader_stock.items()) if (k := math.floor(n * keep)) > 0}


def facts(cfg: dict) -> str:
    m = cfg["trader_pricing"]
    return (f"- The trader's prices follow his stock: each unit of a good villagers sold him lately lowers his "
            f"buying and selling price of that good (down to {m['floor']:.0%} of normal); every night he keeps only "
            f"{m['keep_per_day']:.0%} of his stock. trader_prices always shows today's prices.")


def tool_fact(cfg: dict) -> str:
    return (f"- Carrying a tool multiplies what you gather per hour by {cfg['work_tool_multiplier']}; a tool wears out "
            f"after {cfg['tool_durability_hours']} hours of work.")
