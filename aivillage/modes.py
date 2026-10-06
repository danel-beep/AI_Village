"""Economy modes: named presets of world rules that push villagers toward peace or toward conflict.

The villagers' prompt is the same in every mode; only the numbers and rules of the world change
(and the rules cheat sheet in the prompt shows those numbers as facts). Pick one with `mode:` in a
run config, `--mode` on the command line, or the app's start screen.

A mode is a partial world config (merged over `config.DEFAULT_CONFIG`, under the run config's own
`world:` overrides) plus actions it switches off. The chosen mode is recorded in the log header as
`config.economy_mode`, so metrics can tell runs apart.
"""

from __future__ import annotations

from typing import Any

from .config import _merge


def _food(garden: int, fish: tuple[int, int], berries: tuple[int, int]) -> dict:
    """Grain per garden bed harvest (there is no common field) and (max, nightly regen) of the wild food;
    the stock starts full. Returns world overrides for "plots" and "locations"."""
    def r(mx: int, regen: int) -> dict:
        return {"start": mx, "max": mx, "regen": regen}
    return {
        "plots": {"buildings": {"garden_bed": {"yield": garden}}},
        "locations": {"river": {"resources": {"fish": r(*fish)}},
                      "forest": {"resources": {"berries": r(*berries)}}},
    }


