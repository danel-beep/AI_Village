"""World configuration: everything tunable lives here, nothing is hardcoded in the engine.

A run is fully defined by (config, seed, decisions), which is what makes replay possible.
Override any key by passing a partial dict to `make_config`.
"""

from __future__ import annotations

import copy
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "seed": 1,
    # Time: one tick = one in-game hour. Agents act from day_start to day_end, then night runs.
    "day_start_hour": 6,
    "day_end_hour": 22,
    # Survival
    "satiety_max": 100,
    "satiety_start": 80,
    "satiety_loss_per_hour": 2,  # ~1 meal a day: fewer eat turns, more time for people
    "satiety_loss_asleep_per_hour": 2,
    "satiety_loss_night": 10,
    "starving_health_loss_per_hour": 5,
    "starving_health_loss_night": 20,
    "health_max": 100,
    "health_regen_night_at_home": 15,
    "health_regen_min_satiety": 30,
    # What happens at health 0: "hospital" (lose half the inventory, back in N days) or "death".
    "death_mode": "hospital",
    "hospital_days": 2,
    # Economy
    "start_coins": 20,
    "tax_every_days": 7,
    "tax_amount": 20,
    "eviction_days": 2,
    "work_base_yield": 1,
    "work_profession_multiplier": 3,
    "work_tool_multiplier": 2,
    "tool_durability_hours": 40,
    "max_work_hours": 4,
    "offer_ttl_ticks": 3,
    "steal_notice_chance": 0.5,
    "steal_awake_target_success": 0.5,
    "max_steal_qty": 3,
    "max_text_len": 200,
    "inbox_size": 30,
    "order_every_days": 3,
    "order_ttl_days": 3,
    "orders_per_post": 1,  # orders posted at once; scaled with the population (coins for tax)
    "fire_ticks": 4,
    "fire_water_needed": 3,
    # Items. value = base price; NPC buys at value*npc_buy_ratio, sells at value*npc_sell_ratio.
    "npc_buy_ratio": 0.5,
    "npc_sell_ratio": 1.5,
    "items": {
        "grain": {"value": 2},
        "fish": {"value": 3, "food": 15},
        "berries": {"value": 1, "food": 10},
        "wood": {"value": 2},
        "stone": {"value": 2},
        "ore": {"value": 5},
        "water": {"value": 0, "tradable": False},
        "bread": {"value": 6, "food": 40},
        "fish_soup": {"value": 7, "food": 45},
        "tool": {"value": 20},
        "lock": {"value": 15},
    },
    # Recipes: where they can be made and by whom (None = anyone).
    "recipes": {
        "bread": {"inputs": {"grain": 2}, "output": 1, "where": "home", "profession": None},
        "fish_soup": {"inputs": {"fish": 2}, "output": 1, "where": "home", "profession": None},
        "tool": {"inputs": {"wood": 2, "ore": 1}, "output": 1, "where": "smithy", "profession": "smith"},
        "lock": {"inputs": {"ore": 1, "stone": 1}, "output": 1, "where": "smithy", "profession": "smith"},
    },
    "professions": {
        "farmer": ["grain"],
        "fisher": ["fish"],
        "woodcutter": ["wood"],
        "miner": ["stone", "ore"],
        "smith": [],
    },
    # Map: a graph of locations. Homes are added per agent and connected to the square.
    "locations": {
        "square": {"name": "Village square", "neighbors": ["market", "field", "forest", "river", "smithy"]},
        "market": {"name": "Market", "neighbors": ["square"]},
        "field": {"name": "Field", "neighbors": ["square", "river"],
                  "resources": {"grain": {"start": 40, "max": 40, "regen": 10}}},
        "river": {"name": "River", "neighbors": ["square", "field"],
                  "resources": {"fish": {"start": 30, "max": 30, "regen": 8},
                                "water": {"start": 999, "max": 999, "regen": 999}}},
        "forest": {"name": "Forest", "neighbors": ["square", "mine"],
                   "resources": {"wood": {"start": 80, "max": 80, "regen": 40},
                                 "berries": {"start": 15, "max": 15, "regen": 5}}},
        "mine": {"name": "Mine", "neighbors": ["forest"],
                 "resources": {"stone": {"start": 60, "max": 60, "regen": 30},
                               "ore": {"start": 30, "max": 30, "regen": 10}}},
        "smithy": {"name": "Smithy", "neighbors": ["square"]},
    },
    "projects": {
        "bridge": {"name": "Bridge over the river", "needs": {"wood": 40, "stone": 30},
                   "reward_coins_each": 20},
    },
    # Order templates the NPC council posts on the board; one is picked at random.
    "order_templates": [
        {"needs": {"bread": 3, "fish_soup": 2}, "reward": 80},
        {"needs": {"tool": 2, "wood": 5}, "reward": 90},
        {"needs": {"lock": 1, "stone": 10, "fish": 5}, "reward": 85},
    ],
    # Seasons (backlog #10): a season scales nightly resource regrowth. Day 1 is the first day of
    # order[0]. "wither" empties resources at the first dawn of a season (field crops die in winter).
    "seasons": {
        "enabled": True,
        "length_days": 7,
        "order": ["spring", "summer", "autumn", "winter"],
        "regen_multiplier": {
            "summer": {"berries": 1.5},
            "autumn": {"grain": 1.5},
            "winter": {"grain": 0, "berries": 0, "fish": 0.5},
        },
        "wither": {"winter": {"field": ["grain"]}},
        "announce": {
            "spring": "The field grows again.",
            "winter": "The field is frozen: no grain until spring, berries are gone, fish are scarce.",
        },
    },
    # Population (aivillage/population.py): size N > len(agents) adds generated villagers (seeded names,
    # professions by weight); resources and project needs scale by max(1, N / base_size). None = just `agents`.
    "population": {
        "size": None,
        "base_size": 5,  # the map numbers above are tuned for this many villagers
        "scale_resources": True,
        "scale_projects": True,
        "scale_orders": True,  # more council orders at once: they are the main coin source besides the trader
        "profession_weights": {"farmer": 1.2, "fisher": 1.2, "woodcutter": 1, "miner": 1, "smith": 0.6},
    },
    "agents": [
        {"name": "Anna", "profession": "farmer"},
        {"name": "Boris", "profession": "fisher"},
        {"name": "Clara", "profession": "woodcutter"},
        {"name": "Dmitri", "profession": "miner"},
        {"name": "Elena", "profession": "smith"},
    ],
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def make_config(override: dict | None = None) -> dict:
    from .population import resolve
    return resolve(_merge(DEFAULT_CONFIG, override or {}))