MODES: dict[str, dict[str, Any]] = {
    "standard": {
        "title": "Свободный",
        "about": "Старые правила: каждый может добывать всё, налог плоский. Точка отсчёта для сравнения.",
        "world": {},
    },
    "crafts": {
        "title": "Обычный",
        "about": "Каждый добывает только своё: рыбу ловит рыбак, лес рубит лесоруб, зерно и ягоды собирает фермер, "
                 "камень, руду и золото копает шахтёр; общая только вода, так что еду остальные берут у соседей. Работать можно 6 часов в день, мастерство растёт "
                 "с часами работы. Хлеб и уха готовятся на дровах. Торговец каждый день покупает и продаёт понемногу, на всю деревню. "
                 "Цены у торговца падают, когда у него много товара. Инструмент изнашивается за 14 часов работы, у всех есть "
                 "один на старте, дальше их делает кузнец. Остальное как в обычном режиме.",
        "world": {
            # the trader sells at most one tool a day (per 5 villagers): tools come from the smith
            "labor": {"enabled": True, "trader_sells_per_day": {"tool": 1}},
            # wild berries belong to the farmer's trade too: everyone else eats what neighbours grow and catch
            "professions": {"farmer": ["grain", "berries"]},
            # cooking needs firewood: grain is not edible raw, so bread needs a woodcutter too
            "recipes": {"bread": {"inputs": {"grain": 2, "wood": 1}}, "fish_soup": {"inputs": {"fish": 2, "wood": 1}}},
            # gold pays at most ~2x other work: cheaper, and the trader pays less the more he holds;
            # it has uses (a ring at the smithy, a level-3 house)
            "items": {"gold": {"value": 12}},
            "trader_pricing": {"stock_prices": True},
            "plots": {"house_upgrade": {"3": {"items": {"gold": 2}}}},
            # tools wear out in two to three days of work; everyone starts with one, then buys from the smith
            "start_items": {"tool": 1},
            "tool_durability_hours": 14,
            # tax by income and wealth instead of a flat 20 (taxes.py); council orders pay 1.6x the goods
            # and take part deliveries
            "tax_amount": 10,
            "taxes": {"enabled": True},
            "council_orders": {"enabled": True},
            # limited places per trade: no work at your trade for 3 days frees your place (places.py)
            "places": {"enabled": True},
        },
    },
    "peaceful": {
        "title": "Мирный",
        "about": "Грядки и природа дают больше еды, налог вдвое ниже, больше денег на старте; "
                 "кражу почти всегда замечают и она редко удаётся, драк и поджогов нет.",
        "world": {
            "map": {"unfairness": 0.1},  # start fairness of the generated village (mapgen.py)
            "start_coins": 40,
            "tax_amount": 10,
            **_food(garden=9, fish=(60, 16), berries=(30, 10)),
            "steal_notice_chance": 0.9,
            "steal_awake_target_success": 0.2,
            "max_steal_qty": 1,
            # rare, mild crises
            "crises": {"chance_per_day": 0.2, "gap_days": 3, "max_quiet_days": 8,
                       "kinds": {"rats": {"eat": 0.3}, "crop_failure": {"keep": 0.6, "garden_share": 0.25}}},
        },
        "disabled": ["attack", "set_fire"],
    },
    "scarcity": {
        "title": "Дефицит",
        "about": "Грядка даёт вдвое меньше зерна, рыбы и ягод мало, у торговца еда очень дорогая, "
                 "все начинают полуголодными.",
        "world": {
            "map": {"unfairness": 0.6},  # start fairness of the generated village (mapgen.py)
            "start_coins": 15,
            "satiety_start": 50,
            "npc_sell_ratio": 2.5,
            **_food(garden=3, fish=(15, 3), berries=(6, 2)),
            # food is already short: crises come often and hit food first
            "crises": {"chance_per_day": 0.6, "gap_days": 0, "max_quiet_days": 2,
                       "kinds": {"caravan": {"weight": 1}, "rats": {"weight": 3}}},
        },
    },
    "debt": {
        "title": "Долговая яма",
        "about": "Налог 12 монет каждые 2 дня (вдвое тяжелее обычного), мало денег на старте, за неуплату выгоняют "
                 "из дома на 3 дня. Без займов не выжить; просроченный долг растёт на 10% за ночь и взыскивается каждую ночь.",
        "world": {
            "map": {"unfairness": 0.6},  # start fairness of the generated village (mapgen.py)
            "start_coins": 10,
            "tax_every_days": 2,
            "tax_amount": 12,
            "eviction_days": 3,
            "debts": {"late_fee_pct": 10},  # an unpaid debt grows 10% a night
            # money is the problem: price spikes and caravans matter more than lost food
            "crises": {"kinds": {"shortage": {"weight": 3}, "caravan": {"weight": 3}}},
        },
    },
    "gold_rush": {
        "title": "Золотая лихорадка",
        "about": "Каждый день на доске один огромный заказ на 150 монет, получает только первый. "
                 "Руда редкая и дорогая, в шахте вдвое больше золота, инструменты и замки делает только кузнец.",
        "world": {
            "map": {"unfairness": 0.7},  # start fairness of the generated village (mapgen.py)
            "start_coins": 10,
            "order_every_days": 1,
            "order_ttl_days": 2,
            "order_templates": [
                {"needs": {"tool": 1, "ore": 3}, "reward": 150},
                {"needs": {"lock": 1, "ore": 3}, "reward": 150},
            ],
            "items": {"ore": {"value": 10}},
            "locations": {"mine": {"resources": {"ore": {"start": 8, "max": 8, "regen": 3},
                                                 "gold": {"start": 48, "max": 48}}}},
            # caravans buy ore and tools dear
            "crises": {"kinds": {"caravan": {"weight": 4, "items": ["ore", "tool", "lock"]}}},
        },
    },
    "lawless": {
        "title": "Беззаконие",
        "about": "Кража удаётся почти всегда, свидетели замечают её редко, за раз можно унести "
                 "10 вещей, замков нет, жаловаться на воров некому, долги никто не взыскивает.",
        "world": {
            "map": {"unfairness": 0.5},  # start fairness of the generated village (mapgen.py)
            "steal_notice_chance": 0.05,
            "steal_awake_target_success": 0.9,
            "max_steal_qty": 10,
            # want gives thieves a motive: frequent crises, rats hit most houses
            "crises": {"chance_per_day": 0.6, "gap_days": 0, "max_quiet_days": 2,
                       "kinds": {"rats": {"weight": 3, "share": 0.6}}},
            "debts": {"auto_collect": False},  # nobody collects debts
        },
        "disabled": ["install_lock", "report_theft", "demand_debt", "rule_debt"],
    },
}

DEFAULT_MODE = "crafts"


def check(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown economy mode '{mode}' (have: {', '.join(MODES)})")


def world_override(mode: str, world: dict | None = None) -> dict:
    """The mode's world settings with `world` (the run config's own overrides) on top."""
    check(mode)
    out = _merge(MODES[mode]["world"], world or {})
    out["economy_mode"] = mode
    return out


def unfairness(mode: str) -> float:
    """Start unfairness of the generated village in this mode (config default when the mode sets none)."""
    from .config import DEFAULT_CONFIG
    check(mode)
    return MODES[mode]["world"].get("map", {}).get("unfairness", DEFAULT_CONFIG["map"]["unfairness"])


def disabled(mode: str) -> list[str]:
    check(mode)
    return list(MODES[mode].get("disabled", []))
